"""Central place where player stats change: XP/levels, reputation, wanted, strain, condition, cash, counters.
Every other module calls apply_effects() so clamps, ledger entries and level-ups stay consistent."""
import json

from flask import current_app

from . import security as sec

LEVEL_MAX = 15


def bal() -> dict:
    return current_app.config["BALANCE"]


def xp_for_level(level: int) -> int:
    """Cumulative XP needed to reach `level` (level 1 = 0)."""
    return 100 * (level - 1) ** 2


def level_for_xp(xp: int) -> int:
    lvl = 1
    while lvl < LEVEL_MAX and xp >= xp_for_level(lvl + 1):
        lvl += 1
    return lvl


def incr(db, uid, key, n=1):
    db.execute("INSERT INTO counters(user_id,key,value) VALUES (?,?,?) "
               "ON CONFLICT(user_id,key) DO UPDATE SET value=value+excluded.value", (uid, key, n))


def set_counter(db, uid, key, value: int):
    db.execute("INSERT INTO counters(user_id,key,value) VALUES (?,?,?) "
               "ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value", (uid, key, int(value)))


def set_max(db, uid, key, v):
    db.execute("INSERT INTO counters(user_id,key,value) VALUES (?,?,?) "
               "ON CONFLICT(user_id,key) DO UPDATE SET value=MAX(value,excluded.value)", (uid, key, v))


def counter(db, uid, key) -> int:
    r = db.execute("SELECT value FROM counters WHERE user_id=? AND key=?", (uid, key)).fetchone()
    return r["value"] if r else 0


def add_cash(db, uid, amount: int, kind: str, cycle: int) -> int:
    """Change cash (floored at 0) and write a ledger line. Returns the amount actually applied."""
    cash = db.execute("SELECT cash FROM player_state WHERE user_id=?", (uid,)).fetchone()["cash"]
    new = max(0, cash + int(amount))
    actual = new - cash
    if actual:
        db.execute("UPDATE player_state SET cash=? WHERE user_id=?", (new, uid))
        db.execute("INSERT INTO financial_ledger(user_id,at,cycle,kind,amount,cash_after) VALUES (?,?,?,?,?,?)",
                   (uid, sec.iso(sec.now()), cycle, kind, actual, new))
    return actual


def record_event(db, uid, cycle, event_id, title, severity, description, effects="", status="resolved",
                 choices=None, default_choice=None, expires=None) -> int:
    cur = db.execute(
        "INSERT INTO events(user_id,event_id,cycle,severity,title,description,effects,status,choices,default_choice,expires_cycle) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (uid, event_id, cycle, severity, title, description, effects, status,
         json.dumps(choices) if choices is not None else None, default_choice, expires))
    return cur.lastrowid


def _lose_inventory(db, uid, pct: int) -> int:
    lost = 0
    for r in db.execute("SELECT * FROM inventory WHERE user_id=?", (uid,)).fetchall():
        n = r["quantity"] * pct // 100
        if n <= 0:
            continue
        cost = r["cost_total"] * n // r["quantity"]
        if n >= r["quantity"]:
            db.execute("DELETE FROM inventory WHERE user_id=? AND item_id=? AND location=?", (uid, r["item_id"], r["location"]))
        else:
            db.execute("UPDATE inventory SET quantity=quantity-?, cost_total=cost_total-? WHERE user_id=? AND item_id=? AND location=?",
                       (n, cost, uid, r["item_id"], r["location"]))
        lost += n
    return lost


def apply_effects(db, uid, eff: dict, cycle: int, kind: str = "effect") -> dict:
    """eff keys: cash, xp, rep, wanted, strain, condition, lose_inventory_pct. Returns the actual deltas."""
    if "sanity" in eff:  # sanity is the player-facing inverse of strain (+sanity = -strain)
        eff = dict(eff)
        eff["strain"] = eff.get("strain", 0) - eff.pop("sanity")
    out = {}
    if eff.get("cash"):
        out["cash"] = add_cash(db, uid, eff["cash"], kind, cycle)
    ps = db.execute("SELECT * FROM player_state WHERE user_id=?", (uid,)).fetchone()
    new = {}
    xp_gain = 0
    if eff.get("xp"):
        from . import shops
        perk = 1 + min(200, shops.perk_total(db, uid, "xp_bonus_pct")) / 100
        xp_gain = int(eff["xp"] * bal()["xp_multiplier"] * (0.75 if ps["strain"] >= 70 else 1.0) * perk)
        xp_gain = max(1, xp_gain) if eff["xp"] > 0 else xp_gain
    if xp_gain:
        new["xp"] = max(0, ps["xp"] + xp_gain); out["xp"] = xp_gain
    for key, col, lo, hi in (("rep", "reputation", -10**6, 10**6), ("wanted", "wanted", 0, 100),
                             ("strain", "strain", 0, 100), ("condition", "condition", 0, 100),
                             ("hydration", "hydration", 0, 100), ("nutrition", "nutrition", 0, 100)):
        if eff.get(key):
            v = min(hi, max(lo, ps[col] + int(eff[key])))
            if v != ps[col]:
                new[col] = v; out[key] = v - ps[col]
    if new:
        old_level = ps["level"]
        lvl = level_for_xp(new.get("xp", ps["xp"]))
        if lvl > old_level:
            new["level"] = lvl
            new["capacity"] = max(ps["capacity"], bal()["start_capacity"] + bal()["capacity_per_level"] * (lvl - 1))
            out["level_up"] = lvl
        db.execute("UPDATE player_state SET " + ",".join(f"{c}=?" for c in new) + " WHERE user_id=?",
                   (*new.values(), uid))
        if "reputation" in new:
            set_max(db, uid, "max_rep", new["reputation"])
        if "wanted" in new:
            set_max(db, uid, "max_wanted", new["wanted"])
        if lvl > old_level:
            record_event(db, uid, cycle, "level_up", f"Street level {lvl}", "good",
                         "Your name carries further. Storage grew and new market tiers may be open.")
    if eff.get("lose_inventory_pct"):
        out["units_lost"] = _lose_inventory(db, uid, eff["lose_inventory_pct"])
    return out


def describe(out: dict) -> str:
    names = {"xp": "XP", "rep": "reputation", "wanted": "wanted", "strain": "strain", "condition": "condition", "hydration": "hydration", "nutrition": "nutrition"}
    parts = []
    for k, v in out.items():
        if k == "level_up":
            parts.append(f"level up to {v}")
        elif k == "units_lost":
            parts.append(f"{v} units seized")
        elif k == "strain":
            parts.append(f"sanity {'+' if -v > 0 else ''}{-v}")
        elif k == "cash":
            parts.append(f"cash {'+' if v > 0 else '-'}${abs(v)}")
        else:
            parts.append(f"{names.get(k, k)} {'+' if v > 0 else ''}{v}")
    return ", ".join(parts) if parts else "no change"


def on_sale(db, uid, item: dict, profit: int, cycle: int) -> dict:
    eff = {}
    if profit > 0:
        eff["xp"] = min(50, max(1, profit // 5))
        if profit >= 20:
            eff["rep"] = 2 if item["tier_key"] in ("P", "E") else 1
    heat = item["heat"]
    if heat:
        from . import shops
        shield = min(90, shops.perk_total(db, uid, "heat_shield_pct"))
        w = round(heat * bal()["police_pressure"] * (1 - shield / 100))
        if shield == 0:
            w = max(1, w)
        if w > 0:
            eff["wanted"] = w
    return apply_effects(db, uid, eff, cycle)
