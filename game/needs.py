"""Hydration and nutrition. They drain every cycle (only while the player is online). Low sanity or low health makes them drain faster.
Low nutrition hurts health; low hydration hurts health AND sanity. All numbers live in config.py BALANCE["needs"]."""
from . import progression as prog


def rates(ps) -> dict:
    b = prog.bal()["needs"]
    sanity, mult, reasons = 100 - ps["strain"], 1.0, []
    if sanity < b["low_threshold"]:
        mult += b["low_bonus"]
        reasons.append(f"Your sanity is low (below {b['low_threshold']}%), so you lose {int(b['low_bonus'] * 100)}% more.")
    if ps["condition"] < b["low_threshold"]:
        mult += b["low_bonus"]
        reasons.append(f"Your health is low (below {b['low_threshold']}%), so you lose {int(b['low_bonus'] * 100)}% more.")
    return {"hydration": int(b["hydration_loss"] * mult + 0.5), "nutrition": int(b["nutrition_loss"] * mult + 0.5), "mult": mult, "reasons": reasons}


def damage(ps) -> dict:
    b = prog.bal()["needs"]
    health = sanity = 0
    notes = []
    if ps["nutrition"] < b["critical"]:
        health += b["starvation_health_loss"]
        notes.append(f"You are starving: health -{b['starvation_health_loss']} per cycle.")
    if ps["hydration"] < b["critical"]:
        health += b["dehydration_health_loss"]; sanity += b["dehydration_sanity_loss"]
        notes.append(f"You are dehydrated: health -{b['dehydration_health_loss']} and sanity -{b['dehydration_sanity_loss']} per cycle.")
    return {"health": health, "sanity": sanity, "notes": notes}


def describe(ps) -> dict:
    """What the player panel shows: current loss per cycle and the reasons behind it."""
    b, r, d = prog.bal()["needs"], rates(ps), damage(ps)
    explain = [f"Base loss: {b['hydration_loss']} hydration and {b['nutrition_loss']} nutrition per cycle.", *r["reasons"], *d["notes"],
               f"Below {b['critical']}% nutrition costs health; below {b['critical']}% hydration costs health and sanity. Food and drinks are sold in the Shop."]
    return {"hydration": r["hydration"], "nutrition": r["nutrition"], "explain": " ".join(explain), "health_loss": d["health"], "sanity_loss": d["sanity"]}


def tick(db, uid: str, day: int) -> None:
    ps = db.execute("SELECT * FROM player_state WHERE user_id=?", (uid,)).fetchone()
    r = rates(ps)
    hyd, nut = max(0, ps["hydration"] - r["hydration"]), max(0, ps["nutrition"] - r["nutrition"])
    db.execute("UPDATE player_state SET hydration=?, nutrition=? WHERE user_id=?", (hyd, nut, uid))
    d = damage({**dict(ps), "hydration": hyd, "nutrition": nut})
    eff = {}
    if d["health"]:
        eff["condition"] = -d["health"]
    if d["sanity"]:
        eff["strain"] = d["sanity"]
    if eff:
        prog.apply_effects(db, uid, eff, day, "needs")
    crit = prog.bal()["needs"]["critical"]
    for flag, low, title, text in (("flag_dehydrated", hyd < crit, "You are dehydrated", "Your body is shutting down and your head is spinning. Find something to drink."),
                                   ("flag_starving", nut < crit, "You are starving", "You have not eaten properly in a long time. Your health is suffering.")):
        was = prog.counter(db, uid, flag) == 1
        if low and not was:
            prog.set_counter(db, uid, flag, 1)
            prog.record_event(db, uid, day, flag, title, "warning", text, "Buy food and drinks in the Shop.")
        elif not low and was:
            prog.set_counter(db, uid, flag, 0)
