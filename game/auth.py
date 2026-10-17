"""Server-side sessions, login/logout, CSRF, role decorators, admin bootstrap.
Players may be signed in on ONE device only (a new login ends the old session). Sessions end for the reasons in END_MESSAGES and the
reason is remembered briefly so the affected browser can be told why it was signed out."""
import re
import secrets
import sys
import uuid
from datetime import timedelta
from functools import wraps

from flask import Blueprint, current_app, g, jsonify, request

from . import security as sec
from .database import get_db

bp = Blueprint("auth", __name__, url_prefix="/api")
COOKIE = "kp_session"
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,24}$")
GENERIC_FAIL = "Invalid credentials."
APPEAL = "To appeal ban/suspension, please contact admin."
END_MESSAGES = {
    "kicked": "Kicked by administrator.",
    "other_device": "You were signed out because this account was opened on another device.",
    "expired": "You were signed out because of inactivity.",
    "closed": "You were signed out because the page was closed or the connection was lost.",
    "deleted": "Your account was removed by administration.",
    "pin_reset": "Your PIN was changed by administration. Please sign in again.",
    "secret_changed": "Your credentials were changed. Please sign in again.",
}


def status_message(status: str, reason: str = "", until: str | None = None) -> str:
    r = f" Reason: {reason.strip().rstrip('.')}." if reason and reason.strip() else ""
    if status == "banned":
        return f"Your account has been banned.{r} {APPEAL}"
    if status == "suspended":
        return f"Your account is suspended{' until ' + until[:16].replace('T', ' ') + ' UTC' if until else ''}.{r} {APPEAL}"
    return f"Your account is disabled.{r} Please contact admin."


def bootstrap_admin(app) -> None:
    """Create the first admin from env config. Password is never stored in source."""
    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
        return
    cfg = app.config
    pw = cfg["ADMIN_PASSWORD"]
    generated = False
    if not pw:
        pw, generated = secrets.token_urlsafe(14), True
    db.execute(
        "INSERT INTO users(id, username, role, secret_hash, must_change_secret, created_at) "
        "VALUES (?,?,?,?,1,?)",
        (str(uuid.uuid4()), cfg["ADMIN_USERNAME"], "admin", sec.hash_secret(pw), sec.iso(sec.now())),
    )
    db.commit()
    app.logger.warning("Bootstrap admin '%s' created; password change required at first login.", cfg["ADMIN_USERNAME"])
    if generated:
        print(f"\n*** Generated one-time admin password for '{cfg['ADMIN_USERNAME']}': {pw}\n", file=sys.stderr)


def end_sessions(db, user_id: str, reason: str, detail: str = "", exclude: str | None = None) -> int:
    """End a user's sessions and remember why (no commit; the caller owns the transaction)."""
    q, a = "SELECT token_hash FROM sessions WHERE user_id=?", [user_id]
    if exclude:
        q += " AND token_hash<>?"; a.append(exclude)
    rows = db.execute(q, a).fetchall()
    t = sec.iso(sec.now())
    for r in rows:
        db.execute("INSERT OR REPLACE INTO ended_sessions(token_hash,reason,detail,at) VALUES (?,?,?,?)", (r["token_hash"], reason, detail, t))
        db.execute("DELETE FROM sessions WHERE token_hash=?", (r["token_hash"],))
    db.execute("DELETE FROM ended_sessions WHERE at < ?", (sec.iso(sec.now() - timedelta(days=1)),))
    return len(rows)


def invalidate_user_sessions(user_id: str, reason: str = "kicked", detail: str = "") -> None:
    end_sessions(get_db(), user_id, reason, detail)
    get_db().commit()


def load_session():
    """Resolve cookie -> user. Enforces idle / absolute / tab-closed expiry and account status."""
    g.user, g.end = None, None
    token = request.cookies.get(COOKIE)
    if not token:
        return
    db = get_db()
    cfg = current_app.config
    th = sec.token_hash(token)
    row = db.execute(
        "SELECT s.*, u.username, u.role, u.status, u.status_reason, u.suspended_until, u.must_change_secret "
        "FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?", (th,)).fetchone()
    if not row:
        e = db.execute("SELECT reason, detail FROM ended_sessions WHERE token_hash=?", (th,)).fetchone()
        if e:
            g.end = {"code": e["reason"], "message": e["detail"] or END_MESSAGES.get(e["reason"], "You were signed out.")}
        return
    t = sec.now()
    status = row["status"]
    if status == "suspended" and row["suspended_until"] and sec.parse(row["suspended_until"]) <= t:
        db.execute("UPDATE users SET status='active', suspended_until=NULL, status_reason='' WHERE id=?", (row["user_id"],))
        status = "active"
    reason, detail = None, ""
    if status != "active":
        reason, detail = status, status_message(status, row["status_reason"], row["suspended_until"])
    elif (t - sec.parse(row["created_at"]) > timedelta(hours=cfg["SESSION_MAX_HOURS"])
          or t - sec.parse(row["last_seen"]) > timedelta(minutes=cfg["SESSION_IDLE_MINUTES"])):
        reason = "expired"
    elif row["role"] == "player" and t - sec.parse(row["last_beat"] or row["last_seen"]) > timedelta(seconds=cfg["SESSION_TAB_GRACE_SECONDS"]):
        reason = "closed"  # no heartbeat from the open tab any more
    if reason:
        db.execute("INSERT OR REPLACE INTO ended_sessions(token_hash,reason,detail,at) VALUES (?,?,?,?)", (th, reason, detail, sec.iso(t)))
        db.execute("DELETE FROM sessions WHERE token_hash=?", (th,))
        db.commit()
        g.end = {"code": reason, "message": detail or END_MESSAGES[reason]}
        return
    # every request is a heartbeat; automatic background refreshes (GET + X-Auto-Refresh) are not user activity
    db.execute("UPDATE sessions SET last_beat=? WHERE token_hash=?", (sec.iso(t), th))
    if not (request.method == "GET" and request.headers.get("X-Auto-Refresh") == "1"):
        db.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?", (sec.iso(t), th))
        db.execute("UPDATE users SET last_activity=? WHERE id=?", (sec.iso(t), row["user_id"]))
    db.commit()
    g.user = {"id": row["user_id"], "username": row["username"], "role": row["role"],
              "must_change": bool(row["must_change_secret"]), "csrf": row["csrf_token"], "token_hash": th}


@bp.before_app_request
def _before():
    if request.path.startswith("/api/"):
        load_session()
        # CSRF: every state-changing API call except login needs the session's token.
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.endpoint != "auth.login":
            if g.user is None:
                return  # decorators will return 401
            sent = request.headers.get("X-CSRF-Token", "")
            if not secrets.compare_digest(sent, g.user["csrf"]):
                return jsonify(error="Invalid CSRF token."), 403


def _unauth():
    e = g.get("end")
    if e:
        return jsonify(error=e["message"], code=e["code"]), 401
    return jsonify(error="Not signed in or session expired."), 401


def login_required(fn):
    @wraps(fn)
    def w(*a, **kw):
        if g.get("user") is None:
            return _unauth()
        if g.user["must_change"]:
            return jsonify(error="Credential change required.", code="must_change"), 403
        return fn(*a, **kw)
    return w


def admin_required(fn):
    @wraps(fn)
    @login_required
    def w(*a, **kw):
        if g.user["role"] != "admin":
            sec.log_event("authz_denied", g.user["id"], request.path)
            return jsonify(error="Forbidden."), 403
        return fn(*a, **kw)
    return w


def player_required(fn):
    @wraps(fn)
    @login_required
    def w(*a, **kw):
        if g.user["role"] != "player":
            return jsonify(error="Forbidden."), 403
        return fn(*a, **kw)
    return w


def _session_payload():
    u = g.user
    return {"username": u["username"], "role": u["role"], "must_change": u["must_change"], "csrf": u["csrf"],
            "idle_minutes": current_app.config["SESSION_IDLE_MINUTES"]}


@bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()[:64]
    secret = str(data.get("secret", ""))[:200]
    role = data.get("role")
    if role not in ("player", "admin") or not username or not secret:
        return jsonify(error=GENERIC_FAIL), 401
    if sec.is_locked_out(username):
        sec.log_event("login_locked", None, f"user={username[:32]}")
        return jsonify(error="Too many attempts. Try again later."), 429
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    ok = sec.verify_secret(row["secret_hash"] if row else None, secret)
    if ok and row["role"] != role:
        ok = False
    if ok and row["status"] == "suspended" and row["suspended_until"] and sec.parse(row["suspended_until"]) <= sec.now():
        db.execute("UPDATE users SET status='active', suspended_until=NULL, status_reason='' WHERE id=?", (row["id"],))
        db.commit()
        row = db.execute("SELECT * FROM users WHERE id=?", (row["id"],)).fetchone()
    if not ok:
        sec.record_failure(username)
        sec.log_event("login_failed", row["id"] if row else None, f"role={role}")
        return jsonify(error=GENERIC_FAIL), 401
    if row["status"] != "active":
        # Credentials were correct, so telling the owner WHY they are blocked does not reveal anything to outsiders.
        sec.log_event("login_blocked", row["id"], row["status"])
        return jsonify(error=status_message(row["status"], row["status_reason"], row["suspended_until"]), code=row["status"]), 403
    sec.clear_failures(username)
    token, csrf = sec.new_token(), sec.new_token()
    t = sec.iso(sec.now())
    if row["role"] == "player":
        end_sessions(db, row["id"], "other_device")  # one device at a time: the newest login wins
    db.execute("INSERT INTO sessions(token_hash,user_id,csrf_token,created_at,last_seen,last_beat,ip) VALUES (?,?,?,?,?,?,?)",
               (sec.token_hash(token), row["id"], csrf, t, t, t, sec.client_ip()))
    db.execute("UPDATE users SET last_login=?, last_activity=? WHERE id=?", (t, t, row["id"]))
    if row["role"] == "player":
        from . import world
        world.on_login(db, row["id"])
    db.commit()
    sec.log_event("login_ok", row["id"], f"role={role}")
    resp = jsonify(username=row["username"], role=row["role"], must_change=bool(row["must_change_secret"]), csrf=csrf,
                   idle_minutes=current_app.config["SESSION_IDLE_MINUTES"])
    resp.set_cookie(COOKIE, token, httponly=True, samesite="Lax", secure=current_app.config["COOKIE_SECURE"],
                    max_age=current_app.config["SESSION_MAX_HOURS"] * 3600, path="/")
    return resp


@bp.post("/logout")
def logout():
    if g.get("user"):
        get_db().execute("DELETE FROM sessions WHERE token_hash=?", (g.user["token_hash"],))
        get_db().commit()
    resp = jsonify(ok=True)
    resp.delete_cookie(COOKIE, path="/")
    return resp


@bp.post("/ping")
def ping():
    """Heartbeat while the user is actively working (keeps the idle timer fresh)."""
    if g.get("user") is None:
        return _unauth()
    return jsonify(ok=True)


@bp.get("/me")
def me():
    if g.get("user") is None:
        return _unauth()
    return jsonify(_session_payload())


@bp.post("/change-secret")
def change_secret():
    if g.get("user") is None:
        return _unauth()
    data = request.get_json(silent=True) or {}
    cur, new = str(data.get("current", "")), str(data.get("new", ""))
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id=?", (g.user["id"],)).fetchone()
    if not sec.verify_secret(row["secret_hash"], cur):
        return jsonify(error="Current credential is incorrect."), 400
    cfg = current_app.config
    if g.user["role"] == "admin":
        if len(new) < cfg["ADMIN_PASSWORD_MIN_LENGTH"]:
            return jsonify(error=f"Password must be at least {cfg['ADMIN_PASSWORD_MIN_LENGTH']} characters."), 400
    elif not (new.isdigit() and len(new) >= cfg["PIN_MIN_LENGTH"]):
        return jsonify(error=f"PIN must be at least {cfg['PIN_MIN_LENGTH']} digits."), 400
    if new == cur:
        return jsonify(error="New credential must differ from the current one."), 400
    db.execute("UPDATE users SET secret_hash=?, must_change_secret=0 WHERE id=?", (sec.hash_secret(new), g.user["id"]))
    end_sessions(db, g.user["id"], "secret_changed", exclude=g.user["token_hash"])
    db.commit()
    sec.log_event("secret_changed", g.user["id"])
    return jsonify(ok=True)
