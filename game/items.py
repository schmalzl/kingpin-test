"""Item DEFINITIONS, loaded from content/items.json (edit that file to rename items, change descriptions, prices, unlock levels...).
Restart the server after editing. Current prices live in world_market, never here."""
import json
from pathlib import Path

CONTENT = Path(__file__).resolve().parent.parent / "content" / "items.json"


def _need(obj: dict, keys: dict, where: str) -> None:
    for k, t in keys.items():
        if k not in obj or not isinstance(obj[k], t) or isinstance(obj[k], bool):
            raise ValueError(f"content/items.json: {where} needs '{k}' of type {t.__name__ if isinstance(t, type) else 'number'}")


def _load() -> dict:
    data = json.loads(CONTENT.read_text(encoding="utf-8"))
    tiers, coms = data.get("tiers"), data.get("commodities")
    if not isinstance(tiers, list) or not isinstance(coms, list) or not tiers or not coms:
        raise ValueError("content/items.json needs non-empty 'tiers' and 'commodities' lists")
    num = (int, float)
    for t in tiers:
        _need(t, {"key": str, "label": str, "price_multiplier": num, "unlock_offset": int, "volatility_multiplier": num, "heat_bonus": int, "note": str}, f"tier {t.get('key')}")
    for c in coms:
        _need(c, {"code": str, "name": str, "category": str, "base_price": int, "unlock_level": int, "volatility": num, "heat": int,
                  "description": str, "made_from": list}, f"commodity {c.get('code')}")
    items = {}
    for c in coms:
        for t in tiers:
            b = round(c["base_price"] * t["price_multiplier"])
            iid = f"{c['code']}-{t['key']}"
            if iid in items:
                raise ValueError(f"content/items.json: duplicate item id {iid}")
            items[iid] = {
                "id": iid, "symbol": iid, "name": f"{c['name']} {t['label']}", "category": c["category"], "tier": t["label"], "tier_key": t["key"],
                "description": c["description"], "base_price": b, "min_price": max(1, round(b * 0.5)), "max_price": round(b * 2.0),
                "volatility": round(c["volatility"] * t["volatility_multiplier"], 3), "min_level": c["unlock_level"] + t["unlock_offset"],
                "min_reputation": 0, "storage": 1, "made_from": list(c["made_from"]), "tier_note": t["note"],
                "heat": c["heat"] + t["heat_bonus"],
            }
    return items


ITEMS = _load()
