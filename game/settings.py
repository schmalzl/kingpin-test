"""Per-user interface preferences, stored server-side so they follow the player across devices."""
import json

from .errors import GameError

DEFAULTS = {"density": "compact", "font_size": "normal", "palette": "default", "confirm_expensive": True,
            "compact_market": False, "chart_type": "candles"}
ALLOWED = {"density": ("compact", "comfortable"), "font_size": ("small", "normal", "large"), "palette": ("default", "colorblind"), "chart_type": ("candles", "line")}
BOOLS = {"confirm_expensive", "compact_market"}


def get(db, uid) -> dict:
    row = db.execute("SELECT data FROM user_settings WHERE user_id=?", (uid,)).fetchone()
    try:
        stored = json.loads(row["data"]) if row else {}
    except ValueError:
        stored = {}
    out = dict(DEFAULTS)
    for k, v in stored.items():
        if (k in ALLOWED and v in ALLOWED[k]) or (k in BOOLS and isinstance(v, bool)):
            out[k] = v
    return out


def update(db, uid, changes: dict) -> dict:
    if not isinstance(changes, dict) or not changes:
        raise GameError("No settings supplied.")
    cur = get(db, uid)
    for k, v in changes.items():
        if k not in DEFAULTS:
            raise GameError(f"Unknown setting '{str(k)[:30]}'.")
        if k in ALLOWED and v not in ALLOWED[k]:
            raise GameError(f"Invalid value for {k}.")
        if k in BOOLS and not isinstance(v, bool):
            raise GameError(f"{k} must be true or false.")
        cur[k] = v
    db.execute("INSERT INTO user_settings(user_id,data) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET data=excluded.data",
               (uid, json.dumps(cur)))
    return cur
