"""Contacts (people/factions) and optional delivery contracts. Rewards beat the 90% dealer spread, so contracts matter."""
from . import progression as prog
from . import security as sec
from .errors import GameError
from .items import ITEMS

MAX_ACTIVE = 3
REWARD_MULT = 1.35
MIN_CONDITION = 30

CONTACTS = [
    dict(id="mara", name="Mara Quill", faction="Dockside Co-op", min_level=1, min_rep=0, prefers="Herbal", order="small",
         difficulty=1, reliability=0.9,
         profile="Runs the loading-bay canteen and introduced you to the trade. Blunt, fair, and she remembers who paid on time."),
    dict(id="teo", name="Old Teo", faction="Dockside Co-op", min_level=1, min_rep=0, prefers="Herbal", order="medium",
         difficulty=2, reliability=0.8,
         profile="Corner-shop owner who buys in bulk and haggles out of habit. Never raises his voice, never overpays."),
    dict(id="dex", name="Dex Harlan", faction="Velvet Row Syndicate", min_level=2, min_rep=2, prefers="Stimulant", order="medium",
         difficulty=3, reliability=0.6,
         profile="Nightclub promoter with a great smile and a flexible memory for deadlines."),
    dict(id="ines", name="Ines Varga", faction="Independent", min_level=3, min_rep=4, prefers="Crystal", order="small",
         difficulty=3, reliability=0.85,
         profile="A collector who cares about quality above price. If you cut corners she will know before you do."),
    dict(id="rook", name="Rook", faction="Ashgate Crew", min_level=4, min_rep=8, prefers="Crystal", order="large",
         difficulty=4, reliability=0.7,
         profile="Courier for a rougher crowd. Speaks in short sentences and long silences."),
    dict(id="halloran", name="Dr. Halloran", faction="Independent", min_level=4, min_rep=10, prefers="Opioid-class", order="small",
         difficulty=4, reliability=0.75,
         profile="Runs a late-night clinic and an even later-night side business. Pays well, asks little, trusts no one."),
    dict(id="juno", name="Juno Pell", faction="Velvet Row Syndicate", min_level=5, min_rep=15, prefers="Hallucinogen-class", order="medium",
         difficulty=4, reliability=0.65,
         profile="Party broker whose guest lists are a currency of their own. Charming right up to the invoice."),
    dict(id="calder", name="Sir Calder", faction="Independent", min_level=6, min_rep=25, prefers="Designer", order="small",
         difficulty=5, reliability=0.9,
         profile="A private buyer who has never once raised his voice or paid late. Both facts are unsettling."),
]
C_BY_ID = {c["id"]: c for c in CONTACTS}

# id, contact, title, item, qty, days, rep_reward, rep_penalty, xp, min_level, min_rep, text
_T = [
    ("c_mara_start", "mara", "Canteen Order", "GRN-L", 6, 8, 1, 1, 15, 1, 0, "The canteen needs a few bags before the weekend crowd."),
    ("c_teo_bulk", "teo", "Corner-Shop Restock", "GRN-L", 10, 6, 2, 1, 25, 1, 0, "Teo wants ten units, cash on delivery, no discussion."),
    ("c_teo_high", "teo", "Quality Shelf", "GRN-H", 8, 7, 3, 2, 35, 2, 0, "A better grade for the shelf behind the counter."),
    ("c_dex_club", "dex", "Club Night", "SPK-L", 6, 6, 2, 2, 25, 2, 2, "Dex needs it before Friday. 'Friday' is flexible for him, not for you."),
    ("c_dex_vip", "dex", "VIP Section", "SPK-H", 6, 7, 3, 2, 35, 2, 2, "The VIP crowd wants the good stuff, and they are watching."),
    ("c_ines_blue", "ines", "Collector's Request", "BLU-L", 6, 8, 3, 3, 45, 3, 4, "Ines will inspect every unit."),
    ("c_rook_run", "rook", "Ashgate Run", "BLU-H", 5, 8, 4, 3, 55, 4, 8, "A quick hand-off. Do not be late."),
    ("c_halloran_clinic", "halloran", "After-Hours Delivery", "AMB-L", 4, 8, 4, 4, 60, 4, 10, "The doctor wants a small, quiet delivery."),
    ("c_juno_party", "juno", "Private Party", "VLT-L", 4, 8, 4, 3, 65, 5, 15, "Juno has a guest list and a deadline."),
    ("c_calder_private", "calder", "Private Order", "NVA-L", 3, 9, 6, 5, 90, 6, 25, "Sir Calder's order is small. His patience is smaller."),
]
TEMPLATES = {t[0]: dict(zip(("id", "contact", "title", "item", "qty", "days", "rep_reward", "rep_penalty", "xp",
                             "min_level", "min_rep", "text"), t)) for t in _T}


def _days(t: dict) -> int:
    return t["days"] * prog.bal()["contract_day_multiplier"]


def reward_for(t: dict) -> int:
    return round(t["qty"] * ITEMS[t["item"]]["base_price"] * REWARD_MULT * prog.bal()["reward_multiplier"])


def _score(db, uid, cid) -> int:
    r = db.execute("SELECT score FROM contact_relations WHERE user_id=? AND contact_id=?", (uid, cid)).fetchone()
    return r["score"] if r else 0


def _bump(db, uid, cid, d):
    db.execute("INSERT INTO contact_relations(user_id,contact_id,score) VALUES (?,?,?) "
               "ON CONFLICT(user_id,contact_id) DO UPDATE SET score=score+excluded.score", (uid, cid, d))


def _reason(c, ps, score):
    if score <= -15:
        return "Relationship broken"
    if ps["level"] < c["min_level"]:
        return f"Requires street level {c['min_level']}"
    if c["min_rep"] > 0 and ps["reputation"] < c["min_rep"]:
        return f"Requires reputation {c['min_rep']}"
    return None


def _ps(db, uid):
    return db.execute("SELECT * FROM player_state WHERE user_id=?", (uid,)).fetchone()


def view(db, uid) -> dict:
    ps = _ps(db, uid)
    rows = {r["contract_id"]: r for r in db.execute("SELECT * FROM contracts WHERE user_id=?", (uid,))}
    contacts = []
    for c in CONTACTS:
        sc = _score(db, uid, c["id"])
        why = _reason(c, ps, sc)
        contacts.append({k: c[k] for k in ("id", "name", "faction", "profile", "prefers", "order", "difficulty", "reliability")}
                        | {"score": sc, "available": why is None, "locked_reason": why})
    contracts = []
    for t in TEMPLATES.values():
        c = C_BY_ID[t["contact"]]
        why = _reason(c, ps, _score(db, uid, c["id"])) or (
            f"Requires street level {t['min_level']}" if ps["level"] < t["min_level"] else
            f"Requires reputation {t['min_rep']}" if t["min_rep"] > 0 and ps["reputation"] < t["min_rep"] else None)
        r = rows.get(t["id"])
        held = db.execute("SELECT COALESCE(SUM(quantity),0) AS n FROM inventory WHERE user_id=? AND item_id=? AND location=?",
                          (uid, t["item"], ps["location"])).fetchone()["n"]
        contracts.append({"id": t["id"], "contact": c["name"], "title": t["title"], "text": t["text"],
                          "item_id": t["item"], "item": ITEMS[t["item"]]["name"], "qty": t["qty"], "days": _days(t),
                          "reward": reward_for(t), "rep_reward": t["rep_reward"], "rep_penalty": t["rep_penalty"],
                          "status": r["status"] if r else ("locked" if why else "offered"),
                          "locked_reason": why if not r else None,
                          "deadline": r["deadline_cycle"] if r else None, "held": held})
    return {"contacts": contacts, "contracts": contracts}


def accept(db, uid, contract_id) -> dict:
    t = TEMPLATES.get(contract_id)
    if not t:
        raise GameError("Unknown contract.", 404)
    ps = db.execute("SELECT p.*, c.cycle FROM player_state p JOIN campaigns c ON c.user_id=p.user_id WHERE p.user_id=?", (uid,)).fetchone()
    if db.execute("SELECT 1 FROM contracts WHERE user_id=? AND contract_id=?", (uid, contract_id)).fetchone():
        raise GameError("You already took (or finished) this contract.")
    c = C_BY_ID[t["contact"]]
    why = _reason(c, ps, _score(db, uid, c["id"]))
    if why or ps["level"] < t["min_level"] or (t["min_rep"] > 0 and ps["reputation"] < t["min_rep"]):
        raise GameError(f"Locked: {why or 'requirements not met'}.", 403)
    if ps["condition"] < MIN_CONDITION:
        raise GameError("You are too run down to take on work. Rest first.")
    if db.execute("SELECT COUNT(*) AS n FROM contracts WHERE user_id=? AND status='active'", (uid,)).fetchone()["n"] >= MAX_ACTIVE:
        raise GameError(f"You can only hold {MAX_ACTIVE} active contracts.")
    db.execute("INSERT INTO contracts(user_id,contract_id,status,accepted_cycle,deadline_cycle) VALUES (?,?,?,?,?)",
               (uid, contract_id, "active", ps["cycle"], ps["cycle"] + _days(t)))
    return {"ok": True, "deadline": ps["cycle"] + _days(t)}


def fulfill(db, uid, contract_id) -> dict:
    t = TEMPLATES.get(contract_id)
    row = db.execute("SELECT * FROM contracts WHERE user_id=? AND contract_id=? AND status='active'", (uid, contract_id)).fetchone()
    if not t or not row:
        raise GameError("No active contract with that id.", 404)
    ps = db.execute("SELECT p.*, c.cycle FROM player_state p JOIN campaigns c ON c.user_id=p.user_id WHERE p.user_id=?", (uid,)).fetchone()
    inv = db.execute("SELECT * FROM inventory WHERE user_id=? AND item_id=? AND location=?", (uid, t["item"], ps["location"])).fetchone()
    if not inv or inv["quantity"] < t["qty"]:
        raise GameError(f"You need {t['qty']} x {ITEMS[t['item']]['name']} at the selected stash.")
    cost = inv["cost_total"] if t["qty"] == inv["quantity"] else inv["cost_total"] * t["qty"] // inv["quantity"]
    if t["qty"] == inv["quantity"]:
        db.execute("DELETE FROM inventory WHERE user_id=? AND item_id=? AND location=?", (uid, t["item"], ps["location"]))
    else:
        db.execute("UPDATE inventory SET quantity=quantity-?, cost_total=cost_total-? WHERE user_id=? AND item_id=? AND location=?",
                   (t["qty"], cost, uid, t["item"], ps["location"]))
    reward = reward_for(t)
    db.execute("UPDATE contracts SET status='completed' WHERE user_id=? AND contract_id=?", (uid, contract_id))
    fx = prog.apply_effects(db, uid, {"cash": reward, "xp": t["xp"], "rep": t["rep_reward"]}, ps["cycle"], "contract")
    db.execute("UPDATE player_stats SET revenue=revenue+?, tx_count=tx_count+1, largest_profit=MAX(largest_profit,?) WHERE user_id=?",
               (reward, reward - cost, uid))
    _bump(db, uid, t["contact"], 5)
    prog.incr(db, uid, "contracts_done")
    prog.record_event(db, uid, ps["cycle"], "contract_done", f"Contract delivered: {t['title']}", "good",
                      f"{C_BY_ID[t['contact']]['name']} is satisfied.", prog.describe(fx))
    return {"ok": True, "effects_text": prog.describe(fx), "reward": reward}


def expire(db, uid, new_cycle: int) -> None:
    for r in db.execute("SELECT * FROM contracts WHERE user_id=? AND status='active' AND deadline_cycle<?", (uid, new_cycle)).fetchall():
        t = TEMPLATES[r["contract_id"]]
        db.execute("UPDATE contracts SET status='failed' WHERE user_id=? AND contract_id=?", (uid, r["contract_id"]))
        fx = prog.apply_effects(db, uid, {"rep": -t["rep_penalty"], "strain": 2}, new_cycle, "contract")
        _bump(db, uid, t["contact"], -5)
        prog.incr(db, uid, "contracts_failed")
        prog.record_event(db, uid, new_cycle, "contract_failed", f"Contract missed: {t['title']}", "warning",
                          f"{C_BY_ID[t['contact']]['name']} will not forget the delay.", prog.describe(fx))
