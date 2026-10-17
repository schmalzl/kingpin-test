"""Central configuration. Balance values live in BALANCE so they are never scattered."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
GAME_VERSION = "0.6.0"

# ---- Display texts, shown in the bottom right corner of every screen. Edit freely. ----
VERSION_NOTE = "Kingpin v0.6.0 (alpha)"
COPYRIGHT_NOTE = "© 2026 Kingpin. All rights reserved."
SCHEMA_VERSION = 1


def load_dotenv(path: Path = BASE_DIR / ".env") -> None:
    """Minimal .env loader (no extra dependency). Real environment wins."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


# Starting values for a new campaign (spec section 8). Configurable, not hardcoded in logic.
BALANCE = {
    "start_level": 1,
    "start_xp": 0,
    "start_cash": 500,
    "start_bank": 0,
    "start_reputation": 0,
    "start_wanted": 0,
    "start_strain": 0,   # internally "strain"; players see Sanity = 100 - strain, so new players start at 100% sanity
    "start_condition": 100,
    "start_capacity": 20,
    "start_contacts": 1,
    "start_hideouts": 1,
    # runtime multipliers (admin UI arrives in Phase 6)
    "market_volatility": 1.0,
    "event_frequency": 1.0,
    "police_pressure": 1.0,
    "xp_multiplier": 1.0,
    "reward_multiplier": 1.0,
    "capacity_per_level": 10,
    "day_seconds": 120,                 # 2 real minutes = 1 game day
    "harm_event_min_minutes": 10,       # personal events (police, fines...) only while the player is online
    "harm_event_max_minutes": 15,
    "market_event_min_minutes": 6,      # global market events for everybody
    "market_event_max_minutes": 10,
    "wanted_decay_every_days": 3,
    "micro_step_seconds": 6,            # the live candle moves every N real seconds inside a cycle
    "contract_day_multiplier": 3,
    "rank_thresholds": [["Bronze", 0], ["Silver", 5000], ["Gold", 25000], ["Elite", 100000]],
    # ---- Hydration and nutrition (only drain while the player is online). Numbers are per cycle. ----
    "needs": {"hydration_loss": 3, "nutrition_loss": 2,
              "low_threshold": 30, "low_bonus": 0.5,        # sanity or health below the threshold: needs drain 50% faster (each)
              "critical": 25,                               # below this the body starts to suffer
              "starvation_health_loss": 2, "dehydration_health_loss": 3, "dehydration_sanity_loss": 2},
    "broke_cash_limit": 60,             # Odd Jobs only works below this cash and with an empty stash
    # ---- Actions (Actions tab). Every number is yours to tune. cooldown_days (in cycles) 0 = can be used as often as you like. ----
    # effects: sanity (+ heals), condition (health), wanted, cash, xp, rep
    "actions": {
        "rest": {"label": "Rest", "desc": "Catch your breath. Cheap and only a little effective, but you can do it as often as you like.",
                 "cost": 10, "min_level": 1, "cooldown_days": 0, "effects": {"sanity": 3, "condition": 2}, "confirm": False, "group": "Recovery"},
        "lay_low": {"label": "Lay Low", "desc": "Stay out of sight and let attention fade.",
                    "cost": 60, "min_level": 1, "cooldown_days": 2, "effects": {"wanted": -8, "sanity": 3}, "confirm": False, "group": "Staying Hidden"},
        "clinic": {"label": "Private Clinic Stay", "desc": "Expensive, discreet, and effective recovery.",
                   "cost": 150, "min_level": 2, "cooldown_days": 4, "effects": {"sanity": 40, "condition": 30}, "confirm": True, "group": "Recovery"},
        "odd_jobs": {"label": "Odd Jobs", "desc": "Safety net: day labour when you are broke with no stock. Never available otherwise.",
                     "cost": 0, "min_level": 1, "cooldown_days": 0, "effects": {"cash": 30, "sanity": -3}, "confirm": False, "group": "Income", "broke_only": True},
    },
}


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def build_config() -> dict:
    load_dotenv()
    env = os.environ.get("KINGPIN_ENV", "development")
    return {
        "ENV": env,
        "DEBUG": False,  # never enabled by the app itself
        "SECRET_KEY": os.environ.get("KINGPIN_SECRET_KEY", ""),
        "DB_PATH": os.environ.get("KINGPIN_DB_PATH", str(BASE_DIR / "instance" / "kingpin.db")),
        "ADMIN_USERNAME": os.environ.get("KINGPIN_ADMIN_USERNAME", "admin_001"),
        "ADMIN_PASSWORD": os.environ.get("KINGPIN_ADMIN_PASSWORD", ""),
        "PIN_MIN_LENGTH": _int("KINGPIN_PIN_MIN_LENGTH", 6),
        "ADMIN_PASSWORD_MIN_LENGTH": 12,
        "SESSION_IDLE_MINUTES": _int("KINGPIN_SESSION_IDLE_MINUTES", 15),   # auto sign-out after this long without input
        "SESSION_TAB_GRACE_SECONDS": _int("KINGPIN_SESSION_TAB_GRACE_SECONDS", 180),  # players are signed out this long after closing the tab
        "VERSION_NOTE": VERSION_NOTE,
        "COPYRIGHT_NOTE": COPYRIGHT_NOTE,
        "SESSION_MAX_HOURS": _int("KINGPIN_SESSION_MAX_HOURS", 12),
        "LOGIN_MAX_FAILURES": _int("KINGPIN_LOGIN_MAX_FAILURES", 5),
        "LOGIN_WINDOW_MINUTES": _int("KINGPIN_LOGIN_WINDOW_MINUTES", 15),
        "LOGIN_LOCKOUT_MINUTES": _int("KINGPIN_LOGIN_LOCKOUT_MINUTES", 15),
        "SCHEDULER": True,  # background world clock (market + events); tests turn it off
        "TRUST_PROXY": _int("KINGPIN_TRUST_PROXY", 0),  # number of reverse proxies / tunnels in front of the app
        "COOKIE_SECURE": env == "production",
        "MAX_CONTENT_LENGTH": 6 * 1024 * 1024,
        "BALANCE": BALANCE,
    }
