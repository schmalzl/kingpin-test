"""Admin maintenance. Usage:  python manage.py set-admin-password
Sets the administrator password directly in the database (no browser needed), clears the
forced-change flag and signs out every admin session. The password is never stored in clear text."""
import getpass
import os
import sys

from game import create_app
from game import security as sec
from game.database import get_db


def set_admin_password() -> int:
    pw = os.environ.get("KINGPIN_NEW_ADMIN_PASSWORD") or getpass.getpass("New admin password (min 12 chars): ")
    if not os.environ.get("KINGPIN_NEW_ADMIN_PASSWORD") and getpass.getpass("Repeat: ") != pw:
        print("Passwords do not match."); return 1
    app = create_app({"SCHEDULER": False})
    if len(pw) < app.config["ADMIN_PASSWORD_MIN_LENGTH"]:
        print(f"Password must be at least {app.config['ADMIN_PASSWORD_MIN_LENGTH']} characters."); return 1
    with app.app_context():
        db = get_db()
        row = db.execute("SELECT id, username FROM users WHERE role='admin' ORDER BY created_at LIMIT 1").fetchone()
        db.execute("UPDATE users SET secret_hash=?, must_change_secret=0, status='active', suspended_until=NULL WHERE id=?",
                   (sec.hash_secret(pw), row["id"]))
        db.execute("DELETE FROM sessions WHERE user_id=?", (row["id"],))
        db.execute("DELETE FROM login_attempts")
        db.commit()
        print(f"Password updated for '{row['username']}'. Sign in with it on the Administrator tab.")
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["set-admin-password"]:
        sys.exit(set_admin_password())
    print(__doc__); sys.exit(2)
