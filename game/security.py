"""Hashing, tokens, rate limiting, time helpers. Never log secrets."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from flask import current_app, request
from werkzeug.security import check_password_hash, generate_password_hash

from .database import get_db

# Used to equalise timing when a username does not exist.
_DUMMY_HASH = generate_password_hash("kingpin-dummy-value")


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


def hash_secret(secret: str) -> str:
    return generate_password_hash(secret)  # scrypt, salted


def verify_secret(stored: str | None, supplied: str) -> bool:
    return check_password_hash(stored or _DUMMY_HASH, supplied) and stored is not None


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def client_ip() -> str:
    return request.remote_addr or "unknown"


def log_event(kind: str, user_id: str | None = None, detail: str = "") -> None:
    db = get_db()
    db.execute(
        "INSERT INTO security_events(at, kind, user_id, ip, detail) VALUES (?,?,?,?,?)",
        (iso(now()), kind, user_id, client_ip(), detail[:300]),
    )
    db.commit()
    current_app.logger.info("security_event kind=%s user=%s ip=%s", kind, user_id, client_ip())


# ---- login rate limiting (per username and per IP) ----
def _keys(username: str) -> list[str]:
    return [f"u:{username.lower()}", f"ip:{client_ip()}"]


def is_locked_out(username: str) -> bool:
    cfg = current_app.config
    db = get_db()
    since = iso(now() - timedelta(minutes=cfg["LOGIN_LOCKOUT_MINUTES"]))
    for k in _keys(username):
        n = db.execute(
            "SELECT COUNT(*) AS n FROM login_attempts WHERE key=? AND at>=?", (k, since)
        ).fetchone()["n"]
        if n >= cfg["LOGIN_MAX_FAILURES"]:
            return True
    return False


def record_failure(username: str) -> None:
    db = get_db()
    for k in _keys(username):
        db.execute("INSERT INTO login_attempts(key, at) VALUES (?,?)", (k, iso(now())))
    db.execute("DELETE FROM login_attempts WHERE at < ?", (iso(now() - timedelta(days=1)),))
    db.commit()


def clear_failures(username: str) -> None:
    db = get_db()
    db.execute("DELETE FROM login_attempts WHERE key=?", (f"u:{username.lower()}",))
    db.commit()
