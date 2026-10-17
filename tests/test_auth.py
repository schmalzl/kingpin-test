from datetime import timedelta
from game import security as sec
from game.database import get_db
from .helpers import ADMIN_PW, Base


class AuthTests(Base):
    def test_admin_must_change_password_first(self):
        c = self.client()
        r, d = self.login(c, "admin_001", ADMIN_PW, "admin")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(d["must_change"])
        self.assertEqual(c.get("/api/admin/users").status_code, 403)
        r = c.post("/api/change-secret", json={"current": ADMIN_PW, "new": "short"}, headers={"X-CSRF-Token": d["csrf"]})
        self.assertEqual(r.status_code, 400)
        r = c.post("/api/change-secret", json={"current": ADMIN_PW, "new": "another-long-password"}, headers={"X-CSRF-Token": d["csrf"]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(c.get("/api/admin/users").status_code, 200)

    def test_player_login_logout(self):
        adm = self.admin_client(); self.make_player(adm)
        p = self.player_client()
        self.assertEqual(p.get("/api/state").status_code, 200)
        self.assertEqual(p.post("/api/logout", headers={"X-CSRF-Token": p.csrf}).status_code, 200)
        self.assertEqual(p.get("/api/state").status_code, 401)

    def test_failed_login_is_generic(self):
        adm = self.admin_client(); self.make_player(adm)
        c = self.client()
        r1, d1 = self.login(c, "alice", "000000", "player")
        r2, d2 = self.login(c, "nobody", "000000", "player")
        self.assertEqual((r1.status_code, d1), (r2.status_code, d2))

    def test_rate_limit_and_lockout(self):
        adm = self.admin_client(); self.make_player(adm)
        c = self.client()
        for _ in range(3):
            self.assertEqual(self.login(c, "alice", "bad", "player")[0].status_code, 401)
        r, _ = self.login(c, "alice", "123456", "player")  # correct PIN, still locked
        self.assertEqual(r.status_code, 429)

    def test_role_mismatch_rejected(self):
        adm = self.admin_client(); self.make_player(adm)
        c = self.client()
        self.assertEqual(self.login(c, "alice", "123456", "admin")[0].status_code, 401)
        self.assertEqual(self.login(c, "admin_001", "a-new-strong-password", "player")[0].status_code, 401)

    def test_session_idle_expiry(self):
        adm = self.admin_client(); self.make_player(adm)
        p = self.player_client()
        with self.app.app_context():
            db = get_db()
            db.execute("UPDATE sessions SET last_seen=?", (sec.iso(sec.now() - timedelta(minutes=31)),))
            db.commit()
        self.assertEqual(p.get("/api/state").status_code, 401)

    def test_csrf_required(self):
        adm = self.admin_client(); self.make_player(adm)
        p = self.player_client()
        self.assertEqual(p.post("/api/logout").status_code, 403)

    def test_banned_account_rejected(self):
        adm = self.admin_client(); uid = self.make_player(adm)
        self.post(adm, f"/api/admin/users/{uid}/action", action="ban", confirm=True)
        r, d = self.login(self.client(), "alice", "123456", "player")
        self.assertEqual(r.status_code, 403)
        self.assertIn("banned", d["error"])
        self.assertIn("To appeal", d["error"])

    def test_pin_not_stored_plaintext(self):
        adm = self.admin_client(); self.make_player(adm)
        with self.app.app_context():
            hs = [r["secret_hash"] for r in get_db().execute("SELECT secret_hash FROM users")]
        self.assertTrue(all("123456" not in h and ADMIN_PW not in h for h in hs))
