"""Public leaderboard: ranked by net worth (cash + bank + stock at sell quote), with Bronze/Silver/Gold/Elite tiers."""
from . import market as mk
from . import progression as prog


def tier_for(net: int) -> str:
    tier = "Bronze"
    for name, threshold in prog.bal()["rank_thresholds"]:
        if net >= threshold:
            tier = name
    return tier


def leaderboard(db, limit: int = 50) -> list[dict]:
    stock = {}
    live = mk.live_prices(db)
    for r in db.execute("SELECT user_id, item_id, quantity FROM inventory"):
        stock[r["user_id"]] = stock.get(r["user_id"], 0) + r["quantity"] * mk.sell_price(live.get(r["item_id"]) or 1)
    rows = db.execute("SELECT u.id, u.username, p.level, p.cash, p.bank, p.reputation FROM users u "
                      "JOIN player_state p ON p.user_id=u.id WHERE u.role='player' AND u.status='active'").fetchall()
    entries = []
    for r in rows:
        net = r["cash"] + r["bank"] + stock.get(r["id"], 0)
        entries.append({"name": r["username"], "level": r["level"], "cash": r["cash"], "reputation": r["reputation"],
                        "net_worth": net, "tier": tier_for(net)})
    entries.sort(key=lambda e: (-e["net_worth"], -e["reputation"], e["name"].lower()))
    for i, e in enumerate(entries[:limit], 1):
        e["rank"] = i
    return entries[:limit]
