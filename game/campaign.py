"""Player campaign start state and reset (used for per-player resets and for new seasons)."""
from . import economy
from . import progression as prog

RESET_TABLES = ["financial_ledger", "transactions", "action_log", "inventory", "events", "contact_relations", "contracts",
                "mission_progress", "counters", "purchases", "player_stats", "player_state", "save_exports"]


def start_state(db, uid: str, day: int) -> None:
    b = prog.bal()
    db.execute("INSERT INTO player_state(user_id,level,xp,cash,bank,reputation,wanted,strain,condition,capacity,location) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
               (uid, b["start_level"], b["start_xp"], b["start_cash"], b["start_bank"], b["start_reputation"], b["start_wanted"],
                b["start_strain"], b["start_condition"], b["start_capacity"], "starter_flat"))
    economy.init_player_economy(db, uid, b["start_cash"])
    db.execute("UPDATE campaigns SET cycle=? WHERE user_id=?", (day, uid))


def reset_player(db, uid: str, day: int = 1) -> None:
    for t in RESET_TABLES:
        db.execute(f"DELETE FROM {t} WHERE user_id=?", (uid,))
    start_state(db, uid, day)
