from game.database import get_db
from .helpers import Base


class AdminTests(Base):
    def test_player_cannot_reach_admin_endpoints(self):
        adm = self.admin_client(); self.make_player(adm)
        p = self.player_client()
        self.assertEqual(p.get("/api/admin/users").status_code, 403)
        self.assertEqual(p.get("/api/admin/audit").status_code, 403)
        self.assertEqual(self.post(p, "/api/admin/users", username="eve", pin="123456").status_code, 403)
        self.assertEqual(self.client().get("/api/admin/users").status_code, 401)

    def test_create_player_state_and_audit(self):
        adm = self.admin_client(); uid = self.make_player(adm)
        s = self.player_client().get("/api/state").get_json()["state"]
        self.assertEqual((s["cash"], s["bank"], s["capacity"], s["level"]), (500, 0, 20, 1))
        entries = adm.get("/api/admin/audit").get_json()["entries"]
        self.assertEqual(entries[0]["action"], "create_player")
        self.assertEqual(entries[0]["target_user_id"], uid)

    def test_duplicate_and_invalid_input(self):
        adm = self.admin_client(); self.make_player(adm)
        self.assertEqual(self.post(adm, "/api/admin/users", username="ALICE", pin="123456").status_code, 409)
        self.assertEqual(self.post(adm, "/api/admin/users", username="bob", pin="12").status_code, 400)
        self.assertEqual(self.post(adm, "/api/admin/users", username="b o b", pin="123456").status_code, 400)

    def test_ban_invalidates_existing_session(self):
        adm = self.admin_client(); uid = self.make_player(adm)
        p = self.player_client()
        self.assertEqual(p.get("/api/state").status_code, 200)
        self.assertEqual(self.post(adm, f"/api/admin/users/{uid}/action", action="ban").status_code, 400)  # needs confirm
        self.assertEqual(self.post(adm, f"/api/admin/users/{uid}/action", action="ban", confirm=True).status_code, 200)
        self.assertEqual(p.get("/api/state").status_code, 401)
        self.post(adm, f"/api/admin/users/{uid}/action", action="unban")
        self.assertEqual(self.login(self.client(), "alice", "123456", "player")[0].status_code, 200)

    def test_reset_pin_kicks_and_never_audited_in_clear(self):
        adm = self.admin_client(); uid = self.make_player(adm)
        p = self.player_client()
        self.post(adm, f"/api/admin/users/{uid}/action", action="reset_pin", pin="654321", confirm=True)
        self.assertEqual(p.get("/api/state").status_code, 401)
        self.assertEqual(self.login(self.client(), "alice", "654321", "player")[0].status_code, 200)
        raw = str(adm.get("/api/admin/audit").get_json())
        self.assertNotIn("654321", raw)

    def test_admin_cannot_be_targeted_as_player(self):
        adm = self.admin_client()
        with self.app.app_context():
            aid = get_db().execute("SELECT id FROM users WHERE role='admin'").fetchone()["id"]
        self.assertEqual(self.post(adm, f"/api/admin/users/{aid}/action", action="ban", confirm=True).status_code, 404)

    def test_search_wildcards_escaped(self):
        adm = self.admin_client(); self.make_player(adm)
        self.assertEqual(len(adm.get("/api/admin/users?q=%25").get_json()["users"]), 0)
        self.assertEqual(len(adm.get("/api/admin/users?q=ali").get_json()["users"]), 1)

    def test_persistence_across_app_restart(self):
        adm = self.admin_client(); self.make_player(adm)
        from game import create_app
        app2 = create_app({"DB_PATH": self.app.config["DB_PATH"], "SECRET_KEY": "x" * 32, "ADMIN_PASSWORD": "ignored-here-xx"})
        c = app2.test_client()
        r = c.post("/api/login", json={"username": "alice", "secret": "123456", "role": "player"})
        self.assertEqual(r.status_code, 200)
