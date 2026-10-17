"""Player actions. Every number (cost, effects, cooldown...) comes from BALANCE["actions"] in config.py.
Actions no longer take game time; only their cost and cooldown (cooldown_days, 0 = unlimited) limit them."""
import json

from . import economy as eco
from . import progression as prog
from . import security as sec
from .database import tx
from .errors import GameError


def _defs() -> dict:
    return prog.bal()["actions"]


def _blocked(db, uid, a, ps):
    limit = prog.bal()["broke_cash_limit"]
    if a.get("broke_only") and (ps["cash"] >= limit or eco.used_storage(db, uid) > 0):
        return f"Only when you have under ${limit} and no stock"
    return None


def _last(db, uid, kind):
    return db.execute("SELECT MAX(cycle) AS c FROM action_log WHERE user_id=? AND kind=?", (uid, kind)).fetchone()["c"]


def _ps(db, uid):
    return db.execute("SELECT p.*, c.cycle FROM player_state p JOIN campaigns c ON c.user_id=p.user_id WHERE p.user_id=?", (uid,)).fetchone()


def view(db, uid) -> list[dict]:
    ps = _ps(db, uid)
    out = []
    for k, a in _defs().items():
        last, cd = _last(db, uid, k), a.get("cooldown_days", 0)
        wait = max(0, last + cd - ps["cycle"]) if last is not None and cd else 0
        blocked = _blocked(db, uid, a, ps)
        why = (blocked or (f"Requires street level {a['min_level']}" if ps["level"] < a["min_level"] else
                           f"Cooldown: {wait} more cycle(s)" if wait else "Insufficient funds" if ps["cash"] < a["cost"] else None))
        out.append({"id": k, "label": a["label"], "desc": a["desc"], "cost": a["cost"], "effects": prog.describe(a["effects"]),
                    "cooldown": cd, "confirm": a.get("confirm", False), "available": why is None, "reason": why,
                    "group": a.get("group", "Other"), "hidden": ps["level"] < a["min_level"] or bool(blocked)})
    return out


def perform(uid, action_id, key, volatility_mult=1.0) -> dict:
    key = eco._key(key)
    a = _defs().get(action_id)
    if not a:
        raise GameError("Unknown action.", 404)
    with tx() as db:
        rep = db.execute("SELECT result FROM action_log WHERE user_id=? AND idem_key=?", (uid, key)).fetchone()
        if rep:
            return {**json.loads(rep["result"]), "replayed": True}
        ps = _ps(db, uid)
        if ps["level"] < a["min_level"]:
            raise GameError(f"Locked: requires street level {a['min_level']}.", 403)
        blocked = _blocked(db, uid, a, ps)
        if blocked:
            raise GameError(blocked + ".")
        last, cd = _last(db, uid, action_id), a.get("cooldown_days", 0)
        if cd and last is not None and ps["cycle"] - last < cd:
            raise GameError("That action is on cooldown.")
        if ps["cash"] < a["cost"]:
            raise GameError("Insufficient funds.")
        prog.add_cash(db, uid, -a["cost"], "action", ps["cycle"])
        fx = prog.apply_effects(db, uid, a["effects"], ps["cycle"], "action")
        prog.incr(db, uid, f"actions_{action_id}")
        res = {"ok": True, "action": action_id, "cycle": ps["cycle"], "effects_text": prog.describe(fx) + f"; cost ${a['cost']}", "events": []}
        db.execute("INSERT INTO action_log(user_id,idem_key,kind,cycle,at,result) VALUES (?,?,?,?,?,?)",
                   (uid, key, action_id, ps["cycle"], sec.iso(sec.now()), json.dumps(res)))
        return res
