"""Administrator API. Every route is server-side admin-gated and audited."""
import json
import uuid
from datetime import timedelta

from flask import Blueprint, current_app, g, jsonify, request

from . import security as sec
from . import campaign, shops, world
from . import market as mk
from .items import ITEMS
from .auth import USERNAME_RE, admin_required, end_sessions, status_message
from . import progression as prog
from .database import get_db, tx

bp = Blueprint("admin", __name__, url_prefix="/api/admin")


def audit(target: str | None, action: str, before=None, after=None, note: str = "") -> None:
    get_db().execute(
        "INSERT INTO admin_audit_log(at,admin_id,target_user_id,action,before_value,after_value,note) "
        "VALUES (?,?,?,?,?,?,?)",
        (sec.iso(sec.now()), g.user["id"], target, action,
         json.dumps(before) if before is not None else None,
         json.dumps(after) if after is not None else None, note[:300]),
    )


def create_player(username: str, pin: str) -> str:
    """Create a player + campaign + starting state in one transaction."""
    cfg = current_app.config
    b = cfg["BALANCE"]
    db = get_db()
    uid = str(uuid.uuid4())
    t = sec.iso(sec.now())
    db.execute("INSERT INTO users(id,username,role,secret_hash,created_at) VALUES (?,?,?,?,?)",
               (uid, username, "player", sec.hash_secret(pin), t))
    db.execute("INSERT INTO campaigns(id,user_id,name,created_at) VALUES (?,?,?,?)",
               (str(uuid.uuid4()), uid, "Campaign 1", t))
    db.execute(
        "INSERT INTO player_state(user_id,level,xp,cash,bank,reputation,wanted,strain,condition,capacity,location) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (uid, b["start_level"], b["start_xp"], b["start_cash"], b["start_bank"], b["start_reputation"],
         b["start_wanted"], b["start_strain"], b["start_condition"], b["start_capacity"], "starter_flat"),
    )
    from . import world
    db.execute("UPDATE campaigns SET cycle=? WHERE user_id=?", (world.day_now(db), uid))
    from .economy import init_player_economy
    init_player_economy(db, uid, b["start_cash"])
    return uid


@bp.get("/users")
@admin_required
def list_users():
    q = (request.args.get("q") or "").strip()[:64]
    rows = get_db().execute(
        "SELECT u.id,u.username,u.status,u.status_reason,u.suspended_until,u.last_login,u.created_at,"
        "p.level,p.reputation,p.cash,p.bank,p.location,p.wanted "
        "FROM users u LEFT JOIN player_state p ON p.user_id=u.id "
        "WHERE u.role='player' AND u.username LIKE ? ESCAPE '\\' ORDER BY u.username",
        ("%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",),
    ).fetchall()
    return jsonify(users=[dict(r) for r in rows])


@bp.post("/users")
@admin_required
def create_user():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    pin = str(data.get("pin", ""))
    cfg = current_app.config
    if not USERNAME_RE.match(username):
        return jsonify(error="Username must be 3-24 letters, digits or underscores."), 400
    if not (pin.isdigit() and len(pin) >= cfg["PIN_MIN_LENGTH"]):
        return jsonify(error=f"PIN must be at least {cfg['PIN_MIN_LENGTH']} digits."), 400
    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        return jsonify(error="Username already exists."), 409
    uid = create_player(username, pin)
    audit(uid, "create_player", after={"username": username})
    db.commit()
    return jsonify(id=uid, username=username), 201


def _target(uid: str):
    row = get_db().execute("SELECT * FROM users WHERE id=? AND role='player'", (uid,)).fetchone()
    return row


@bp.post("/users/<uid>/action")
@admin_required
def user_action(uid):
    data = request.get_json(silent=True) or {}
    action = data.get("action")
    reason = str(data.get("reason", "")).strip()[:300]   # shown to the player for ban / suspend / disable only
    note = str(data.get("note", ""))
    row = _target(uid)
    if not row:
        return jsonify(error="Player not found."), 404
    if action in ("ban", "disable", "suspend", "kick", "reset_pin", "delete", "reset") and data.get("confirm") is not True:
        return jsonify(error="Confirmation required for this action."), 400
    if action == "delete" and data.get("confirm_name") != row["username"]:
        return jsonify(error="Type the player's username to confirm the deletion."), 400
    hours = 0
    if action == "suspend":
        try:
            hours = int(data.get("hours", 24))
        except (TypeError, ValueError):
            return jsonify(error="Invalid duration."), 400
        if not 1 <= hours <= 24 * 365:
            return jsonify(error="Duration must be 1-8760 hours."), 400
    if action == "reset_pin":
        pin = str(data.get("pin", ""))
        if not (pin.isdigit() and len(pin) >= current_app.config["PIN_MIN_LENGTH"]):
            return jsonify(error=f"PIN must be at least {current_app.config['PIN_MIN_LENGTH']} digits."), 400
    if action not in ("ban", "disable", "suspend", "kick", "reset_pin", "delete", "reset", "unban", "enable"):
        return jsonify(error="Unknown action."), 400
    before = {"status": row["status"]}
    after = {}
    with tx() as db:
        if action == "ban":
            db.execute("UPDATE users SET status='banned', suspended_until=NULL, status_reason=? WHERE id=?", (reason, uid))
            end_sessions(db, uid, "banned", status_message("banned", reason))
        elif action == "disable":
            db.execute("UPDATE users SET status='disabled', status_reason=? WHERE id=?", (reason, uid))
            end_sessions(db, uid, "disabled", status_message("disabled", reason))
        elif action == "suspend":
            until = sec.iso(sec.now() + timedelta(hours=hours))
            db.execute("UPDATE users SET status='suspended', suspended_until=?, status_reason=? WHERE id=?", (until, reason, uid))
            end_sessions(db, uid, "suspended", status_message("suspended", reason, until))
        elif action in ("unban", "enable"):
            db.execute("UPDATE users SET status='active', suspended_until=NULL, status_reason='' WHERE id=?", (uid,))
        elif action == "kick":
            end_sessions(db, uid, "kicked")  # fixed message: "Kicked by administrator."
        elif action == "reset_pin":
            db.execute("UPDATE users SET secret_hash=? WHERE id=?", (sec.hash_secret(pin), uid))
            end_sessions(db, uid, "pin_reset")
        elif action == "reset":
            campaign.reset_player(db, uid, world.day_now(db))
            after = {"campaign": "reset"}
        elif action == "delete":
            end_sessions(db, uid, "deleted")
        if action == "delete":
            audit(uid, "delete_account", {"username": row["username"]}, {"deleted": True}, note)
            db.execute("DELETE FROM users WHERE id=?", (uid,))  # cascades to every per-player table
            return jsonify(ok=True, deleted=True)
        if action != "reset":
            after = dict(db.execute("SELECT status FROM users WHERE id=?", (uid,)).fetchone())
        audit(uid, "reset_campaign" if action == "reset" else action, before, after, reason or note)
    return jsonify(ok=True, status=after.get("status", row["status"]))


@bp.get("/audit")
@admin_required
def audit_log():
    args, where, params = request.args, [], []
    if args.get("target"):
        where.append("target_user_id=?"); params.append(args["target"])
    if args.get("action"):
        where.append("action=?"); params.append(args["action"])
    sql = "SELECT * FROM admin_audit_log" + (" WHERE " + " AND ".join(where) if where else "") \
          + " ORDER BY id DESC LIMIT 200"
    return jsonify(entries=[dict(r) for r in get_db().execute(sql, params).fetchall()])


@bp.get("/users/<uid>/state")
@admin_required
def inspect_state(uid):
    if not _target(uid):
        return jsonify(error="Player not found."), 404
    from .routes import player_state_for
    return jsonify(state=player_state_for(uid))


# ---- game-state editing (server-side, audited) ----
FIELDS = {"cash": ("cash", 0, 10**9), "bank": ("bank", 0, 10**9),
          "level": ("level", 1, prog.LEVEL_MAX), "reputation": ("reputation", -10**6, 10**6)}


@bp.post("/users/<uid>/adjust")
@admin_required
def adjust(uid):
    data = request.get_json(silent=True) or {}
    field, mode, amount = data.get("field"), data.get("mode"), data.get("amount")
    note = str(data.get("note", ""))
    if field not in FIELDS or mode not in ("add", "remove", "set"):
        return jsonify(error="Invalid field or mode."), 400
    if isinstance(amount, bool) or not isinstance(amount, int) or not 0 <= amount <= 10**9:
        return jsonify(error="Amount must be a whole number between 0 and 1,000,000,000."), 400
    if mode != "add" and data.get("confirm") is not True:
        return jsonify(error="Confirmation required for remove/set."), 400
    if not _target(uid):
        return jsonify(error="Player not found."), 404
    col, lo, hi = FIELDS[field]
    with tx() as db:
        ps = db.execute("SELECT p.*, c.cycle FROM player_state p JOIN campaigns c ON c.user_id=p.user_id WHERE p.user_id=?", (uid,)).fetchone()
        cur = ps[col]
        new = cur + amount if mode == "add" else cur - amount if mode == "remove" else amount
        if not lo <= new <= hi:
            return jsonify(error=f"Result would be {new}; allowed range for {field} is {lo} to {hi}."), 400
        if new == cur:
            return jsonify(error="No change."), 400
        if field == "cash":
            prog.add_cash(db, uid, new - cur, "admin", ps["cycle"])
        elif field == "bank":
            db.execute("UPDATE player_state SET bank=? WHERE user_id=?", (new, uid))
        elif field == "reputation":
            prog.apply_effects(db, uid, {"rep": new - cur}, ps["cycle"], "admin")
        else:  # level: XP is reset to the start of that level so level and XP stay consistent
            used = db.execute("SELECT COALESCE(SUM(quantity),0) AS n FROM inventory WHERE user_id=?", (uid,)).fetchone()["n"]
            b = current_app.config["BALANCE"]
            cap = max(b["start_capacity"] + b["capacity_per_level"] * (new - 1), used)
            db.execute("UPDATE player_state SET level=?, xp=?, capacity=? WHERE user_id=?",
                       (new, prog.xp_for_level(new), cap, uid))
        prog.record_event(db, uid, ps["cycle"], "admin_adjust", "Administrative adjustment", "info",
                          f"The game administrator adjusted your {field}.")
        audit(uid, f"adjust_{field}", {field: cur}, {field: new, "mode": mode, "amount": amount}, note)
    from .routes import player_state_for
    return jsonify(ok=True, field=field, before=cur, after=new, state=player_state_for(uid))


# ---- login-screen announcement (one message at a time; posting replaces the old one) ----
@bp.post("/announcement")
@admin_required
def post_announcement():
    msg = str((request.get_json(silent=True) or {}).get("message", "")).replace("\r\n", "\n").strip()
    if not 1 <= len(msg) <= 1000:
        return jsonify(error="The message must be between 1 and 1000 characters."), 400
    with tx() as db:
        old = db.execute("SELECT message FROM announcement WHERE id=1").fetchone()
        db.execute("INSERT INTO announcement(id,message,posted_at,posted_by) VALUES (1,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                   "message=excluded.message, posted_at=excluded.posted_at, posted_by=excluded.posted_by",
                   (msg, sec.iso(sec.now()), g.user["id"]))
        audit(None, "post_announcement", {"message": old["message"][:200]} if old else None, {"message": msg[:200]})
    return jsonify(ok=True)


@bp.post("/announcement/clear")
@admin_required
def clear_announcement():
    with tx() as db:
        old = db.execute("SELECT message FROM announcement WHERE id=1").fetchone()
        db.execute("DELETE FROM announcement WHERE id=1")
        audit(None, "clear_announcement", {"message": old["message"][:200]} if old else None, None)
    return jsonify(ok=True)


# ---- seasons ----
@bp.post("/season")
@admin_required
def new_season():
    data = request.get_json(silent=True) or {}
    name = " ".join(str(data.get("name", "")).split())
    if not 1 <= len(name) <= 40 or not name.isprintable():
        return jsonify(error="The season name must be 1-40 printable characters."), 400
    if data.get("confirm") is not True:
        return jsonify(error="Confirmation required: a new season resets the day counter and the market."), 400
    reset = data.get("reset_players") is True
    with tx() as db:
        old = world.season_info(db)
        res = world.new_season(db, name, reset)
        audit(None, "new_season", {"season": old["name"], "day": old["day"]}, {"season": name, "players_reset": res["players_reset"]})
    return jsonify(ok=True, **res)


# ---- public login-screen leaderboard: mask player names ----
@bp.post("/settings")
@admin_required
def admin_settings():
    v = (request.get_json(silent=True) or {}).get("mask_leaderboard")
    if not isinstance(v, bool):
        return jsonify(error="mask_leaderboard must be true or false."), 400
    with tx() as db:
        old = world.get_state(db, "mask_leaderboard", "1") == "1"
        world.set_state(db, "mask_leaderboard", "1" if v else "0")
        audit(None, "set_mask_leaderboard", {"mask": old}, {"mask": v})
    return jsonify(ok=True, mask_leaderboard=v)


# ---- market manipulation: pump, rug pull, crash ----
MANIP = {"surge": (1.05, 5.0, "good", "is surging", "Buyers are scrambling and the price has jumped."),
         "rug_pull": (0.05, 0.6, "severe", "collapses", "The price has fallen through the floor. Nobody can say why."),
         "crash": (0.1, 0.9, "severe", "Market crash", "Prices are plummeting across the board.")}


@bp.get("/market")
@admin_required
def market_state():
    db = get_db()
    mods = []
    for r in db.execute("SELECT * FROM world_mods ORDER BY id DESC"):
        target = ITEMS[r["item_id"]]["name"] if r["item_id"] in ITEMS else ("ALL ITEMS" if r["category"] == "*" else r["category"] or "?")
        mods.append({"id": r["id"], "target": target, "factor": r["factor"], "expires_day": r["expires_day"]})
    return jsonify(mods=mods, day=world.day_now(db), items=[{"id": i["id"], "name": i["name"]} for i in ITEMS.values()])


@bp.post("/market")
@admin_required
def market_action():
    data = request.get_json(silent=True) or {}
    action = data.get("action")
    if data.get("confirm") is not True:
        return jsonify(error="Confirmation required."), 400
    if action == "clear":
        with tx() as db:
            db.execute("DELETE FROM world_mods")
            mk.reprice(db, world.day_now(db))
            audit(None, "market_clear", None, None)
        return jsonify(ok=True)
    if action not in MANIP:
        return jsonify(error="Unknown market action."), 400
    lo, hi, sev, verb, desc = MANIP[action]
    try:
        factor, cycles = float(data.get("factor")), int(data.get("cycles"))
    except (TypeError, ValueError):
        return jsonify(error="Multiplier and cycles must be numbers."), 400
    if not lo <= factor <= hi:
        return jsonify(error=f"The multiplier must be between {lo} and {hi}."), 400
    if not 1 <= cycles <= 500:
        return jsonify(error="Cycles must be between 1 and 500."), 400
    item_id = data.get("item_id")
    if action != "crash" and item_id not in ITEMS:
        return jsonify(error="Choose an item."), 400
    with tx() as db:
        day = world.day_now(db)
        if action == "crash":
            db.execute("INSERT INTO world_mods(category,factor,expires_day,item_id) VALUES ('*',?,?,NULL)", (factor, day + cycles - 1))
            title = verb
        else:
            db.execute("INSERT INTO world_mods(category,factor,expires_day,item_id) VALUES ('',?,?,?)", (factor, day + cycles - 1, item_id))
            title = f"{ITEMS[item_id]['name']} {verb}"
        mk.reprice(db, day)
        for r in db.execute("SELECT id FROM users WHERE role='player' AND status='active'").fetchall():
            prog.record_event(db, r["id"], day, "market_shock", title, sev, desc, f"x{factor} for {cycles} cycles")
        audit(None, f"market_{action}", None, {"item": item_id, "factor": factor, "cycles": cycles})
    return jsonify(ok=True)


@bp.post("/market/<int:mid>/end")
@admin_required
def market_end(mid):
    with tx() as db:
        if not db.execute("SELECT 1 FROM world_mods WHERE id=?", (mid,)).fetchone():
            return jsonify(error="Not found."), 404
        db.execute("DELETE FROM world_mods WHERE id=?", (mid,))
        mk.reprice(db, world.day_now(db))
        audit(None, "market_end_mod", {"id": mid}, None)
    return jsonify(ok=True)


# ---- season specials (extra shop items for this season) ----
@bp.get("/specials")
@admin_required
def specials_list():
    return jsonify(specials=[{**s, "text": shops.text_of(s)} for s in shops.specials(get_db())])


@bp.post("/specials")
@admin_required
def specials_add():
    from .errors import GameError
    try:
        it = shops.parse_special(request.get_json(silent=True) or {})
    except GameError as e:
        return jsonify(error=e.message), e.status
    with tx() as db:
        db.execute("INSERT INTO special_items(name,description,price,min_level,max_per_player,perks,effects,created_at) VALUES (?,?,?,?,?,?,?,?)",
                   (it["name"], it["description"], it["price"], it["min_level"], it["max_per_player"], json.dumps(it["perks"]), json.dumps(it["effects"]), sec.iso(sec.now())))
        audit(None, "special_add", None, {"name": it["name"], "price": it["price"]})
    return jsonify(ok=True)


@bp.post("/specials/<int:sid>/delete")
@admin_required
def specials_delete(sid):
    with tx() as db:
        r = db.execute("SELECT name FROM special_items WHERE id=?", (sid,)).fetchone()
        if not r:
            return jsonify(error="Not found."), 404
        db.execute("DELETE FROM special_items WHERE id=?", (sid,))
        audit(None, "special_delete", {"name": r["name"]}, None)
    return jsonify(ok=True)
