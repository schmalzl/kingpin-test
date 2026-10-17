import os
import tempfile
import unittest

from config import BALANCE
from game import create_app

ADMIN_PW = "test-admin-password-123"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({
            "DB_PATH": os.path.join(self.tmp.name, "t.db"), "SECRET_KEY": "x" * 32,
            "ADMIN_USERNAME": "admin_001", "ADMIN_PASSWORD": ADMIN_PW,
            "LOGIN_MAX_FAILURES": 3, "SCHEDULER": False,
            "BALANCE": dict(BALANCE, micro_step_seconds=10**6),  # freeze the live candle so quotes are stable in tests
        })

    def tearDown(self):
        self.tmp.cleanup()

    def client(self):
        return self.app.test_client()

    def login(self, c, user, secret, role):
        r = c.post("/api/login", json={"username": user, "secret": secret, "role": role})
        return r, (r.get_json() or {})

    def admin_client(self, change=True):
        c = self.client()
        r, d = self.login(c, "admin_001", ADMIN_PW, "admin")
        assert r.status_code == 200, r.get_json()
        c.csrf = d["csrf"]
        if change:
            r = c.post("/api/change-secret", json={"current": ADMIN_PW, "new": "a-new-strong-password"},
                       headers={"X-CSRF-Token": c.csrf})
            assert r.status_code == 200, r.get_json()
        return c

    def post(self, c, url, **json):
        return c.post(url, json=json, headers={"X-CSRF-Token": c.csrf})

    def make_player(self, adm, name="alice", pin="123456"):
        r = self.post(adm, "/api/admin/users", username=name, pin=pin)
        assert r.status_code == 201, r.get_json()
        return r.get_json()["id"]

    def player_client(self, name="alice", pin="123456"):
        c = self.client()
        r, d = self.login(c, name, pin, "player")
        assert r.status_code == 200, d
        c.csrf = d["csrf"]
        return c
