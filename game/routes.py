"""Player-facing game endpoints. The user id always comes from the server session."""
from flask import Blueprint, current_app, g, jsonify, request

from config import BASE_DIR, GAME_VERSION
from pathlib import Path

from . import actions, board, contacts, economy, events, missions, saves, settings, shops, world
from . import market as mk
from . import needs
from . import progression as prog
from .auth import player_required
from .database import get_db, tx
from .errors import GameError
from .items import ITEMS

bp = Blueprint("game", __name__, url_prefix="/api")


@bp.errorhandler(GameError)
def _game_error(e):
    return jsonify(error=e.message, **e.extra), e.status


def player_state_for(user_id: str) -> dict:
    db = get_db()
    s = db.execute("SELECT * FROM player_state WHERE user_id=?", (user_id,)).fetchone()
    c = db.execute("SELECT * FROM campaigns WHERE user_id=?", (user_id,)).fetchone()
    if not s or not c:
        return {}
    d = dict(s)
    d.pop("user_id")
    inv = economy.inventory_view(db, user_id)
    d["storage_used"] = inv["used"]
    d["needs"] = needs.describe(dict(s))
    d["sanity"] = 100 - d["strain"]  # players see sanity; internally it is stored as strain
    d["inventory_value"] = inv["est_value"]
    d["net_worth"] = d["cash"] + d["bank"] + inv["est_value"]
    d["campaign"] = {"id": c["id"], "name": c["name"], "cycle": c["cycle"]}
    d["xp_floor"] = prog.xp_for_level(d["level"])
    d["xp_next"] = prog.xp_for_level(d["level"] + 1)
    mv = missions.view(db, user_id)
    d["active_mission"] = next((m for m in mv if m["kind"] == "main" and m["status"] == "available"), None)
    d["claimable_missions"] = sum(1 for m in mv if m["claimable"])
    b = prog.bal()
    d["day"], d["next_day_in_ms"], d["day_seconds"] = world.day_now(db), world.ms_to_next_day(db), b["day_seconds"]
    d["season"] = world.season_info(db)
    d["unread_events"] = events.unread_count(db, user_id)
    d["pending_events"] = db.execute("SELECT COUNT(*) AS n FROM events WHERE user_id=? AND status='pending'", (user_id,)).fetchone()["n"]
    return d


@bp.get("/state")
@player_required
def state():
    return jsonify(version=GAME_VERSION, state=player_state_for(g.user["id"]))


@bp.get("/market")
@player_required
def market():
    return jsonify(items=economy.market_view(get_db(), g.user["id"]))


@bp.get("/market/<item_id>/history")
@player_required
def history(item_id):
    if item_id not in ITEMS:
        return jsonify(error="Unknown item."), 404
    try:
        limit = int(request.args.get("limit", "60"))
    except ValueError:
        limit = 60
    limit = max(2, min(limit, 500))
    rows = get_db().execute("SELECT day, price FROM world_price_history WHERE item_id=? ORDER BY day DESC LIMIT ?", (item_id, limit)).fetchall()
    return jsonify(history=[dict(r) for r in reversed(rows)])


@bp.get("/market/<item_id>/candles")
@player_required
def candles(item_id):
    if item_id not in ITEMS:
        return jsonify(error="Unknown item."), 404
    try:
        limit = max(5, min(int(request.args.get("limit", "60")), 300))
    except ValueError:
        limit = 60
    return jsonify(candles=mk.candles(get_db(), item_id, limit))


@bp.post("/bank")
@player_required
def bank():
    b = _body()
    return jsonify(economy.bank_transfer(g.user["id"], b.get("action"), b.get("amount"), b.get("key")))


@bp.get("/shops")
@player_required
def shops_list():
    return jsonify(shops=shops.view(get_db(), g.user["id"]))


@bp.post("/shops/buy")
@player_required
def shops_buy():
    b = _body()
    return jsonify(shops.buy(g.user["id"], b.get("item_id"), b.get("key")))


@bp.get("/inventory")
@player_required
def inventory():
    return jsonify(economy.inventory_view(get_db(), g.user["id"]))


def _body():
    return request.get_json(silent=True) or {}


@bp.post("/trade/buy")
@player_required
def buy():
    b = _body()
    return jsonify(economy.buy(g.user["id"], b.get("item_id"), b.get("quantity"), b.get("key")))


@bp.post("/trade/sell")
@player_required
def sell():
    b = _body()
    return jsonify(economy.sell(g.user["id"], b.get("item_id"), b.get("quantity"), b.get("key")))


@bp.get("/transactions")
@player_required
def transactions():
    rows = get_db().execute("SELECT id,kind,item_id,quantity,unit_price,total,profit,cycle,at FROM transactions "
                            "WHERE user_id=? AND kind<>'advance' ORDER BY id DESC LIMIT 100", (g.user["id"],)).fetchall()
    return jsonify(transactions=[dict(r) for r in rows])


@bp.get("/ledger")
@player_required
def ledger():
    rows = get_db().execute("SELECT id,at,cycle,kind,amount,cash_after FROM financial_ledger WHERE user_id=? "
                            "ORDER BY id DESC LIMIT 200", (g.user["id"],)).fetchall()
    return jsonify(ledger=[dict(r) for r in rows])


# ---- Phase 3: progression, missions, contacts, events, actions ----
@bp.get("/missions")
@player_required
def missions_list():
    return jsonify(missions=missions.view(get_db(), g.user["id"]))


@bp.post("/missions/<mid>/claim")
@player_required
def missions_claim(mid):
    with tx() as db:
        return jsonify(missions.claim(db, g.user["id"], mid))


@bp.get("/contacts")
@player_required
def contacts_list():
    return jsonify(contacts.view(get_db(), g.user["id"]))


@bp.post("/contracts/<cid>/accept")
@player_required
def contract_accept(cid):
    with tx() as db:
        return jsonify(contacts.accept(db, g.user["id"], cid))


@bp.post("/contracts/<cid>/fulfill")
@player_required
def contract_fulfill(cid):
    with tx() as db:
        return jsonify(contacts.fulfill(db, g.user["id"], cid))


@bp.get("/events")
@player_required
def events_list():
    db, uid = get_db(), g.user["id"]
    return jsonify(events=events.view(db, uid, 40, request.args.get("news") == "1"), seen_upto=events.seen_upto(db, uid))


@bp.post("/events/clear")
@player_required
def events_clear():
    with tx() as db:
        return jsonify(ok=True, cleared=events.clear(db, g.user["id"]))


@bp.post("/events/ack")
@player_required
def events_ack():
    with tx() as db:
        return jsonify(ok=True, seen_upto=events.ack(db, g.user["id"], _body().get("upto")))


@bp.post("/events/<int:eid>/respond")
@player_required
def events_respond(eid):
    with tx() as db:
        return jsonify(events.respond(db, g.user["id"], eid, _body().get("choice")))


@bp.get("/actions")
@player_required
def actions_list():
    return jsonify(actions=actions.view(get_db(), g.user["id"]))


@bp.post("/actions/<aid>")
@player_required
def actions_do(aid):
    return jsonify(actions.perform(g.user["id"], aid, _body().get("key"), current_app.config["BALANCE"].get("market_volatility", 1.0)))


# ---- settings ----
@bp.get("/settings")
@player_required
def settings_get():
    db, uid = get_db(), g.user["id"]
    u = db.execute("SELECT username, created_at, last_login FROM users WHERE id=?", (uid,)).fetchone()
    n = db.execute("SELECT COUNT(*) AS n FROM sessions WHERE user_id=?", (uid,)).fetchone()["n"]
    return jsonify(settings=settings.get(db, uid), defaults=settings.DEFAULTS, pin_min_length=current_app.config["PIN_MIN_LENGTH"],
                   account={"username": u["username"], "created_at": u["created_at"], "last_login": u["last_login"], "sessions": n})


@bp.post("/settings")
@player_required
def settings_set():
    with tx() as db:
        return jsonify(settings=settings.update(db, g.user["id"], _body()))


@bp.post("/settings/sign-out-others")
@player_required
def sign_out_others():
    with tx() as db:
        cur = db.execute("DELETE FROM sessions WHERE user_id=? AND token_hash<>?", (g.user["id"], g.user["token_hash"]))
        return jsonify(ok=True, signed_out=cur.rowcount)


# ---- save / load (.kgf) ----
@bp.post("/saves/export")
@player_required
def saves_export():
    data, filename, meta = saves.export_snapshot(g.user["id"])
    return jsonify(data=data, filename=filename, meta=meta)


@bp.post("/saves/inspect")
@player_required
def saves_inspect():
    return jsonify(saves.inspect(get_db(), g.user["id"], _body().get("data")))


@bp.post("/saves/import")
@player_required
def saves_import():
    b = _body()
    if b.get("confirm") is not True:
        return jsonify(error="Confirmation required: importing replaces your current campaign."), 400
    return jsonify(saves.import_snapshot(g.user["id"], b.get("data")))


@bp.get("/saves/exports")
@player_required
def saves_exports():
    return jsonify(exports=saves.list_exports(get_db(), g.user["id"]))


# ---- public endpoints (no login needed) ----
@bp.get("/announcement")
def announcement():
    r = get_db().execute("SELECT message, posted_at FROM announcement WHERE id=1").fetchone()
    return jsonify(message=r["message"] if r else None, posted_at=r["posted_at"] if r else None)


@bp.get("/leaderboard")
def leaderboard():
    try:
        limit = max(1, min(int(request.args.get("limit", "50")), 100))
    except ValueError:
        limit = 50
    db = get_db()
    entries = board.leaderboard(db, limit)
    if g.get("user") is None and world.get_state(db, "mask_leaderboard", "1") == "1":
        for e in entries:  # visitors who are not signed in only see the first 2 characters
            e["name"] = e["name"][:2] + "*" * max(0, len(e["name"]) - 2)
    return jsonify(entries=entries, tiers=prog.bal()["rank_thresholds"])


# ---- statistics + tutorial ----
@bp.get("/stats")
@player_required
def stats():
    db, uid = get_db(), g.user["id"]
    st = dict(db.execute("SELECT * FROM player_stats WHERE user_id=?", (uid,)).fetchone())
    ps = player_state_for(uid)
    sells = db.execute("SELECT COUNT(*) AS n, COALESCE(SUM(profit),0) AS p, COALESCE(SUM(CASE WHEN profit>0 THEN 1 ELSE 0 END),0) AS w "
                       "FROM transactions WHERE user_id=? AND kind='sell'", (uid,)).fetchone()
    series = [dict(r) for r in db.execute("SELECT id, cycle, cash_after FROM financial_ledger WHERE user_id=? ORDER BY id DESC LIMIT 200", (uid,))][::-1]
    recent = [dict(r) for r in db.execute("SELECT kind,item_id,quantity,unit_price,total,profit,cycle FROM transactions "
                                          "WHERE user_id=? AND kind<>'advance' ORDER BY id DESC LIMIT 12", (uid,))]
    done = {r["mission_id"] for r in db.execute("SELECT mission_id FROM mission_progress WHERE user_id=? AND status='completed'", (uid,))}
    cnt = lambda k: prog.counter(db, uid, k)  # noqa: E731
    return jsonify(
        totals={"revenue": st["revenue"], "expenditure": st["expenditure"], "net_profit": st["revenue"] - st["expenditure"],
                "largest_profit": st["largest_profit"], "largest_loss": st["largest_loss"], "transactions": st["tx_count"],
                "avg_profit_per_sale": round(sells["p"] / sells["n"], 1) if sells["n"] else 0, "sales": sells["n"], "profitable_sales": sells["w"]},
        player={"net_worth": ps["net_worth"], "cash": ps["cash"], "bank": ps["bank"], "inventory_value": ps["inventory_value"], "level": ps["level"],
                "xp": ps["xp"], "reputation": ps["reputation"], "highest_reputation": max(cnt("max_rep"), ps["reputation"]),
                "wanted": ps["wanted"], "highest_wanted": max(cnt("max_wanted"), ps["wanted"]), "day": ps["day"]},
        progress={"missions_done": len(done), "missions_total": len(missions.MISSIONS), "contracts_done": cnt("contracts_done"),
                  "contracts_failed": cnt("contracts_failed"), "units_bought": cnt("units_bought"), "units_sold": cnt("units_sold"),
                  "hideouts_owned": 1, "businesses_owned": 0},
        series=series, recent=recent)


@bp.get("/tutorial")
@player_required
def tutorial():
    f = Path(BASE_DIR) / "ingame-tutorial.md"
    text = f.read_text(encoding="utf-8")[:100_000] if f.exists() else ""
    return jsonify(markdown=text)


@bp.get("/meta")
def meta():
    cfg = current_app.config
    return jsonify(version=cfg["VERSION_NOTE"], copyright=cfg["COPYRIGHT_NOTE"], season=world.season_info(get_db()),
                   mask_leaderboard=world.get_state(get_db(), "mask_leaderboard", "1") == "1")
