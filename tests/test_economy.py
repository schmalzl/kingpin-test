import threading
import uuid

from game import market as mk
from game.database import get_db
from game.items import ITEMS
from .helpers import Base


def key():
    return uuid.uuid4().hex


class EconomyBase(Base):
    def setUp(self):
        super().setUp()
        self.adm = self.admin_client()
        self.uid = self.make_player(self.adm)
        self.p = self.player_client()

    def state(self):
        return self.p.get("/api/state").get_json()["state"]

    def buy(self, item="GRN-L", qty=1, k=None):
        return self.post(self.p, "/api/trade/buy", item_id=item, quantity=qty, key=k or key())

    def sell(self, item="GRN-L", qty=1, k=None):
        return self.post(self.p, "/api/trade/sell", item_id=item, quantity=qty, key=k or key())

    def price(self, item="GRN-L"):
        return next(i for i in self.p.get("/api/market").get_json()["items"] if i["id"] == item)

    def ledger_sum(self):
        with self.app.app_context():
            return get_db().execute("SELECT SUM(amount) AS s FROM financial_ledger WHERE user_id=?", (self.uid,)).fetchone()["s"]


class TradeTests(EconomyBase):
    def test_valid_purchase(self):
        price = self.price()["price"]
        r = self.buy(qty=3)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.state()["cash"], 500 - 3 * price)
        inv = self.p.get("/api/inventory").get_json()
        self.assertEqual(inv["items"][0]["quantity"], 3)
        self.assertEqual(inv["used"], 3)

    def test_insufficient_funds_no_side_effects(self):
        r = self.buy("GRN-L", 20)  # cheap item but 20 units; then expensive one
        self.assertEqual(r.status_code, 200)
        before = self.state()
        r = self.buy("GRN-L", 1000)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.state()["cash"], before["cash"])

    def test_invalid_quantities(self):
        for q in (0, -5, 1.5, "3", None, True, 10**6):
            self.assertEqual(self.buy(qty=q).status_code, 400, q)
        self.assertEqual(self.state()["cash"], 500)

    def test_storage_limit(self):
        with self.app.app_context():
            db = get_db(); db.execute("UPDATE player_state SET cash=100000"); db.commit()
        self.assertEqual(self.buy("GRN-L", 20).status_code, 200)
        r = self.buy("GRN-L", 1)
        self.assertEqual(r.status_code, 400)
        self.assertIn("storage", r.get_json()["error"].lower())

    def test_locked_item_rejected_by_server(self):
        r = self.buy("NVA-E", 1)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.buy("NOPE", 1).status_code, 404)

    def test_partial_sale_and_cost_basis(self):
        self.buy(qty=4)
        before = self.state()["cash"]
        r = self.sell(qty=1)
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertEqual(self.state()["cash"], before + d["total"])
        inv = self.p.get("/api/inventory").get_json()["items"][0]
        self.assertEqual(inv["quantity"], 3)
        self.sell(qty=3)
        self.assertEqual(self.p.get("/api/inventory").get_json()["items"], [])

    def test_oversell_rejected(self):
        self.buy(qty=2)
        self.assertEqual(self.sell(qty=3).status_code, 400)
        self.assertEqual(self.p.get("/api/inventory").get_json()["items"][0]["quantity"], 2)

    def test_idempotent_replay(self):
        k = key()
        a = self.buy(qty=2, k=k); b = self.buy(qty=2, k=k)
        self.assertEqual(a.status_code, 200)
        self.assertTrue(b.get_json()["replayed"])
        self.assertEqual(self.p.get("/api/inventory").get_json()["items"][0]["quantity"], 2)

    def test_round_trip_never_profits(self):
        self.buy(qty=5); self.sell(qty=5)
        self.assertLess(self.state()["cash"], 500)

    def test_ledger_consistency(self):
        self.buy(qty=5); self.sell(qty=2); self.buy("SPK-L", 3); self.buy(qty=999)
        self.assertEqual(self.ledger_sum(), self.state()["cash"])
        rows = self.p.get("/api/ledger").get_json()["ledger"]
        self.assertEqual(rows[0]["cash_after"], self.state()["cash"])

    def test_cross_account_isolation(self):
        self.make_player(self.adm, "bob", "654321")
        bob = self.player_client("bob", "654321")
        self.buy(qty=3)
        self.assertEqual(bob.get("/api/inventory").get_json()["items"], [])
        self.assertEqual(bob.get("/api/state").get_json()["state"]["cash"], 500)

    def test_concurrent_buys_never_overspend(self):
        results = []
        def worker():
            c = self.app.test_client()
            r = c.post("/api/login", json={"username": "alice", "secret": "123456", "role": "player"})
            h = {"X-CSRF-Token": r.get_json()["csrf"]}
            results.append(c.post("/api/trade/buy", json={"item_id": "GRN-L", "quantity": 8, "key": key()}, headers=h).status_code)
        ts = [threading.Thread(target=worker) for _ in range(6)]
        [t.start() for t in ts]; [t.join() for t in ts]
        self.p = self.player_client()  # the workers' logins ended our session (one device at a time)
        s = self.state()
        self.assertGreaterEqual(s["cash"], 0)
        self.assertEqual(self.ledger_sum(), s["cash"])
        self.assertEqual(self.p.get("/api/inventory").get_json()["used"], results.count(200) * 8)


class MarketTests(EconomyBase):
    def test_item_content_minimums(self):
        self.assertGreaterEqual(len(ITEMS), 20)
        self.assertEqual({i["tier"] for i in ITEMS.values()}, {"Low", "High", "Premium", "Elite"})

    def test_prices_within_bounds_over_many_days(self):
        with self.app.app_context():
            db = get_db()
            for day in range(1, 300):
                mk.advance_day(db, day, 1.0)
            db.commit()
        for it in self.p.get("/api/market").get_json()["items"]:
            d = ITEMS[it["id"]]
            self.assertTrue(d["min_price"] * 0.85 <= it["price"] <= d["max_price"] * 1.15, it["id"])

    def test_every_player_sees_the_same_prices(self):
        self.make_player(self.adm, "bobby", "654321")
        bob = self.player_client("bobby", "654321")
        a = [(i["id"], i["price"]) for i in self.p.get("/api/market").get_json()["items"]]
        b = [(i["id"], i["price"]) for i in bob.get("/api/market").get_json()["items"]]
        self.assertEqual(a, b)

    def test_refresh_does_not_reroll_market(self):
        self.assertEqual(self.p.get("/api/market").get_json(), self.p.get("/api/market").get_json())

    def test_history_available_immediately(self):
        h = self.p.get("/api/market/GRN-L/history?limit=500").get_json()["history"]
        self.assertGreater(len(h), 30)

    def test_admin_cannot_use_player_endpoints(self):
        self.assertEqual(self.adm.get("/api/market").status_code, 403)
