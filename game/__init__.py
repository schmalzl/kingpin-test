import logging
import secrets
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from config import BASE_DIR, build_config
from . import database


def _resolve_secret(cfg: dict) -> str:
    if cfg["SECRET_KEY"]:
        return cfg["SECRET_KEY"]
    key_file = Path(cfg["DB_PATH"]).parent / "secret_key"
    if key_file.exists():
        return key_file.read_text().strip()
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(32)
    key_file.write_text(key)
    try:
        key_file.chmod(0o600)
    except OSError:
        pass
    return key


def create_app(overrides: dict | None = None) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static"),
    )
    cfg = build_config()
    if overrides:
        cfg.update(overrides)
    cfg["SECRET_KEY"] = _resolve_secret(cfg)
    app.config.update(cfg)
    if cfg.get("TRUST_PROXY", 0) > 0:
        # Behind a tunnel/proxy every request arrives from 127.0.0.1; read the real client IP from X-Forwarded-For
        # (rightmost N entries only, so a client cannot forge it past the trusted proxy).
        from werkzeug.middleware.proxy_fix import ProxyFix
        n = cfg["TRUST_PROXY"]
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=n, x_proto=n, x_host=0, x_prefix=0)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    Path(cfg["DB_PATH"]).parent.mkdir(parents=True, exist_ok=True)

    database.init_app(app)
    with app.app_context():
        database.init_db()
        from .auth import bootstrap_admin
        bootstrap_admin(app)
        from . import world
        world.init_world(database.get_db())

    from .auth import bp as auth_bp
    from .admin import bp as admin_bp
    from .routes import bp as game_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(game_bp)

    from . import world as _world

    @app.before_request
    def _tick():
        if request.path.startswith("/api/"):
            try:
                _world.maybe_tick()  # cheap check; catches the market up if the background clock was late
            except Exception:
                app.logger.exception("world tick failed")

    if app.config.get("SCHEDULER", True):
        _world.start_scheduler(app)

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.after_request
    def headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; script-src 'self'; "
            "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        if request.path.startswith("/static/") or request.path == "/":
            resp.headers["Cache-Control"] = "no-cache"  # always revalidate so updates apply immediately
        if resp.mimetype == "application/json":
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.errorhandler(404)
    def nf(_):
        return jsonify(error="Not found."), 404

    @app.errorhandler(405)
    def na(_):
        return jsonify(error="Method not allowed."), 405

    @app.errorhandler(413)
    def big(_):
        return jsonify(error="Request too large."), 413

    @app.errorhandler(Exception)
    def boom(e):
        from werkzeug.exceptions import HTTPException
        if isinstance(e, HTTPException):
            return jsonify(error=e.description), e.code
        app.logger.exception("Unhandled error")
        return jsonify(error="Internal server error."), 500

    return app
