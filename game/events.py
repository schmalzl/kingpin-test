"""Random + scripted events. Probability = f(event_frequency, wanted, police_pressure); outcomes seeded per (user, cycle).
Severe events need high wanted (counterplay: lay low / lawyers). Choice events stay pending 3 cycles, then default."""
import json
import random

from . import progression as prog
from .errors import GameError

PENDING_DAYS = 5
EV = lambda **k: k  # noqa: E731

FIRST = EV(id="first_shakedown", title="A Visit From Your Landlord's 'Friend'", severity="warning", weight=0,
           description="A broad man in a good coat leans in your doorway. Word is out that someone new is moving product on this block, "
                       "and the block has a tax. He is polite about it, which is worse.",
           choices=[EV(label="Pay the fixer ($50)", requires_cash=50, effects={"cash": -50, "strain": 2, "rep": 1}),
                    EV(label="Refuse and stand your ground", requires_cash=0, effects={"rep": -2, "wanted": 3, "strain": 5}),
                    EV(label="Smile, stall, and slip out the back", requires_cash=0, effects={"strain": 3, "wanted": 1, "cash": -20})],
           default=1)

DEFS = [
    EV(id="corner_patrol", title="Patrol on Your Corner", severity="warning", weight=3, min_wanted=10,
       description="A squad car idles on your block for an hour. Nothing happens, but everyone noticed.",
       effects={"wanted": 2, "strain": 2}),
    EV(id="police_search", title="Unannounced Search", severity="severe", weight=2, min_wanted=30,
       description="Officers arrive with paperwork and questions. You can bring in a lawyer to limit the damage, or cooperate and eat the loss.",
       choices=[EV(label="Retain a lawyer ($120)", requires_cash=120, effects={"cash": -120, "wanted": -5, "strain": 3}),
                EV(label="Cooperate and take the loss", requires_cash=0, effects={"lose_inventory_pct": 25, "wanted": 3, "strain": 6})],
       default=1),
    EV(id="fine_notice", title="Fine Notice", severity="warning", weight=2, min_wanted=15,
       description="A citation arrives, citing 'nuisance activity' at your address.",
       effects={"cash_pct": [5, 10], "wanted": 1}),
    EV(id="market_glut", title="Herbal Glut", severity="info", weight=4,
       description="A big delivery floods the district. Greenleaf prices sag.",
       effects={"market": {"category": "Herbal", "factor": 0.8, "cycles": 3}}),
    EV(id="supply_crunch", title="Stimulant Supply Crunch", severity="info", weight=4,
       description="A courier goes missing and Sparkdust gets scarce.",
       effects={"market": {"category": "Stimulant", "factor": 1.3, "cycles": 3}}),
    EV(id="festival_weekend", title="Festival Weekend", severity="good", weight=3,
       description="Crowds flood the riverside. Demand for Greenleaf jumps.",
       effects={"market": {"category": "Herbal", "factor": 1.2, "cycles": 2}}),
    EV(id="rival_interference", title="Rival Interference", severity="warning", weight=2, min_level=2,
       description="Someone has been telling your customers you are unreliable.", effects={"rep": -2, "strain": 5}),
    EV(id="contact_tip", title="A Useful Tip", severity="good", weight=2,
       description="A contact passes along a pricing pattern you had not noticed.", effects={"xp": 15, "rep": 1}),
    EV(id="unexpected_expense", title="Unexpected Expense", severity="warning", weight=3,
       description="A repair bill, a lost deposit, a favour that was not free.", effects={"cash": [-60, -25]}),
    EV(id="lucky_break", title="Lucky Break", severity="good", weight=2,
       description="You find an old debt someone finally decided to pay.", effects={"cash": [30, 90]}),
    EV(id="sleepless_week", title="Sleepless Stretch", severity="warning", weight=2,
       description="Too many late nights. Your hands are not quite steady.", effects={"strain": 8, "condition": -5}),
    EV(id="informant_rumour", title="Informant Rumour", severity="warning", weight=2, min_wanted=20,
       description="You hear someone on your block is talking to the wrong people.", effects={"wanted": 4}),
    EV(id="lawyer_offer", title="A Lawyer Offers Cover", severity="info", weight=2, min_wanted=20,
       description="A local attorney offers a retainer that would quiet things down.",
       choices=[EV(label="Pay the retainer ($80)", requires_cash=80, effects={"cash": -80, "wanted": -10, "strain": -2}),
                EV(label="Decline", requires_cash=0, effects={})], default=1),
    EV(id="crystal_shortage", title="Bluefrost Shortage", severity="info", weight=3, min_level=3,
       description="A processing delay chokes the Bluefrost supply.",
       effects={"market": {"category": "Crystal", "factor": 1.35, "cycles": 4}}),
    EV(id="quiet_streets", title="Quiet Streets", severity="good", weight=2, min_wanted=5,
       description="The heat drifts elsewhere for a while.", effects={"wanted": -3, "strain": -2}),
    EV(id="district_crackdown", title="District Crackdown", severity="severe", weight=2, min_wanted=20,
       description="A visible enforcement push rattles the whole market.",
       effects={"wanted": 5, "market": {"category": "Herbal", "factor": 1.25, "cycles": 3}}),
    EV(id="shipment_delay", title="Shipment Delay", severity="info", weight=2, min_level=2,
       description="Trucks are late across town and Sparkdust runs short.",
       effects={"market": {"category": "Stimulant", "factor": 1.2, "cycles": 2}}),
    EV(id="rival_offer", title="A Rival's Side Job", severity="good", weight=1, min_level=3,
       description="A rival crew offers quick cash for a favour that draws attention.",
       choices=[EV(label="Take the side job (+$100, wanted +3)", requires_cash=0, effects={"cash": 100, "wanted": 3, "rep": -1}),
                EV(label="Pass", requires_cash=0, effects={})], default=1),
]
BY_ID = {d["id"]: d for d in DEFS + [FIRST]}


def _roll(eff: dict, rng: random.Random, cash: int) -> dict:
    out = {}
    pp = prog.bal()["police_pressure"]
    for k, v in eff.items():
        if k == "market":
            continue
        if k == "cash_pct":
            out["cash"] = -max(20, cash * rng.randint(*v) // 100)
            continue
        v = rng.randint(*v) if isinstance(v, list) else v
        if k == "wanted" and v > 0:
            v = max(1, round(v * pp))
        out[k] = v
    return out


def _apply(db, uid, eff, cycle, rng) -> str:
    cash = db.execute("SELECT cash FROM player_state WHERE user_id=?", (uid,)).fetchone()["cash"]
    rolled = _roll(eff, rng, cash)
    if rolled.get("lose_inventory_pct"):
        from . import shops
        rolled["lose_inventory_pct"] = int(rolled["lose_inventory_pct"] * (1 - min(90, shops.perk_total(db, uid, "search_loss_reduction_pct")) / 100))
    out = prog.apply_effects(db, uid, rolled, cycle, "event")
    text = prog.describe(out) if out else "no direct effect"
    m = eff.get("market")
    if m:
        db.execute("INSERT INTO world_mods(category,factor,expires_day) VALUES (?,?,?)",
                   (m["category"], m["factor"], cycle + m["cycles"] - 1))
        text += f"; {m['category']} prices x{m['factor']} for {m['cycles']} cycles"
    return text


def _fire(db, uid, d, cycle, rng):
    if d.get("choices"):
        prog.record_event(db, uid, cycle, d["id"], d["title"], d["severity"], d["description"], "Awaiting your decision",
                          "pending", d["choices"], d["default"], cycle + PENDING_DAYS)
    else:
        text = _apply(db, uid, d["effects"], cycle, rng)
        prog.record_event(db, uid, cycle, d["id"], d["title"], d["severity"], d["description"], text)


def _resolve(db, uid, row, idx, cycle, check):
    ch = json.loads(row["choices"])[idx]
    if check:
        cash = db.execute("SELECT cash FROM player_state WHERE user_id=?", (uid,)).fetchone()["cash"]
        if ch.get("requires_cash", 0) > cash:
            raise GameError("Insufficient funds for that option.")
    text = _apply(db, uid, ch["effects"], cycle, random.Random(f"resolve:{row['id']}:{idx}"))
    db.execute("UPDATE events SET status='resolved', resolved_choice=?, effects=? WHERE id=?",
               (idx, f"{ch['label']}: {text}", row["id"]))
    return text


MARKET_ONLY = {"market_glut", "supply_crunch", "festival_weekend", "crystal_shortage", "shipment_delay"}


def expire_pending(db, uid, day):
    """Undecided choice events fall back to their default (only evaluated while the player is online)."""
    for row in db.execute("SELECT * FROM events WHERE user_id=? AND status='pending' AND expires_cycle<?", (uid, day)).fetchall():
        _resolve(db, uid, row, row["default_choice"], day, check=False)


def fire_market(db, d, day):
    """Global market event: one price modifier for everybody, plus a news line in every player's feed."""
    m = d["effects"]["market"]
    db.execute("INSERT INTO world_mods(category,factor,expires_day) VALUES (?,?,?)", (m["category"], m["factor"], day + m["cycles"] - 1))
    text = f"{m['category']} prices x{m['factor']} for {m['cycles']} cycles"
    for r in db.execute("SELECT id FROM users WHERE role='player' AND status='active'").fetchall():
        prog.record_event(db, r["id"], day, d["id"], d["title"], d["severity"], d["description"], text)


def fire_personal(db, uid, day, rng, first=False):
    if first:
        _fire(db, uid, FIRST, day, rng)
        return
    ps = db.execute("SELECT * FROM player_state WHERE user_id=?", (uid,)).fetchone()
    pool = [d for d in DEFS if d["id"] not in MARKET_ONLY and ps["wanted"] >= d.get("min_wanted", 0)
            and ps["wanted"] <= d.get("max_wanted", 100) and ps["level"] >= d.get("min_level", 1)]
    if pool:
        _fire(db, uid, rng.choices(pool, weights=[d["weight"] for d in pool])[0], day, rng)


def respond(db, uid, event_id, idx) -> dict:
    row = db.execute("SELECT * FROM events WHERE id=? AND user_id=? AND status='pending'", (event_id, uid)).fetchone()
    if not row:
        raise GameError("No pending event with that id.", 404)
    n = len(json.loads(row["choices"]))
    if isinstance(idx, bool) or not isinstance(idx, int) or not 0 <= idx < n:
        raise GameError("Invalid choice.")
    cycle = db.execute("SELECT cycle FROM campaigns WHERE user_id=?", (uid,)).fetchone()["cycle"]
    text = _resolve(db, uid, row, idx, cycle, check=True)
    prog.incr(db, uid, "events_responded")
    return {"ok": True, "result": text}


def seen_upto(db, uid) -> int:
    return prog.counter(db, uid, "events_seen_upto")


def unread_count(db, uid) -> int:
    return db.execute("SELECT COUNT(*) AS n FROM events WHERE user_id=? AND id>?", (uid, seen_upto(db, uid))).fetchone()["n"]


def ack(db, uid, upto) -> int:
    """Mark events up to id `upto` as read (watermark never moves backwards or past the newest event)."""
    if isinstance(upto, bool) or not isinstance(upto, int) or upto < 0:
        raise GameError("Invalid event id.")
    newest = db.execute("SELECT COALESCE(MAX(id),0) AS m FROM events WHERE user_id=?", (uid,)).fetchone()["m"]
    upto = min(upto, newest)
    if upto > seen_upto(db, uid):
        prog.set_counter(db, uid, "events_seen_upto", upto)
    return upto


def clear(db, uid) -> int:
    """Delete resolved events from the feed. Events still awaiting a decision are never removed."""
    n = db.execute("DELETE FROM events WHERE user_id=? AND status='resolved'", (uid,)).rowcount
    ack(db, uid, 10**12)
    return n


def view(db, uid, limit=40, news_only=False) -> list[dict]:
    seen = seen_upto(db, uid)
    q = "SELECT * FROM events WHERE user_id=?" + (" AND (id>? OR status='pending')" if news_only else "") + " ORDER BY id DESC LIMIT ?"
    args = (uid, seen, limit) if news_only else (uid, limit)
    out = []
    for r in db.execute(q, args):
        ch = json.loads(r["choices"]) if r["choices"] else None
        out.append({"id": r["id"], "cycle": r["cycle"], "severity": r["severity"], "title": r["title"],
                    "description": r["description"], "effects": r["effects"], "status": r["status"],
                    "expires_cycle": r["expires_cycle"], "resolved_choice": r["resolved_choice"], "unread": r["id"] > seen,
                    "choices": [{"label": c["label"], "requires_cash": c.get("requires_cash", 0)} for c in ch] if ch else None})
    return out
