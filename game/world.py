"""Real-time world clock. 2 real minutes = 1 game day (BALANCE["day_seconds"]).
 * The market advances for everybody, logged in or not, once the server runs (background thread + lazy catch-up on requests).
 * Players age with wall-clock time (derived from account creation), also while offline.
 * Personal events (police, fines, decisions) fire only for ONLINE players (valid session), spaced 10-15 real minutes apart.
 * Global market events happen to everybody and are announced in every player's news feed."""
import random
import threading
import time
from datetime import timedelta

from flask import current_app

from . import campaign
from . import needs
from . import events as ev
from . import market as mk
from . import progression as prog
from . import security as sec
from .database import get_db, tx

MAX_CATCHUP_DAYS = 1500


def _ms() -> int:
    return int(time.time() * 1000)


def get_state(db, key, default=None):
    r = db.execute("SELECT value FROM world_state WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default


def set_state(db, key, value):
    db.execute("INSERT INTO world_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


def _ds() -> int:
    return prog.bal()["day_seconds"]


def init_world(db) -> None:
    if get_state(db, "epoch") is None:
        set_state(db, "epoch", sec.iso(sec.now() - timedelta(seconds=_ds())))  # the first day starts immediately ("Day 1")
        set_state(db, "last_day", "1")
    if get_state(db, "season_name") is None:
        set_state(db, "season_name", "Season 1")
        set_state(db, "season_id", "1")
    mk.ensure_market(db, day_now(db))
    db.commit()


def season_info(db) -> dict:
    started = max(0.0, _elapsed(db) - _ds())  # the epoch is set one cycle before the season really starts
    return {"name": get_state(db, "season_name", "Season 1"), "id": int(get_state(db, "season_id", "1")), "day": day_now(db),
            "real_day": int(started // 86400) + 1}


def new_season(db, name: str, reset_players: bool) -> dict:
    """Start a new season: day counter back to 1, fresh market, old saves invalid; optionally reset every player. Caller owns the tx."""
    old_day = day_now(db)
    set_state(db, "season_id", int(get_state(db, "season_id", "1")) + 1)
    set_state(db, "season_name", name)
    set_state(db, "epoch", sec.iso(sec.now() - timedelta(seconds=_ds())))
    set_state(db, "last_day", "1")
    set_state(db, "next_market_event_ms", "0")
    db.execute("DELETE FROM special_items")  # season specials only last one season
    for t in ("world_price_history", "world_market", "world_mods"):
        db.execute(f"DELETE FROM {t}")
    mk.ensure_market(db, 1)
    # keep day-based timers of players who are NOT reset meaningful in the new timeline
    db.execute("UPDATE contracts SET deadline_cycle=MAX(3, deadline_cycle-?), accepted_cycle=0 WHERE status='active'", (old_day - 1,))
    db.execute("UPDATE events SET expires_cycle=6 WHERE status='pending'")
    db.execute("UPDATE action_log SET cycle=0")
    db.execute("UPDATE campaigns SET cycle=1")
    n = 0
    if reset_players:
        for r in db.execute("SELECT id FROM users WHERE role='player'").fetchall():
            campaign.reset_player(db, r["id"], 1)
            n += 1
    return {"season": season_info(db), "players_reset": n}


def _elapsed(db) -> float:
    return (sec.now() - sec.parse(get_state(db, "epoch"))).total_seconds()


def day_now(db) -> int:
    return int(_elapsed(db) // _ds())


def ms_to_next_day(db) -> int:
    ds = _ds()
    return int((ds - _elapsed(db) % ds) * 1000)


def online_ids(db) -> set:
    cfg = current_app.config
    t = sec.now()
    rows = db.execute("SELECT DISTINCT s.user_id FROM sessions s JOIN users u ON u.id=s.user_id "
                      "WHERE u.role='player' AND u.status='active' AND s.last_seen>=? AND s.last_beat>=? AND s.created_at>=?",
                      (sec.iso(t - timedelta(minutes=cfg["SESSION_IDLE_MINUTES"])), sec.iso(t - timedelta(seconds=cfg["SESSION_TAB_GRACE_SECONDS"])),
                       sec.iso(t - timedelta(hours=cfg["SESSION_MAX_HOURS"])))).fetchall()
    return {r["user_id"] for r in rows}


def _process_day(db, day: int) -> None:
    b = prog.bal()
    # fix the candle that just ended (its base price may have moved through trades) before the new cycle opens
    db.execute("INSERT OR REPLACE INTO world_price_history(item_id,day,price) SELECT item_id, ?, price FROM world_market", (day - 1,))
    db.execute("DELETE FROM world_mods WHERE expires_day < ?", (day,))
    mk.advance_day(db, day, b["market_volatility"])
    db.execute("DELETE FROM world_price_history WHERE day < ?", (day - 1000,))
    online = online_ids(db)
    for r in db.execute("SELECT id FROM users WHERE role='player' AND status='active'").fetchall():
        uid = r["id"]
        db.execute("UPDATE campaigns SET cycle=? WHERE user_id=?", (day, uid))
        prog.incr(db, uid, "cycles")
        if day % b["wanted_decay_every_days"] == 0:
            db.execute("UPDATE player_state SET wanted=wanted-1 WHERE user_id=? AND wanted>0", (uid,))
        if uid in online:
            from . import contacts
            contacts.expire(db, uid, day)
            needs.tick(db, uid, day)
            ev.expire_pending(db, uid, day)


def tick() -> int:
    with tx() as db:
        d, last = day_now(db), int(get_state(db, "last_day", "0"))
        if d <= last:
            return d
        for day in range(max(last + 1, d - MAX_CATCHUP_DAYS + 1), d + 1):
            _process_day(db, day)
        set_state(db, "last_day", d)
    return d


def maybe_tick() -> None:
    db = get_db()
    if day_now(db) > int(get_state(db, "last_day", "0")):
        tick()


def _interval_ms(db, uid, rng, first=False) -> int:
    b = prog.bal()
    lo, hi = (4, 6) if first else (b["harm_event_min_minutes"], b["harm_event_max_minutes"])
    mins = rng.uniform(lo, hi) / max(0.1, b["event_frequency"])
    wanted = db.execute("SELECT wanted FROM player_state WHERE user_id=?", (uid,)).fetchone()["wanted"]
    return int(mins * max(0.5, 1 - wanted / 200) * 60000)


def on_login(db, uid) -> None:
    """Grace period: nothing punishes a player for time spent offline."""
    day, now = day_now(db), _ms()
    db.execute("UPDATE events SET expires_cycle=? WHERE user_id=? AND status='pending'", (day + ev.PENDING_DAYS, uid))
    db.execute("UPDATE contracts SET deadline_cycle=MAX(deadline_cycle, ?) WHERE user_id=? AND status='active'", (day + 2, uid))
    if prog.counter(db, uid, "next_harm_ms") < now:
        first = prog.counter(db, uid, "flag_first_shakedown") == 0
        prog.set_counter(db, uid, "next_harm_ms", now + _interval_ms(db, uid, random.Random(f"login:{uid}:{now}"), first))


def _run_events(db, now: int) -> None:
    b = prog.bal()
    day = day_now(db)
    g_next = int(get_state(db, "next_market_event_ms", "0"))
    rng = random.Random(f"world-ev:{g_next}:{day}")
    gap = lambda: int(rng.uniform(b["market_event_min_minutes"], b["market_event_max_minutes"]) * 60000 / max(0.1, b["event_frequency"]))  # noqa: E731
    if g_next == 0:
        set_state(db, "next_market_event_ms", now + gap())
    elif now >= g_next:
        pool = [d for d in ev.DEFS if d["id"] in ev.MARKET_ONLY]
        ev.fire_market(db, rng.choices(pool, weights=[d["weight"] for d in pool])[0], day)
        set_state(db, "next_market_event_ms", now + gap())
    for uid in online_ids(db):
        nxt = prog.counter(db, uid, "next_harm_ms")
        first = prog.counter(db, uid, "flag_first_shakedown") == 0
        prng = random.Random(f"ev:{uid}:{nxt}")
        if nxt == 0:
            prog.set_counter(db, uid, "next_harm_ms", now + _interval_ms(db, uid, prng, first))
            continue
        if now < nxt:
            continue
        pending = db.execute("SELECT COUNT(*) AS n FROM events WHERE user_id=? AND status='pending'", (uid,)).fetchone()["n"]
        if pending >= 2:
            prog.set_counter(db, uid, "next_harm_ms", now + 120000)
            continue
        if first:
            prog.incr(db, uid, "flag_first_shakedown")
        ev.fire_personal(db, uid, day, prng, first)
        prog.set_counter(db, uid, "next_harm_ms", now + _interval_ms(db, uid, prng))


def run_events() -> None:
    db, now = get_db(), _ms()
    due = now >= int(get_state(db, "next_market_event_ms", "0"))
    if not due:
        due = any(now >= prog.counter(db, uid, "next_harm_ms") for uid in online_ids(db))
    if due:
        with tx() as db2:
            _run_events(db2, now)


def start_scheduler(app) -> None:
    def loop():
        while True:
            time.sleep(5)
            try:
                with app.app_context():
                    maybe_tick()
                    run_events()
            except Exception:  # keep the clock alive no matter what
                app.logger.exception("world scheduler error")
    threading.Thread(target=loop, name="kingpin-world", daemon=True).start()
