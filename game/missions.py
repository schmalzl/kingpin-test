"""Missions: objectives are evaluated by the server from counters and live state; rewards are granted once via claim."""
from . import progression as prog
from .errors import GameError

C = lambda k, n, label: {"t": "c", "k": k, "n": n, "label": label}  # noqa: E731
S = lambda f, n, label, op=">=": {"t": "s", "f": f, "n": n, "op": op, "label": label}  # noqa: E731

MISSIONS = [
    dict(id="c1_first_steps", chapter=1, kind="main", title="First Steps", requires=[],
         context="Mara slides a coffee across the canteen counter. 'You want in? Then learn the prices first. Buy something. Anything small.'",
         objectives=[C("units_bought", 5, "Buy 5 units on the market")], rewards={"cash": 50, "xp": 30, "rep": 1}),
    dict(id="c1_move_product", chapter=1, kind="main", title="Move Some Product", requires=["c1_first_steps"],
         context="'Inventory that sits is money that rots,' Mara says. 'Sell a little. See how the market treats you.'",
         objectives=[C("units_sold", 3, "Sell 3 units")], rewards={"cash": 40, "xp": 30}),
    dict(id="c1_in_the_black", chapter=1, kind="main", title="In the Black", requires=["c1_move_product"],
         context="Selling is easy. Selling for more than you paid is the whole game. The dealer's cut is 10%, so buy low and wait for the market to move.",
         objectives=[C("profit_total", 40, "Earn $40 total profit from sales")], rewards={"cash": 80, "xp": 40, "rep": 1}),
    dict(id="c1_read_the_street", chapter=1, kind="main", title="Read the Street", requires=["c1_first_steps"],
         context="Prices breathe. Let a few cycles pass (2 real minutes each) and watch how they move.",
         objectives=[C("cycles", 3, "Let 3 cycles pass")], rewards={"cash": 30, "xp": 20}),
    dict(id="c1_heat", chapter=1, kind="main", title="Heat", requires=["c1_read_the_street"],
         context="Someone will notice you eventually. When a street event asks you to decide, decide. Ignoring it is also a choice, just a worse one.",
         objectives=[C("events_responded", 1, "Respond to a street event")], rewards={"xp": 40, "rep": 2}),
    dict(id="c1_cushion", chapter=1, kind="main", title="A Little Cushion", requires=["c1_in_the_black", "c1_heat"],
         context="Chapter 1 ends when you stop living from sale to sale. Build a cash reserve.",
         objectives=[S("cash", 800, "Hold $800 cash")], rewards={"cash": 100, "xp": 80, "rep": 2}),
    dict(id="c2_first_contract", chapter=2, kind="main", title="Word Gets Around", requires=["c1_cushion"],
         context="Old Teo has been asking about you. Open the Contacts tab and deliver on a contract.",
         objectives=[C("contracts_done", 1, "Complete a contract")], rewards={"cash": 120, "xp": 60, "rep": 3}),
    dict(id="c2_name_recognition", chapter=2, kind="main", title="Name Recognition", requires=["c2_first_contract"],
         context="People start using your name without being asked. Make that a habit.",
         objectives=[S("reputation", 10, "Reach reputation 10")], rewards={"cash": 100, "xp": 70}),
    dict(id="c2_volume", chapter=2, kind="main", title="Volume Seller", requires=["c2_first_contract"],
         context="Bigger customers want proof you can handle volume.",
         objectives=[C("units_sold", 40, "Sell 40 units in total")], rewards={"cash": 150, "xp": 80}),
    dict(id="c2_level3", chapter=2, kind="main", title="Rising", requires=["c1_cushion"],
         context="Higher tiers and better contacts open at street level 3.",
         objectives=[S("level", 3, "Reach street level 3")], rewards={"cash": 100, "xp": 40}),
    dict(id="c2_low_profile", chapter=2, kind="main", title="Low Profile", requires=["c2_level3"],
         context="Growth draws eyes. Show you can grow quietly.",
         objectives=[S("level", 3, "Be at least street level 3"), S("wanted", 10, "Keep wanted at 10 or below", "<=")],
         rewards={"cash": 150, "xp": 90, "rep": 2}),
    dict(id="c2_three_contracts", chapter=2, kind="main", title="Reliable Hands", requires=["c2_first_contract"],
         context="Reliable people get the better contracts.",
         objectives=[C("contracts_done", 3, "Complete 3 contracts")], rewards={"cash": 250, "xp": 120, "rep": 4}),
    dict(id="s_rest_up", chapter=0, kind="side", title="Rest Up", requires=[],
         context="Running on fumes helps nobody. Use the Rest action once.",
         objectives=[C("actions_rest", 1, "Use Rest once")], rewards={"cash": 20, "xp": 10}),
    dict(id="s_lay_low", chapter=0, kind="side", title="Lie Low", requires=[],
         context="When the street is loud, go quiet. Use the Lay Low action once.",
         objectives=[C("actions_lay_low", 1, "Use Lay Low once")], rewards={"cash": 20, "xp": 10}),
]
BY_ID = {m["id"]: m for m in MISSIONS}


def _val(db, uid, ps, o):
    return prog.counter(db, uid, o["k"]) if o["t"] == "c" else ps[o["f"]]


def _met(o, v):
    return v >= o["n"] if o.get("op", ">=") == ">=" else v <= o["n"]


def _done(db, uid):
    return {r["mission_id"] for r in db.execute("SELECT mission_id FROM mission_progress WHERE user_id=? AND status='completed'", (uid,))}


def view(db, uid) -> list[dict]:
    ps = db.execute("SELECT * FROM player_state WHERE user_id=?", (uid,)).fetchone()
    done = _done(db, uid)
    out = []
    for m in MISSIONS:
        objs = []
        for o in m["objectives"]:
            v = _val(db, uid, ps, o)
            objs.append({"label": o["label"], "value": v, "target": o["n"], "met": _met(o, v)})
        unlocked = all(r in done for r in m["requires"])
        status = "completed" if m["id"] in done else ("available" if unlocked else "locked")
        out.append({"id": m["id"], "chapter": m["chapter"], "kind": m["kind"], "title": m["title"], "context": m["context"],
                    "rewards": m["rewards"], "status": status, "objectives": objs,
                    "claimable": status == "available" and all(o["met"] for o in objs),
                    "requires": [BY_ID[r]["title"] for r in m["requires"] if r not in done]})
    return out


def active(db, uid):
    for m in view(db, uid):
        if m["kind"] == "main" and m["status"] == "available":
            return m
    return None


def claim(db, uid, mission_id) -> dict:
    m = BY_ID.get(mission_id)
    if not m:
        raise GameError("Unknown mission.", 404)
    cur = next(x for x in view(db, uid) if x["id"] == mission_id)
    if cur["status"] == "completed":
        raise GameError("Mission already completed.")
    if cur["status"] == "locked":
        raise GameError("Mission is locked.", 403)
    if not cur["claimable"]:
        raise GameError("Objectives not complete yet.")
    cycle = db.execute("SELECT cycle FROM campaigns WHERE user_id=?", (uid,)).fetchone()["cycle"]
    db.execute("INSERT INTO mission_progress(user_id,mission_id,status,cycle) VALUES (?,?,'completed',?)", (uid, mission_id, cycle))
    r = dict(m["rewards"])
    if r.get("cash"):
        r["cash"] = round(r["cash"] * prog.bal()["reward_multiplier"])
    fx = prog.apply_effects(db, uid, r, cycle, "mission")
    prog.incr(db, uid, "missions_done")
    prog.record_event(db, uid, cycle, "mission_done", f"Mission complete: {m['title']}", "good", "", prog.describe(fx))
    return {"ok": True, "effects_text": prog.describe(fx)}
