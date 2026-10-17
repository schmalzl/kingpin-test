"""Kingpin Game File (.kgf) export/import.

Format:  KGF1.<base64url(JSON payload)>.<base64url(HMAC-SHA256 signature)>
 * Signed (not encrypted): the file is the player's own data, so confidentiality is not needed; integrity is.
   The signing key is derived from the server SECRET_KEY, so files cannot be forged or edited, and changing the
   SECRET_KEY invalidates all old saves.
 * The server stays authoritative: an import is accepted only if (a) the signature is valid, (b) the file belongs to
   the importing account and its current campaign, (c) the server issued that exact snapshot (save_exports table),
   (d) no administrator changed the account after the snapshot was made, and (e) every field passes validation.
 * Policy: importing is a ROLLBACK of the campaign to that snapshot (everything since is lost). Nothing is merged,
   so nothing can be duplicated. Permissions, status and credentials are never part of a save."""
import base64
import binascii
import hashlib
import hmac
import json
import math
import sqlite3
import uuid

from flask import current_app

from config import GAME_VERSION
from . import contacts as ct
from . import world
from . import missions as ms
from . import progression as prog
from . import security as sec
from .database import MIGRATIONS, get_db, tx
from .errors import GameError
from .items import ITEMS

MAGIC, FORMAT_VERSION, SCHEMA = "KGF1", 1, len(MIGRATIONS)
MAX_BYTES = 5 * 1024 * 1024
KEEP_EXPORTS = 50
HISTORY_CYCLES = 120
LOCATIONS = {"starter_flat"}

SINGLE = {
    "player_state": [("level", "i"), ("xp", "i"), ("cash", "i"), ("bank", "i"), ("reputation", "i"), ("wanted", "i"),
                     ("strain", "i"), ("condition", "i"), ("capacity", "i"), ("location", "s"), ("hydration", "i"), ("nutrition", "i")],
    "player_stats": [("revenue", "i"), ("expenditure", "i"), ("tx_count", "i"), ("largest_profit", "i"), ("largest_loss", "i")],
}
MULTI = {
    "counters": [("key", "s"), ("value", "i")],
    "mission_progress": [("mission_id", "s"), ("status", "s"), ("cycle", "i")],
    "contracts": [("contract_id", "s"), ("status", "s"), ("accepted_cycle", "i"), ("deadline_cycle", "i")],
    "contact_relations": [("contact_id", "s"), ("score", "i")],
    "events": [("cycle", "i"), ("event_id", "s"), ("severity", "s"), ("title", "s"), ("description", "s"), ("effects", "s"),
               ("status", "s"), ("choices", "s?"), ("default_choice", "i?"), ("resolved_choice", "i?"), ("expires_cycle", "i?")],
    "inventory": [("item_id", "s"), ("location", "s"), ("quantity", "i"), ("cost_total", "i"), ("acquired_cycle", "i")],
    "transactions": [("id", "i"), ("idem_key", "s"), ("kind", "s"), ("item_id", "s?"), ("quantity", "i?"), ("unit_price", "i?"),
                     ("total", "i"), ("profit", "i?"), ("cycle", "i"), ("at", "s"), ("result", "s")],
    "financial_ledger": [("id", "i"), ("at", "s"), ("cycle", "i"), ("kind", "s"), ("amount", "i"), ("cash_after", "i"), ("tx_id", "i?")],
    "action_log": [("idem_key", "s"), ("kind", "s"), ("cycle", "i"), ("at", "s"), ("result", "s")],
    "purchases": [("item_id", "s"), ("quantity", "i")],
}
INSERT_ORDER = ["player_state", "player_stats", "counters", "mission_progress", "contracts", "contact_relations", "events",
                "inventory", "transactions", "financial_ledger", "action_log", "purchases"]
DELETE_ORDER = ["financial_ledger", "transactions", "action_log", "purchases", "inventory",
                "events", "contact_relations", "contracts", "mission_progress", "counters", "player_stats", "player_state"]
LONG = {"description", "effects", "choices", "result"}
ROW_CAP = {"financial_ledger": 100_000, "transactions": 100_000, "events": 20_000, "price_history": 20_000}
ROW_CAP_DEFAULT = 5_000
EFFECT_KEYS = {"cash", "cash_pct", "xp", "rep", "wanted", "strain", "condition", "lose_inventory_pct", "market"}


def _key() -> bytes:
    return hmac.new(current_app.config["SECRET_KEY"].encode(), b"kingpin-kgf-signing-v1", hashlib.sha256).digest()


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(raw: bytes) -> bytes:
    return hmac.new(_key(), MAGIC.encode() + b"." + raw, hashlib.sha256).digest()


def encode(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return f"{MAGIC}.{_b64(raw)}.{_b64(_sign(raw))}"


def decode(data) -> dict:
    if not isinstance(data, str) or not data.strip():
        raise GameError("No file content received.")
    data = data.strip()
    if len(data) > MAX_BYTES:
        raise GameError("File is too large.", 413)
    parts = data.split(".")
    if len(parts) != 3 or parts[0] != MAGIC:
        raise GameError("This is not a valid Kingpin save file.")
    try:
        raw, sig = _unb64(parts[1]), _unb64(parts[2])
    except (binascii.Error, ValueError):
        raise GameError("The save file is corrupted.")
    if not hmac.compare_digest(sig, _sign(raw)):
        raise GameError("Signature check failed: the file was modified or was not created by this server.")
    try:
        payload = json.loads(raw)
    except (ValueError, RecursionError):
        raise GameError("The save file is corrupted.")
    if not isinstance(payload, dict):
        raise GameError("The save file is corrupted.")
    return payload


# ---------------- export ----------------
def export_snapshot(uid: str):
    with tx() as db:
        user = db.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()
        camp = db.execute("SELECT * FROM campaigns WHERE user_id=?", (uid,)).fetchone()
        tables = {}
        for name, cols in SINGLE.items():
            row = db.execute(f"SELECT {','.join(c for c, _ in cols)} FROM {name} WHERE user_id=?", (uid,)).fetchone()
            tables[name] = dict(row) if row else None
        for name, cols in MULTI.items():
            q = f"SELECT {','.join(c for c, _ in cols)} FROM {name} WHERE user_id=?"
            a = [uid]
            tables[name] = [dict(r) for r in db.execute(q + " ORDER BY rowid", a)]
        saved_at = sec.iso(sec.now())
        payload = {"format": FORMAT_VERSION, "schema": SCHEMA, "game_version": GAME_VERSION, "export_id": str(uuid.uuid4()),
                   "campaign_id": camp["id"], "season_id": int(world.get_state(db, "season_id", "1")), "user_id": uid, "username": user["username"], "saved_at": saved_at,
                   "campaign": {"name": camp["name"], "cycle": camp["cycle"]}, "tables": tables}
        data = encode(payload)
        if len(data) > MAX_BYTES:
            raise GameError("The campaign is too large to export.")
        ps = tables["player_state"]
        db.execute("INSERT INTO save_exports(export_id,user_id,campaign_id,created_at,cycle,level,cash) VALUES (?,?,?,?,?,?,?)",
                   (payload["export_id"], uid, camp["id"], saved_at, camp["cycle"], ps["level"], ps["cash"]))
        db.execute("DELETE FROM save_exports WHERE user_id=? AND export_id NOT IN "
                   "(SELECT export_id FROM save_exports WHERE user_id=? ORDER BY created_at DESC LIMIT ?)", (uid, uid, KEEP_EXPORTS))
    fname = f"kingpin-{user['username']}-cycle{camp['cycle']}-{saved_at[:10].replace('-', '')}.kgf"
    return data, fname, _meta(payload)


def _meta(p: dict) -> dict:
    ps = p["tables"]["player_state"]
    return {"export_id": p["export_id"], "username": p["username"], "saved_at": p["saved_at"], "game_version": p["game_version"],
            "format": p["format"], "schema": p["schema"], "campaign": p["campaign"]["name"], "cycle": p["campaign"]["cycle"],
            "level": ps["level"], "cash": ps["cash"], "bank": ps["bank"], "reputation": ps["reputation"],
            "inventory_units": sum(r["quantity"] for r in p["tables"]["inventory"]),
            "missions_done": sum(1 for r in p["tables"]["mission_progress"] if r["status"] == "completed")}


# ---------------- validation ----------------
def _bad(msg):
    raise GameError(f"Invalid save data: {msg}")


def _check_val(v, t: str, name: str):
    nullable = t.endswith("?")
    t = t[0]
    if v is None:
        if nullable:
            return
        _bad(f"{name} is missing")
    if t == "i":
        if isinstance(v, bool) or not isinstance(v, int) or abs(v) > 10**13:
            _bad(f"{name} must be a whole number")
    elif t == "f":
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            _bad(f"{name} must be a number")
    else:
        if not isinstance(v, str) or len(v) > (4000 if name.split(".")[-1] in LONG else 200):
            _bad(f"{name} must be text")


def _check_row(row, cols, label):
    if not isinstance(row, dict) or set(row) != {c for c, _ in cols}:
        _bad(f"{label} has unexpected or missing fields")
    for c, t in cols:
        _check_val(row[c], t, f"{label}.{c}")


def _check_choices(s):
    try:
        ch = json.loads(s)
    except ValueError:
        _bad("event choices are not valid")
    if not isinstance(ch, list) or not 1 <= len(ch) <= 6:
        _bad("event choices are not valid")
    for c in ch:
        if not isinstance(c, dict) or not isinstance(c.get("label"), str) or not isinstance(c.get("effects"), dict) \
                or not set(c["effects"]) <= EFFECT_KEYS:
            _bad("event choices are not valid")


def _check_json_dict(s, label):
    try:
        if not isinstance(json.loads(s), dict):
            raise ValueError
    except ValueError:
        _bad(f"{label} is not valid")


def validate_tables(p: dict) -> None:
    t = p.get("tables")
    camp = p.get("campaign")
    if not isinstance(t, dict) or not isinstance(camp, dict) or set(t) != set(SINGLE) | set(MULTI):
        _bad("structure is wrong")
    _check_row(camp, [("name", "s"), ("cycle", "i")], "campaign")
    if camp["cycle"] < 0:
        _bad("cycle is negative")
    for n, cols in SINGLE.items():
        _check_row(t[n], cols, n)
    for n, cols in MULTI.items():
        rows = t[n]
        if not isinstance(rows, list) or len(rows) > ROW_CAP.get(n, ROW_CAP_DEFAULT):
            _bad(f"{n} has too many entries")
        for r in rows:
            _check_row(r, cols, n)
    ps = t["player_state"]
    for f, lo, hi in (("level", 1, prog.LEVEL_MAX), ("xp", 0, 10**12), ("cash", 0, 10**12), ("bank", 0, 10**12),
                      ("wanted", 0, 100), ("hydration", 0, 100), ("nutrition", 0, 100), ("strain", 0, 100), ("condition", 0, 100), ("capacity", 0, 10**6)):
        if not lo <= ps[f] <= hi:
            _bad(f"{f} is out of range")
    if ps["location"] not in LOCATIONS:
        _bad("unknown location")
    if prog.level_for_xp(ps["xp"]) != ps["level"]:
        _bad("level does not match experience")
    inv = t["inventory"]
    seen = set()
    for r in inv:
        if r["item_id"] not in ITEMS or r["location"] not in LOCATIONS or not 1 <= r["quantity"] <= 10**6 or r["cost_total"] < 0:
            _bad("inventory contains impossible entries")
        if (r["item_id"], r["location"]) in seen:
            _bad("inventory has duplicate entries")
        seen.add((r["item_id"], r["location"]))
    if sum(r["quantity"] for r in inv) > ps["capacity"]:
        _bad("inventory exceeds storage capacity")
    for r in t["mission_progress"]:
        if r["mission_id"] not in ms.BY_ID or r["status"] not in ("completed", "failed"):
            _bad("mission progress contains unknown entries")
    for r in t["contracts"]:
        if r["contract_id"] not in ct.TEMPLATES or r["status"] not in ("active", "completed", "failed"):
            _bad("contracts contain unknown entries")
    for r in t["contact_relations"]:
        if r["contact_id"] not in ct.C_BY_ID:
            _bad("contacts contain unknown entries")
    for r in t["counters"]:
        if r["value"] < 0 or not r["key"]:
            _bad("counters contain impossible entries")
    for r in t["events"]:
        if r["severity"] not in ("info", "good", "warning", "severe") or r["status"] not in ("resolved", "pending"):
            _bad("events contain impossible entries")
        if r["choices"] is not None:
            _check_choices(r["choices"])
    tx_ids = set()
    for r in t["transactions"]:
        if r["kind"] not in ("buy", "sell", "advance") or r["id"] in tx_ids or r["id"] < 1:
            _bad("transactions contain impossible entries")
        tx_ids.add(r["id"])
        _check_json_dict(r["result"], "transaction result")
    for r in t["action_log"]:
        _check_json_dict(r["result"], "action log")
    for r in t["purchases"]:
        if not 1 <= r["quantity"] <= 1000:
            _bad("purchases contain impossible entries")
    total = 0
    for r in t["financial_ledger"]:
        if r["id"] < 1 or (r["tx_id"] is not None and r["tx_id"] not in tx_ids):
            _bad("ledger contains impossible entries")
        total += r["amount"]
    if total != ps["cash"]:
        _bad("cash does not match the financial ledger")


def check_ownership(db, uid: str, p: dict) -> None:
    if p.get("format") != FORMAT_VERSION:
        raise GameError(f"Unsupported save format version ({str(p.get('format'))[:10]}).")
    if p.get("schema") != SCHEMA:
        raise GameError(f"This save was made with an incompatible database schema ({str(p.get('schema'))[:10]}; this server uses {SCHEMA}).")
    if p.get("user_id") != uid:
        raise GameError("This save belongs to a different account and cannot be imported here.", 403)
    if p.get("season_id") != int(world.get_state(db, "season_id", "1")):
        raise GameError("This save was made in a previous season and cannot be imported.", 403)
    camp = db.execute("SELECT id FROM campaigns WHERE user_id=?", (uid,)).fetchone()
    if p.get("campaign_id") != camp["id"]:
        raise GameError("This save belongs to a different campaign.", 403)
    rec = db.execute("SELECT * FROM save_exports WHERE export_id=? AND user_id=?", (str(p.get("export_id"))[:64], uid)).fetchone()
    if not rec:
        raise GameError("This snapshot is not known to the server (it may be too old and was pruned).", 403)
    last_admin = db.execute("SELECT MAX(at) AS a FROM admin_audit_log WHERE target_user_id=? AND "
                            "(action LIKE 'adjust\\_%' ESCAPE '\\' OR action='reset_campaign')", (uid,)).fetchone()["a"]
    if last_admin and rec["created_at"] < last_admin:
        raise GameError("An administrator changed your account after this save was made, so it can no longer be restored.", 403)


def _current(db, uid):
    r = db.execute("SELECT p.level, p.cash, p.bank, c.cycle FROM player_state p JOIN campaigns c ON c.user_id=p.user_id WHERE p.user_id=?", (uid,)).fetchone()
    return dict(r)


def inspect(db, uid: str, data) -> dict:
    try:
        p = decode(data)
        check_ownership(db, uid, p)
        validate_tables(p)
    except GameError as e:
        return {"compatible": False, "error": e.message}
    cur, meta = _current(db, uid), _meta(p)
    warnings = []
    if meta["cycle"] < cur["cycle"]:
        warnings.append(f"This save is {cur['cycle'] - meta['cycle']} day(s) older than your current campaign. All progress since then will be lost.")
    elif meta["cycle"] == cur["cycle"]:
        warnings.append("This save matches your current cycle; importing restores the exact state at the time of export.")
    return {"compatible": True, "meta": meta, "current": cur, "warnings": warnings}


# ---------------- import ----------------
def import_snapshot(uid: str, data) -> dict:
    p = decode(data)
    with tx() as db:
        check_ownership(db, uid, p)
        validate_tables(p)
        t = p["tables"]
        try:
            day = world.day_now(db)
            delta = day - p["campaign"]["cycle"]
            db.execute("UPDATE campaigns SET name=?, cycle=? WHERE user_id=?", (p["campaign"]["name"], day, uid))
            for n in DELETE_ORDER:
                db.execute(f"DELETE FROM {n} WHERE user_id=?", (uid,))
            for n in INSERT_ORDER:
                cols = SINGLE.get(n) or MULTI[n]
                names = [c for c, _ in cols]
                sql = f"INSERT INTO {n}(user_id,{','.join(names)}) VALUES (?,{','.join('?' * len(names))})"
                rows = [t[n]] if n in SINGLE else t[n]
                for r in rows:
                    db.execute(sql, (uid, *[r[c] for c in names]))
            # day-based fields are shifted so deadlines/cooldowns keep their remaining time in the new timeline
            db.execute("UPDATE contracts SET accepted_cycle=accepted_cycle+?, deadline_cycle=deadline_cycle+? WHERE user_id=? AND status='active'", (delta, delta, uid))
            db.execute("UPDATE events SET expires_cycle=expires_cycle+? WHERE user_id=? AND status='pending'", (delta, uid))
            db.execute("UPDATE action_log SET cycle=cycle+? WHERE user_id=?", (delta, uid))
            prog.set_counter(db, uid, "next_harm_ms", 0)
        except sqlite3.IntegrityError:
            raise GameError("Invalid save data: it conflicts with game rules.")
        prog.set_counter(db, uid, "events_seen_upto",
                         db.execute("SELECT COALESCE(MAX(id),0) AS m FROM events WHERE user_id=?", (uid,)).fetchone()["m"])
        prog.record_event(db, uid, p["campaign"]["cycle"], "save_restored", "Save restored", "info",
                          f"Your campaign was restored from a save made at {p['saved_at'][:16].replace('T', ' ')}.")
    sec.log_event("save_import", uid, p["export_id"])
    return {"ok": True, "meta": _meta(p)}


def list_exports(db, uid: str) -> list[dict]:
    return [dict(r) for r in db.execute(
        "SELECT export_id, created_at, cycle, level, cash FROM save_exports WHERE user_id=? ORDER BY created_at DESC LIMIT 50", (uid,))]
