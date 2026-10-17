"""Global real-time market (same prices for every player).
Each CYCLE (2 real minutes) the supply/demand indices drift: small noise plus occasional large jumps -> the cycle's base price.
Inside a cycle the live price wiggles slowly around the base (a seeded random walk, re-evaluated every few seconds); at the end of the
cycle the candle is final and a new one opens. Everything is a pure function of (season, item, cycle, time), so all players see the same candle.
price = base_price x (demand/supply) x regional x event; admin events (surge, rug pull, crash) are event factors and may push beyond normal bounds."""
import random

from . import contacts as ct
from . import progression as prog
from . import security as sec
from .items import ITEMS

SELL_SPREAD = 0.10        # dealer margin: you sell for 90% of the quote
TRADE_IMPACT = 0.005      # supply shift per unit traded
MEAN_REVERSION = 0.08
BASE_NOISE = 0.03         # small moves per cycle
JUMP_PROB = 0.03          # chance per item per cycle of a LARGE move
ELASTICITY = 1.0
IDX_MIN, IDX_MAX = 0.5, 1.6
BACKFILL_DAYS = 60        # seeded pre-history so charts are useful right away


def price_for(item: dict, supply: float, demand: float, regional: float = 1.0, event: float = 1.0) -> int:
    raw = item["base_price"] * (demand / supply) ** ELASTICITY * regional * event
    lo, hi = item["min_price"] * min(1.0, event), item["max_price"] * max(1.0, event)
    return int(max(1, min(hi, max(lo, round(raw)))))


def sell_price(price: int) -> int:
    return max(1, int(price * (1 - SELL_SPREAD)))


def clamp_idx(x: float) -> float:
    return min(IDX_MAX, max(IDX_MIN, x))


def event_factor(db, item: dict, day: int) -> float:
    """Product of all active modifiers: market-wide ('*'), per category, or per item."""
    f = 1.0
    for r in db.execute("SELECT factor FROM world_mods WHERE expires_day>=? AND (item_id=? OR category=? OR category='*')",
                        (day, item["id"], item["category"])):
        f *= r["factor"]
    return f


def _season(db) -> str:
    r = db.execute("SELECT value FROM world_state WHERE key='season_id'").fetchone()
    return r["value"] if r else "1"


def advance_day(db, day: int, volatility_mult: float = 1.0) -> None:
    sid = _season(db)
    for r in db.execute("SELECT * FROM world_market").fetchall():
        item = ITEMS.get(r["item_id"])
        if item is None:
            continue  # item removed from items.json
        rng = random.Random(f"world:{sid}:{r['item_id']}:{day}")
        sigma = BASE_NOISE * item["volatility"] * volatility_mult
        s = clamp_idx(r["supply"] + (1 - r["supply"]) * MEAN_REVERSION + rng.gauss(0, sigma))
        d = clamp_idx(r["demand"] + (1 - r["demand"]) * MEAN_REVERSION + rng.gauss(0, sigma))
        if rng.random() < JUMP_PROB * volatility_mult:           # large move
            jump = rng.uniform(0.15, 0.40) * rng.choice((-1, 1))
            if rng.random() < 0.5:
                d = clamp_idx(d * (1 + jump))
            else:
                s = clamp_idx(s * (1 - jump))
        p = price_for(item, s, d, 1.0, event_factor(db, item, day))
        db.execute("UPDATE world_market SET price=?, prev_price=?, supply=?, demand=? WHERE item_id=?", (p, r["price"], s, d, r["item_id"]))
        db.execute("INSERT OR REPLACE INTO world_price_history(item_id,day,price) VALUES (?,?,?)", (r["item_id"], day, p))


def reprice(db, day: int) -> None:
    """Re-evaluate every price right now (used after admin market events so they take effect immediately)."""
    for r in db.execute("SELECT * FROM world_market").fetchall():
        it = ITEMS.get(r["item_id"])
        if it is None:
            continue
        p = price_for(it, r["supply"], r["demand"], 1.0, event_factor(db, it, day))
        db.execute("UPDATE world_market SET price=? WHERE item_id=?", (p, r["item_id"]))
        db.execute("INSERT OR REPLACE INTO world_price_history(item_id,day,price) VALUES (?,?,?)", (r["item_id"], day, p))


def ensure_market(db, day: int = 1) -> None:
    """Create the market on first start / new season, then simulate seeded pre-history ending at `day`."""
    sid = _season(db)
    have = {r["item_id"] for r in db.execute("SELECT item_id FROM world_market")}
    if have >= set(ITEMS):
        return
    fresh = not have
    for iid, item in ITEMS.items():
        if iid in have:
            continue
        rng = random.Random(f"world-init:{sid}:{iid}")
        s, d = 1 + rng.uniform(-0.08, 0.08), 1 + rng.uniform(-0.08, 0.08)
        p = price_for(item, s, d)
        db.execute("INSERT INTO world_market(item_id,price,prev_price,supply,demand) VALUES (?,?,?,?,?)", (iid, p, p, s, d))
    if fresh:  # new world or season: seeded pre-history. Items added later just start at the current cycle.
        for d in range(day - BACKFILL_DAYS, day):
            advance_day(db, d)
    for r in db.execute("SELECT item_id, price FROM world_market").fetchall():
        if fresh or r["item_id"] not in have:
            db.execute("INSERT OR REPLACE INTO world_price_history(item_id,day,price) VALUES (?,?,?)", (r["item_id"], day, r["price"]))


def apply_trade_impact(db, item_id: str, qty: int, bought: bool, day: int) -> None:
    """Buying drains supply, selling floods it; the base price moves immediately (for everyone)."""
    r = db.execute("SELECT * FROM world_market WHERE item_id=?", (item_id,)).fetchone()
    delta = TRADE_IMPACT * qty
    s = clamp_idx(r["supply"] + (-delta if bought else delta))
    it = ITEMS[item_id]
    p = price_for(it, s, r["demand"], 1.0, event_factor(db, it, day))
    db.execute("UPDATE world_market SET supply=?, price=? WHERE item_id=?", (s, p, item_id))


# ---------------- live candles ----------------
def _clock(db):
    """(current cycle, micro-steps elapsed in it, micro-steps per cycle)."""
    ds = prog.bal()["day_seconds"]
    step = max(1, prog.bal().get("micro_step_seconds", 6))
    r = db.execute("SELECT value FROM world_state WHERE key='epoch'").fetchone()
    el = (sec.now() - sec.parse(r["value"])).total_seconds()
    total = max(4, int(ds // step))
    return int(el // ds), min(total, int((el % ds) // step)), total


def _path(sid: str, item: dict, day: int, steps: int, base: int) -> list[float]:
    """Slow seeded random walk around 1.0: index 0 = open, index `steps` = value after that many micro-steps.
    Cheap items get a wider relative range, otherwise whole-dollar rounding would make their candles flat."""
    rng = random.Random(f"wig:{sid}:{item['id']}:{day}")
    sigma, limit, m, out = max(0.010 * item["volatility"], 0.5 / max(base, 1)), max(0.07, 2.2 / max(base, 1)), 0.0, [1.0]
    for _ in range(steps):
        m = max(-limit, min(limit, m * 0.9 + rng.gauss(0, sigma)))
        out.append(1.0 + m)
    return out


def live_prices(db) -> dict:
    day, k, _n = _clock(db)
    sid = _season(db)
    out = {}
    for r in db.execute("SELECT item_id, price FROM world_market"):
        it = ITEMS.get(r["item_id"])
        if it is not None:
            out[r["item_id"]] = max(1, round(r["price"] * _path(sid, it, day, k, r["price"])[-1]))
    return out


def live_price(db, item_id: str) -> int:
    day, k, _n = _clock(db)
    r = db.execute("SELECT price FROM world_market WHERE item_id=?", (item_id,)).fetchone()
    return max(1, round(r["price"] * _path(_season(db), ITEMS[item_id], day, k, r["price"])[-1]))


def candles(db, item_id: str, limit: int = 60) -> list[dict]:
    """One candle per cycle: finished cycles are fixed, the current one is live."""
    day, k, n = _clock(db)
    sid, it = _season(db), ITEMS[item_id]

    def make(d, base, steps, live):
        vals = [max(1, round(base * m)) for m in _path(sid, it, d, steps, base)]
        return {"day": d, "open": vals[0], "high": max(vals), "low": min(vals), "close": vals[-1], "live": live}

    rows = db.execute("SELECT day, price FROM world_price_history WHERE item_id=? AND day<? ORDER BY day DESC LIMIT ?",
                      (item_id, day, max(1, limit - 1))).fetchall()
    out = [make(r["day"], r["price"], n, False) for r in reversed(rows)]
    cur = db.execute("SELECT price FROM world_market WHERE item_id=?", (item_id,)).fetchone()["price"]
    out.append(make(day, cur, k, True))
    return out


def popularity(demand: float) -> str:
    return ("Very high (hot right now)" if demand >= 1.3 else "High" if demand >= 1.1 else "Steady" if demand >= 0.9
            else "Low" if demand >= 0.75 else "Very low")


def item_info(item: dict, row) -> dict:
    return {"made_from": item["made_from"], "tier_note": item["tier_note"], "popularity": popularity(row["demand"]),
            "heat": ("None", "Low", "Medium", "High")[min(item["heat"], 3)], "base_price": item["base_price"],
            "min_price": item["min_price"], "max_price": item["max_price"],
            "buyers": [c["name"] for c in ct.CONTACTS if c["prefers"] == item["category"]]}
