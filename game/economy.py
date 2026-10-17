"""Authoritative economy logic. Every mutation runs inside database.tx() and is idempotent via a client key."""
import json
import re

from . import market as mk
from . import progression as prog
from . import security as sec
from .database import tx
from .errors import GameError
from .items import ITEMS

MAX_QTY = 1000
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def lock_reason(item: dict, ps) -> str | None:
    """Why an item is locked for this player, or None. Reputation only gates items that require some (> 0)."""
    if ps["level"] < item["min_level"]:
        return f"Requires street level {item['min_level']}"
    if item["min_reputation"] > 0 and ps["reputation"] < item["min_reputation"]:
        return f"Requires reputation {item['min_reputation']}"
    return None


def _qty(v) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= MAX_QTY:
        raise GameError(f"Quantity must be a whole number from 1 to {MAX_QTY}.")
    return v


def _key(v) -> str:
    if not isinstance(v, str) or not KEY_RE.match(v):
        raise GameError("Missing or invalid idempotency key.")
    return v


def _state(db, uid):
    return db.execute("SELECT p.*, c.cycle FROM player_state p JOIN campaigns c ON c.user_id=p.user_id "
                      "WHERE p.user_id=?", (uid,)).fetchone()


def used_storage(db, uid, location=None) -> int:
    q, a = "SELECT COALESCE(SUM(quantity),0) AS n FROM inventory WHERE user_id=?", [uid]
    if location:
        q += " AND location=?"; a.append(location)
    return db.execute(q, a).fetchone()["n"]


def _replay(db, uid, key):
    r = db.execute("SELECT result FROM transactions WHERE user_id=? AND idem_key=?", (uid, key)).fetchone()
    return {**json.loads(r["result"]), "replayed": True} if r else None


def _record(db, uid, key, kind, cycle, item_id, qty, unit, total, profit, ledger_amount, ledger_kind, cash_after, summary):
    cur = db.execute(
        "INSERT INTO transactions(user_id,idem_key,kind,item_id,quantity,unit_price,total,profit,cycle,at,result) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (uid, key, kind, item_id, qty, unit, total, profit, cycle, sec.iso(sec.now()), json.dumps(summary)))
    txid = cur.lastrowid
    if ledger_amount:
        db.execute("INSERT INTO financial_ledger(user_id,at,cycle,kind,amount,cash_after,tx_id) VALUES (?,?,?,?,?,?,?)",
                   (uid, sec.iso(sec.now()), cycle, ledger_kind, ledger_amount, cash_after, txid))
    return txid


def _quote(db, item_id) -> int:
    return mk.live_price(db, item_id)


def buy(uid: str, item_id, quantity, key) -> dict:
    qty, key = _qty(quantity), _key(key)
    with tx() as db:
        if (rep := _replay(db, uid, key)):
            return rep
        item = ITEMS.get(item_id)
        if not item:
            raise GameError("Unknown item.", 404)
        ps = _state(db, uid)
        why = lock_reason(item, ps)
        if why:
            raise GameError(f"Locked: {why.lower()}.", 403)
        price = _quote(db, item_id)
        total = price * qty
        if total > ps["cash"]:
            raise GameError("Insufficient funds.")
        if used_storage(db, uid) + qty > ps["capacity"]:
            raise GameError("Not enough storage space.")
        cash = ps["cash"] - total
        db.execute("UPDATE player_state SET cash=? WHERE user_id=?", (cash, uid))
        db.execute("INSERT INTO inventory(user_id,item_id,location,quantity,cost_total,acquired_cycle) VALUES (?,?,?,?,?,?) "
                   "ON CONFLICT(user_id,item_id,location) DO UPDATE SET quantity=quantity+excluded.quantity, "
                   "cost_total=cost_total+excluded.cost_total", (uid, item_id, ps["location"], qty, total, ps["cycle"]))
        db.execute("UPDATE player_stats SET expenditure=expenditure+?, tx_count=tx_count+1 WHERE user_id=?", (total, uid))
        prog.incr(db, uid, "units_bought", qty)
        mk.apply_trade_impact(db, item_id, qty, True, ps["cycle"])
        res = {"ok": True, "kind": "buy", "item_id": item_id, "quantity": qty, "unit_price": price, "total": total, "cash": cash}
        _record(db, uid, key, "buy", ps["cycle"], item_id, qty, price, total, None, -total, "buy", cash, res)
        return res


def sell(uid: str, item_id, quantity, key) -> dict:
    qty, key = _qty(quantity), _key(key)
    with tx() as db:
        if (rep := _replay(db, uid, key)):
            return rep
        if item_id not in ITEMS:
            raise GameError("Unknown item.", 404)
        ps = _state(db, uid)
        inv = db.execute("SELECT * FROM inventory WHERE user_id=? AND item_id=? AND location=?",
                         (uid, item_id, ps["location"])).fetchone()
        if not inv or inv["quantity"] < qty:
            raise GameError("Insufficient inventory at the selected stash.")
        from . import shops
        bonus = min(50, shops.perk_total(db, uid, "sell_bonus_pct"))
        unit = max(1, int(mk.sell_price(_quote(db, item_id)) * (1 + bonus / 100)))
        revenue = unit * qty
        cost_removed = inv["cost_total"] if qty == inv["quantity"] else inv["cost_total"] * qty // inv["quantity"]
        profit = revenue - cost_removed
        if qty == inv["quantity"]:
            db.execute("DELETE FROM inventory WHERE user_id=? AND item_id=? AND location=?", (uid, item_id, ps["location"]))
        else:
            db.execute("UPDATE inventory SET quantity=quantity-?, cost_total=cost_total-? WHERE user_id=? AND item_id=? AND location=?",
                       (qty, cost_removed, uid, item_id, ps["location"]))
        cash = ps["cash"] + revenue
        db.execute("UPDATE player_state SET cash=? WHERE user_id=?", (cash, uid))
        db.execute("UPDATE player_stats SET revenue=revenue+?, tx_count=tx_count+1, "
                   "largest_profit=MAX(largest_profit,?), largest_loss=MAX(largest_loss,?) WHERE user_id=?",
                   (revenue, profit, -profit, uid))
        prog.incr(db, uid, "units_sold", qty)
        if profit > 0:
            prog.incr(db, uid, "profit_total", profit)
        fx = prog.on_sale(db, uid, ITEMS[item_id], profit, ps["cycle"])
        mk.apply_trade_impact(db, item_id, qty, False, ps["cycle"])
        res = {"ok": True, "kind": "sell", "item_id": item_id, "quantity": qty, "unit_price": unit,
               "total": revenue, "profit": profit, "cash": cash, "effects": fx, "effects_text": prog.describe(fx)}
        _record(db, uid, key, "sell", ps["cycle"], item_id, qty, unit, revenue, profit, revenue, "sell", cash, res)
        return res


def bank_transfer(uid: str, action, amount, key) -> dict:
    """Move cash into the bank or back out. Booked in the ledger, idempotent, atomic."""
    key = _key(key)
    if action not in ("deposit", "withdraw"):
        raise GameError("Unknown bank action.")
    if isinstance(amount, bool) or not isinstance(amount, int) or not 1 <= amount <= 10**9:
        raise GameError("Enter a whole amount of at least $1.")
    with tx() as db:
        rep = db.execute("SELECT result FROM action_log WHERE user_id=? AND idem_key=?", (uid, key)).fetchone()
        if rep:
            return {**json.loads(rep["result"]), "replayed": True}
        ps = _state(db, uid)
        if action == "deposit" and amount > ps["cash"]:
            raise GameError("You do not have that much cash on you.")
        if action == "withdraw" and amount > ps["bank"]:
            raise GameError("You do not have that much in the bank.")
        delta = -amount if action == "deposit" else amount
        prog.add_cash(db, uid, delta, action, ps["cycle"])
        db.execute("UPDATE player_state SET bank=bank-? WHERE user_id=?", (delta, uid))
        now = db.execute("SELECT cash, bank FROM player_state WHERE user_id=?", (uid,)).fetchone()
        res = {"ok": True, "action": action, "amount": amount, "cash": now["cash"], "bank": now["bank"]}
        db.execute("INSERT INTO action_log(user_id,idem_key,kind,cycle,at,result) VALUES (?,?,?,?,?,?)",
                   (uid, key, "bank", ps["cycle"], sec.iso(sec.now()), json.dumps(res)))
        return res


def init_player_economy(db, uid: str, start_cash: int) -> None:
    """Called inside the player-creation transaction."""
    db.execute("INSERT INTO player_stats(user_id) VALUES (?)", (uid,))
    db.execute("INSERT INTO financial_ledger(user_id,at,cycle,kind,amount,cash_after) VALUES (?,?,?,?,?,?)",
               (uid, sec.iso(sec.now()), 0, "start", start_cash, start_cash))


# ---------- read models ----------
def market_view(db, uid: str) -> list[dict]:
    ps = _state(db, uid)
    owned = {r["item_id"]: r["quantity"] for r in
             db.execute("SELECT item_id, quantity FROM inventory WHERE user_id=? AND location=?", (uid, ps["location"]))}
    out = []
    live = mk.live_prices(db)
    for r in db.execute("SELECT * FROM world_market"):
        it = ITEMS.get(r["item_id"])
        if it is None:
            continue
        why = lock_reason(it, ps)
        out.append({k: it[k] for k in ("id", "symbol", "name", "category", "tier", "description", "min_level")} | mk.item_info(it, r) | {
            "price": live.get(r["item_id"], r["price"]), "prev_price": r["prev_price"], "sell_price": mk.sell_price(live.get(r["item_id"], r["price"])),
            "supply": round(r["supply"], 2), "demand": round(r["demand"], 2),
            "unlocked": why is None, "locked_reason": why, "owned": owned.get(r["item_id"], 0)})
    return sorted(out, key=lambda x: (x["min_level"], x["id"]))


def inventory_view(db, uid: str) -> dict:
    ps = _state(db, uid)
    rows, total_value = [], 0
    live = mk.live_prices(db)
    for r in db.execute("SELECT i.*, m.price FROM inventory i LEFT JOIN world_market m "
                        "ON m.item_id=i.item_id WHERE i.user_id=? ORDER BY i.item_id", (uid,)):
        val = mk.sell_price(live.get(r["item_id"]) or r["price"] or 1) * r["quantity"]
        total_value += val
        rows.append({"item_id": r["item_id"], "name": ITEMS.get(r["item_id"], {}).get("name", r["item_id"]), "location": r["location"],
                     "quantity": r["quantity"], "avg_cost": round(r["cost_total"] / r["quantity"], 2),
                     "cost_total": r["cost_total"], "est_value": val, "unrealized": val - r["cost_total"]})
    return {"location": ps["location"], "capacity": ps["capacity"], "used": used_storage(db, uid),
            "items": rows, "est_value": total_value}
