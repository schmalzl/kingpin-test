"""SQLite access + versioned migrations. Add new migrations to MIGRATIONS; never edit old ones."""
import sqlite3
from contextlib import contextmanager

from flask import current_app, g

MIGRATIONS = [
    # --- version 1: foundation ---
    """
    CREATE TABLE users (
        id TEXT PRIMARY KEY,
        username TEXT NOT NULL UNIQUE COLLATE NOCASE,
        role TEXT NOT NULL CHECK (role IN ('player','admin')),
        secret_hash TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active'
            CHECK (status IN ('active','disabled','suspended','banned')),
        suspended_until TEXT,
        must_change_secret INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        last_login TEXT,
        last_activity TEXT,
        admin_notes TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE sessions (
        token_hash TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        csrf_token TEXT NOT NULL,
        created_at TEXT NOT NULL,
        last_seen TEXT NOT NULL,
        ip TEXT
    );
    CREATE INDEX idx_sessions_user ON sessions(user_id);
    CREATE TABLE login_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT NOT NULL,
        at TEXT NOT NULL
    );
    CREATE INDEX idx_login_attempts_key ON login_attempts(key, at);
    CREATE TABLE security_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        at TEXT NOT NULL,
        kind TEXT NOT NULL,
        user_id TEXT,
        ip TEXT,
        detail TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE campaigns (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        created_at TEXT NOT NULL,
        cycle INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE player_state (
        user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        level INTEGER NOT NULL CHECK (level >= 1),
        xp INTEGER NOT NULL CHECK (xp >= 0),
        cash INTEGER NOT NULL CHECK (cash >= 0),
        bank INTEGER NOT NULL CHECK (bank >= 0),
        reputation INTEGER NOT NULL,
        wanted INTEGER NOT NULL CHECK (wanted BETWEEN 0 AND 100),
        strain INTEGER NOT NULL CHECK (strain BETWEEN 0 AND 100),
        condition INTEGER NOT NULL CHECK (condition BETWEEN 0 AND 100),
        capacity INTEGER NOT NULL CHECK (capacity >= 0),
        location TEXT NOT NULL
    );
    CREATE TABLE admin_audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        at TEXT NOT NULL,
        admin_id TEXT NOT NULL,
        target_user_id TEXT,
        action TEXT NOT NULL,
        before_value TEXT,
        after_value TEXT,
        note TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX idx_audit_target ON admin_audit_log(target_user_id);
    """,
    # --- version 2: core economy ---
    """
    CREATE TABLE market_state (
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        item_id TEXT NOT NULL,
        price INTEGER NOT NULL CHECK (price > 0),
        prev_price INTEGER NOT NULL CHECK (prev_price > 0),
        supply REAL NOT NULL,
        demand REAL NOT NULL,
        PRIMARY KEY (user_id, item_id)
    );
    CREATE TABLE price_history (
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        item_id TEXT NOT NULL,
        cycle INTEGER NOT NULL,
        price INTEGER NOT NULL,
        PRIMARY KEY (user_id, item_id, cycle)
    );
    CREATE TABLE inventory (
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        item_id TEXT NOT NULL,
        location TEXT NOT NULL,
        quantity INTEGER NOT NULL CHECK (quantity > 0),
        cost_total INTEGER NOT NULL CHECK (cost_total >= 0),
        acquired_cycle INTEGER NOT NULL,
        PRIMARY KEY (user_id, item_id, location)
    );
    CREATE TABLE transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        idem_key TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('buy','sell','advance')),
        item_id TEXT,
        quantity INTEGER,
        unit_price INTEGER,
        total INTEGER NOT NULL DEFAULT 0,
        profit INTEGER,
        cycle INTEGER NOT NULL,
        at TEXT NOT NULL,
        result TEXT NOT NULL,
        UNIQUE (user_id, idem_key)
    );
    CREATE TABLE financial_ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        at TEXT NOT NULL,
        cycle INTEGER NOT NULL,
        kind TEXT NOT NULL,
        amount INTEGER NOT NULL,
        cash_after INTEGER NOT NULL,
        tx_id INTEGER REFERENCES transactions(id)
    );
    CREATE INDEX idx_ledger_user ON financial_ledger(user_id, id);
    CREATE TABLE player_stats (
        user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        revenue INTEGER NOT NULL DEFAULT 0,
        expenditure INTEGER NOT NULL DEFAULT 0,
        tx_count INTEGER NOT NULL DEFAULT 0,
        largest_profit INTEGER NOT NULL DEFAULT 0,
        largest_loss INTEGER NOT NULL DEFAULT 0
    );
    """,
    # --- version 3: progression, missions, contracts, events ---
    """
    CREATE TABLE counters (
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        key TEXT NOT NULL,
        value INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (user_id, key)
    );
    CREATE TABLE mission_progress (
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        mission_id TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('completed','failed')),
        cycle INTEGER NOT NULL,
        PRIMARY KEY (user_id, mission_id)
    );
    CREATE TABLE contracts (
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        contract_id TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('active','completed','failed')),
        accepted_cycle INTEGER NOT NULL,
        deadline_cycle INTEGER NOT NULL,
        PRIMARY KEY (user_id, contract_id)
    );
    CREATE TABLE contact_relations (
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        contact_id TEXT NOT NULL,
        score INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (user_id, contact_id)
    );
    CREATE TABLE events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        event_id TEXT NOT NULL,
        cycle INTEGER NOT NULL,
        severity TEXT NOT NULL CHECK (severity IN ('info','good','warning','severe')),
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        effects TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL CHECK (status IN ('resolved','pending')),
        choices TEXT,
        default_choice INTEGER,
        resolved_choice INTEGER,
        expires_cycle INTEGER
    );
    CREATE INDEX idx_events_user ON events(user_id, id);
    CREATE TABLE market_mods (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        category TEXT NOT NULL,
        factor REAL NOT NULL,
        expires_cycle INTEGER NOT NULL
    );
    CREATE TABLE action_log (
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        idem_key TEXT NOT NULL,
        kind TEXT NOT NULL,
        cycle INTEGER NOT NULL,
        at TEXT NOT NULL,
        result TEXT NOT NULL,
        UNIQUE (user_id, idem_key)
    );
    """,
    # --- version 4: settings + save snapshots (+ backfill for players created before the economy phase) ---
    """
    CREATE TABLE user_settings (
        user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        data TEXT NOT NULL DEFAULT '{}'
    );
    CREATE TABLE save_exports (
        export_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        campaign_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        cycle INTEGER NOT NULL,
        level INTEGER NOT NULL,
        cash INTEGER NOT NULL
    );
    CREATE INDEX idx_save_exports_user ON save_exports(user_id, created_at);
    INSERT OR IGNORE INTO player_stats(user_id) SELECT id FROM users WHERE role='player';
    INSERT INTO financial_ledger(user_id, at, cycle, kind, amount, cash_after)
        SELECT p.user_id, strftime('%Y-%m-%dT%H:%M:%S.000000Z','now'), 0, 'opening',
               p.cash - COALESCE((SELECT SUM(l.amount) FROM financial_ledger l WHERE l.user_id=p.user_id), 0), p.cash
        FROM player_state p
        WHERE p.cash <> COALESCE((SELECT SUM(l.amount) FROM financial_ledger l WHERE l.user_id=p.user_id), 0);
    """,
    # --- version 5: real-time world (global market), announcement ---
    """
    CREATE TABLE announcement (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        message TEXT NOT NULL,
        posted_at TEXT NOT NULL,
        posted_by TEXT
    );
    CREATE TABLE world_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE world_market (
        item_id TEXT PRIMARY KEY,
        price INTEGER NOT NULL CHECK (price > 0),
        prev_price INTEGER NOT NULL CHECK (prev_price > 0),
        supply REAL NOT NULL,
        demand REAL NOT NULL
    );
    CREATE TABLE world_price_history (
        item_id TEXT NOT NULL,
        day INTEGER NOT NULL,
        price INTEGER NOT NULL,
        PRIMARY KEY (item_id, day)
    );
    CREATE TABLE world_mods (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT NOT NULL,
        factor REAL NOT NULL,
        expires_day INTEGER NOT NULL
    );
    DROP TABLE market_state;
    DROP TABLE price_history;
    DROP TABLE market_mods;
    UPDATE contracts SET deadline_cycle = MAX(3, deadline_cycle - COALESCE((SELECT c.cycle FROM campaigns c WHERE c.user_id = contracts.user_id), 0)),
                         accepted_cycle = 0 WHERE status = 'active';
    UPDATE events SET expires_cycle = 6 WHERE status = 'pending';
    UPDATE action_log SET cycle = 0;
    UPDATE campaigns SET cycle = 0;
    """,
    # --- version 6: heartbeat sessions, session end reasons, ban/suspend reasons ---
    """
    ALTER TABLE sessions ADD COLUMN last_beat TEXT NOT NULL DEFAULT '';
    UPDATE sessions SET last_beat = last_seen;
    ALTER TABLE users ADD COLUMN status_reason TEXT NOT NULL DEFAULT '';
    CREATE TABLE ended_sessions (
        token_hash TEXT PRIMARY KEY,
        reason TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT '',
        at TEXT NOT NULL
    );
    """,
    # --- version 7: shops (purchases, season specials), per-item market modifiers ---
    """
    ALTER TABLE world_mods ADD COLUMN item_id TEXT;
    CREATE TABLE purchases (
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        item_id TEXT NOT NULL,
        quantity INTEGER NOT NULL CHECK (quantity > 0),
        PRIMARY KEY (user_id, item_id)
    );
    CREATE TABLE special_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        price INTEGER NOT NULL CHECK (price >= 0),
        min_level INTEGER NOT NULL DEFAULT 1,
        max_per_player INTEGER NOT NULL DEFAULT 0,
        perks TEXT NOT NULL DEFAULT '{}',
        effects TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL
    );
    """,
    # --- version 8: hydration and nutrition ---
    """
    ALTER TABLE player_state ADD COLUMN hydration INTEGER NOT NULL DEFAULT 100 CHECK (hydration BETWEEN 0 AND 100);
    ALTER TABLE player_state ADD COLUMN nutrition INTEGER NOT NULL DEFAULT 100 CHECK (nutrition BETWEEN 0 AND 100);
    """,
]


@contextmanager
def tx():
    """Atomic write block (BEGIN IMMEDIATE serialises writers). Rolls back on any error."""
    db = get_db()
    if db.in_transaction:
        db.commit()
    db.execute("BEGIN IMMEDIATE")
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        conn = sqlite3.connect(current_app.config["DB_PATH"], timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        g.db = conn
    return g.db


def close_db(_exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_app(app) -> None:
    app.teardown_appcontext(close_db)


def init_db() -> None:
    """Idempotent: creates the DB and applies any pending migrations."""
    db = get_db()
    db.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = db.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    current = row["v"] or 0
    for i, script in enumerate(MIGRATIONS[current:], start=current + 1):
        db.executescript("BEGIN;" + script + f"INSERT INTO schema_version(version) VALUES ({i}); COMMIT;")
    db.commit()
