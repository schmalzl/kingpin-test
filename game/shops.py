"""Shops: static shops from content/shops.json plus season specials created by the admin.
Items give instant effects (sanity, health, ...) and/or permanent perks. Prices are paid from cash and booked in the ledger."""
import json
from pathlib import Path

from config import BASE_DIR
from . import economy
from . import progression as prog
from . import security as sec
from .database import tx
from .errors import GameError

PERK_TEXT = {"capacity": "Storage +{v}", "sell_bonus_pct": "Sell prices +{v}%", "heat_shield_pct": "Police attention from sales -{v}%",
             "search_loss_reduction_pct": "Seizures in searches -{v}%", "xp_bonus_pct": "Experience +{v}%"}
PERK_CAP = {"capacity": 200, "sell_bonus_pct": 50, "heat_shield_pct": 90, "search_loss_reduction_pct": 90, "xp_bonus_pct": 200}
EFFECT_TEXT = {"sanity": "Sanity", "condition": "Health", "hydration": "Hydration", "nutrition": "Nutrition", "xp": "XP", "rep": "Reputation", "wanted": "Wanted"}


def _norm(raw: dict, where: str) -> dict:
    for k, t in (("id", str), ("name", str)):
        if not isinstance(raw.get(k), t) or not raw[k].strip():
            raise ValueError(f"content/shops.json: {where} needs '{k}'")
    if not isinstance(raw.get("price"), int) or isinstance(raw["price"], bool) or raw["price"] < 0:
        raise ValueError(f"content/shops.json: {where} needs a whole-number 'price' >= 0")
    perks, effects = raw.get("perks", {}), raw.get("effects", {})
    if not set(perks) <= set(PERK_TEXT) or not set(effects) <= set(EFFECT_TEXT):
        raise ValueError(f"content/shops.json: {where} has an unknown perk or effect")
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in [*perks.values(), *effects.values()]):
        raise ValueError(f"content/shops.json: {where} perk/effect values must be whole numbers")
    if not perks and not effects:
        raise ValueError(f"content/shops.json: {where} needs at least one perk or effect")
    return {"id": raw["id"], "name": raw["name"], "description": raw.get("description", ""), "price": raw["price"],
            "min_level": int(raw.get("min_level", 1)), "max_per_player": int(raw.get("max_per_player", 0)), "perks": perks, "effects": effects}


def _load():
    data = json.loads((Path(BASE_DIR) / "content" / "shops.json").read_text(encoding="utf-8"))
    shops, items = [], {}
    for s in data["shops"]:
        its = []
        for r in s["items"]:
            it = _norm(r, f"item {r.get('id')}")
            if it["id"] in items:
                raise ValueError(f"content/shops.json: duplicate item id {it['id']}")
            items[it["id"]] = it
            its.append(it)
        shops.append({"id": s["id"], "name": s["name"], "description": s.get("description", ""), "items": its})
    return shops, items


SHOPS, STATIC_ITEMS = _load()


def _special(r) -> dict:
    return {"id": f"special:{r['id']}", "name": r["name"], "description": r["description"], "price": r["price"], "min_level": r["min_level"],
            "max_per_player": r["max_per_player"], "perks": json.loads(r["perks"]), "effects": json.loads(r["effects"])}


def specials(db) -> list[dict]:
    return [_special(r) for r in db.execute("SELECT * FROM special_items ORDER BY id")]


def find_item(db, item_id: str):
    if item_id in STATIC_ITEMS:
        return STATIC_ITEMS[item_id]
    if isinstance(item_id, str) and item_id.startswith("special:") and item_id[8:].isdigit():
        r = db.execute("SELECT * FROM special_items WHERE id=?", (int(item_id[8:]),)).fetchone()
        return _special(r) if r else None
    return None


def text_of(it: dict) -> str:
    parts = [f"{EFFECT_TEXT[k]} {'+' if v > 0 else ''}{v}" for k, v in it["effects"].items()]
    parts += [PERK_TEXT[k].format(v=v) for k, v in it["perks"].items()]
    return " | ".join(parts)


def perk_total(db, uid: str, perk: str) -> int:
    total = 0
    for r in db.execute("SELECT item_id, quantity FROM purchases WHERE user_id=?", (uid,)).fetchall():
        it = find_item(db, r["item_id"])
        if it:
            total += it["perks"].get(perk, 0) * r["quantity"]
    return min(total, PERK_CAP.get(perk, 0))


def parse_special(data: dict) -> dict:
    """Validate an admin-created season special."""
    name = " ".join(str(data.get("name", "")).split())
    desc = str(data.get("description", "")).strip()[:200]
    if not 1 <= len(name) <= 40:
        raise GameError("The name must be 1-40 characters.")
    try:
        price, lvl, mx = int(data.get("price")), int(data.get("min_level", 1)), int(data.get("max_per_player", 0))
    except (TypeError, ValueError):
        raise GameError("Price, level and limit must be whole numbers.")
    if not (0 <= price <= 10_000_000 and 1 <= lvl <= prog.LEVEL_MAX and 0 <= mx <= 99):
        raise GameError("Price 0-10,000,000, level 1-15 and limit 0-99 are allowed.")
    perks, effects = {}, {}
    pt, pv = data.get("perk"), data.get("perk_value")
    if pt:
        if pt not in PERK_TEXT:
            raise GameError("Unknown perk.")
        if not isinstance(pv, int) or isinstance(pv, bool) or not 1 <= pv <= PERK_CAP[pt]:
            raise GameError(f"The perk value must be a whole number from 1 to {PERK_CAP[pt]}.")
        perks[pt] = pv
    et, ev = data.get("effect"), data.get("effect_value")
    if et:
        if et not in EFFECT_TEXT:
            raise GameError("Unknown effect.")
        if not isinstance(ev, int) or isinstance(ev, bool) or ev == 0 or abs(ev) > 100:
            raise GameError("The effect value must be a non-zero whole number between -100 and 100.")
        effects[et] = ev
    if not perks and not effects:
        raise GameError("Choose at least a perk or an instant effect.")
    return {"name": name, "description": desc, "price": price, "min_level": lvl, "max_per_player": mx, "perks": perks, "effects": effects}


def view(db, uid: str) -> list[dict]:
    ps = db.execute("SELECT * FROM player_state WHERE user_id=?", (uid,)).fetchone()
    owned = {r["item_id"]: r["quantity"] for r in db.execute("SELECT item_id, quantity FROM purchases WHERE user_id=?", (uid,))}
    shops = [dict(s) for s in SHOPS]
    sp = specials(db)
    if sp:
        shops.append({"id": "specials", "name": "Season Specials", "description": "Limited items, only available this season.", "items": sp})
    out = []
    for s in shops:
        items = []
        for it in s["items"]:
            n = owned.get(it["id"], 0)
            reason = (f"Requires street level {it['min_level']}" if ps["level"] < it["min_level"] else
                      "Limit reached" if it["max_per_player"] and n >= it["max_per_player"] else
                      "Insufficient funds" if ps["cash"] < it["price"] else None)
            items.append({"id": it["id"], "name": it["name"], "description": it["description"], "price": it["price"], "owned": n,
                          "max": it["max_per_player"], "text": text_of(it), "available": reason is None, "reason": reason,
                          "hidden": ps["level"] < it["min_level"]})
        out.append({"id": s["id"], "name": s["name"], "description": s["description"], "items": items})
    return out


def buy(uid: str, item_id, key) -> dict:
    key = economy._key(key)
    with tx() as db:
        rep = db.execute("SELECT result FROM action_log WHERE user_id=? AND idem_key=?", (uid, key)).fetchone()
        if rep:
            return {**json.loads(rep["result"]), "replayed": True}
        it = find_item(db, item_id)
        if not it:
            raise GameError("That item is not for sale.", 404)
        ps = db.execute("SELECT p.*, c.cycle FROM player_state p JOIN campaigns c ON c.user_id=p.user_id WHERE p.user_id=?", (uid,)).fetchone()
        n = db.execute("SELECT COALESCE(SUM(quantity),0) AS n FROM purchases WHERE user_id=? AND item_id=?", (uid, it["id"])).fetchone()["n"]
        if ps["level"] < it["min_level"]:
            raise GameError(f"Locked: requires street level {it['min_level']}.", 403)
        if it["max_per_player"] and n >= it["max_per_player"]:
            raise GameError("You cannot buy more of this item.")
        if ps["cash"] < it["price"]:
            raise GameError("Insufficient funds.")
        prog.add_cash(db, uid, -it["price"], "shop", ps["cycle"])
        fx = prog.apply_effects(db, uid, it["effects"], ps["cycle"], "shop") if it["effects"] else {}
        if it["perks"].get("capacity"):
            db.execute("UPDATE player_state SET capacity=capacity+? WHERE user_id=?", (it["perks"]["capacity"], uid))
        db.execute("INSERT INTO purchases(user_id,item_id,quantity) VALUES (?,?,1) ON CONFLICT(user_id,item_id) DO UPDATE SET quantity=quantity+1", (uid, it["id"]))
        db.execute("UPDATE player_stats SET expenditure=expenditure+?, tx_count=tx_count+1 WHERE user_id=?", (it["price"], uid))
        prog.incr(db, uid, "shop_purchases")
        res = {"ok": True, "item": it["name"], "price": it["price"], "effects_text": (prog.describe(fx) if fx else "") or text_of(it)}
        db.execute("INSERT INTO action_log(user_id,idem_key,kind,cycle,at,result) VALUES (?,?,?,?,?,?)",
                   (uid, key, "shop", ps["cycle"], sec.iso(sec.now()), json.dumps(res)))
        return res
