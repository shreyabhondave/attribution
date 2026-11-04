"""PostgreSQL storage (psycopg 3 + connection pool). Raw tables are append-only facts; derived tables are
rebuilt from them.

Design notes
  * Real types: TIMESTAMPTZ for instants, DATE for days, NUMERIC(14,2) for money, BOOLEAN for flags.
    (NUMERIC is loaded back as float, which is plenty for 2-decimal INR totals; see the README.)
  * Concurrency: a pool of connections, READ COMMITTED writes. No application-level write lock; the only
    hot rows are the `counters`, bumped last in each transaction so they are held for microseconds. The
    "something changed" signal is a SEQUENCE (gen_seq), which never blocks writers.
  * Reads run in REPEATABLE READ / READ ONLY, so a report or a pipeline refresh sees ONE consistent
    snapshot even while ingestion keeps committing.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from datetime import UTC, datetime

from psycopg import IsolationLevel
from psycopg.adapt import Loader
from psycopg.types.numeric import FloatLoader
from psycopg_pool import ConnectionPool

from . import config

_pool: ConnectionPool | None = None
_url: str = config.DATABASE_URL
_init_lock = threading.Lock()


class Row(dict):
    """A dict row that also supports positional access (row[0]), like sqlite3.Row did."""

    def __getitem__(self, k):
        return super().__getitem__(k) if not isinstance(k, int) else list(self.values())[k]


def _row_factory(cursor):
    names = [c.name for c in (cursor.description or [])]
    return lambda values: Row(zip(names, values, strict=True))


class _UtcTimestamptz(Loader):
    """Every TIMESTAMPTZ is returned as an aware UTC datetime, whatever the server's TimeZone setting is
    (a server in Asia/Kolkata would otherwise hand back +05:30 values and the UI labels everything UTC)."""

    def load(self, data):
        return datetime.fromisoformat(bytes(data).decode()).astimezone(UTC)


def _configure(conn) -> None:
    conn.row_factory = _row_factory
    conn.adapters.register_loader("numeric", FloatLoader)
    conn.adapters.register_loader("timestamptz", _UtcTimestamptz)


SCHEMA = """
CREATE SEQUENCE IF NOT EXISTS gen_seq;

CREATE TABLE IF NOT EXISTS events (
  event_id      TEXT PRIMARY KEY,            -- idempotency key: pixel retries are dropped here
  event_name    TEXT NOT NULL,
  anonymous_id  TEXT NOT NULL,
  email_hash    TEXT,
  ts_raw        TEXT,                        -- exactly what the device sent
  ts_format     TEXT,                        -- epoch | iso_z | iso_offset | naive_utc
  received_at   TIMESTAMPTZ NOT NULL,
  ts_utc        TIMESTAMPTZ NOT NULL,        -- effective event time (device time if believable)
  ts_ms         BIGINT NOT NULL,             -- same instant as epoch ms, for fast session maths
  ts_source     TEXT NOT NULL,               -- device | received_future | received_stale | received_missing
  page_url      TEXT, referrer TEXT, user_agent TEXT, ip TEXT,
  value         NUMERIC(14,2), currency TEXT, order_id TEXT,
  is_bot        BOOLEAN NOT NULL DEFAULT FALSE,
  channel       TEXT, utm_source TEXT, utm_medium TEXT, utm_campaign TEXT, click_id_type TEXT,
  is_touch      BOOLEAN NOT NULL DEFAULT FALSE   -- page_view carrying a marketing signal
);
CREATE INDEX IF NOT EXISTS ix_events_anon  ON events (anonymous_id, ts_ms);
CREATE INDEX IF NOT EXISTS ix_events_email ON events (email_hash) WHERE email_hash IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_events_order ON events (order_id)   WHERE order_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_events_touch ON events (ts_ms)      WHERE is_touch AND NOT is_bot;

-- every webhook is kept (audit trail); `orders` is the latest state per order_id
CREATE TABLE IF NOT EXISTS order_webhooks (
  order_id TEXT NOT NULL, updated_at TIMESTAMPTZ NOT NULL, financial_status TEXT NOT NULL,
  email_hash TEXT, created_at TIMESTAMPTZ, total NUMERIC(14,2) NOT NULL, currency TEXT,
  PRIMARY KEY (order_id, updated_at, financial_status, total)
);
CREATE TABLE IF NOT EXISTS orders (
  order_id TEXT PRIMARY KEY, email_hash TEXT,
  created_at TIMESTAMPTZ NOT NULL, created_day DATE NOT NULL, created_ms BIGINT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL, financial_status TEXT NOT NULL,
  total NUMERIC(14,2) NOT NULL, currency TEXT NOT NULL, total_inr NUMERIC(14,2) NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_orders_email ON orders (email_hash);
CREATE INDEX IF NOT EXISTS ix_orders_day   ON orders (created_day);

-- every pull from the ad platforms is kept; the newest pull per (date, campaign) is the truth
CREATE TABLE IF NOT EXISTS ad_spend_pulls (
  date DATE NOT NULL, platform TEXT NOT NULL, campaign TEXT NOT NULL,
  spend NUMERIC(14,2) NOT NULL, currency TEXT NOT NULL, pulled_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (date, campaign, pulled_at)
);
CREATE OR REPLACE VIEW ad_spend_current AS
  SELECT DISTINCT ON (date, campaign) date, platform, campaign, spend, currency, pulled_at
  FROM ad_spend_pulls ORDER BY date, campaign, pulled_at DESC;

-- ---------------- derived (safe to truncate; rebuilt by pipeline.refresh) ----------------
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY, anonymous_id TEXT NOT NULL, person_id TEXT, day DATE NOT NULL,
  start_ms BIGINT NOT NULL, end_ms BIGINT NOT NULL, start_ts TIMESTAMPTZ, end_ts TIMESTAMPTZ, duration_s DOUBLE PRECISION,
  n_events INTEGER, n_page_views INTEGER, channel TEXT, utm_campaign TEXT, landing_url TEXT,
  has_atc BOOLEAN, has_checkout BOOLEAN, has_purchase BOOLEAN
);
CREATE INDEX IF NOT EXISTS ix_sessions_anon   ON sessions (anonymous_id);
CREATE INDEX IF NOT EXISTS ix_sessions_day    ON sessions (day);
CREATE INDEX IF NOT EXISTS ix_sessions_person ON sessions (person_id);

CREATE TABLE IF NOT EXISTS person_map (node TEXT PRIMARY KEY, person_id TEXT NOT NULL);  -- 'a:<anon>' | 'e:<email_hash>'
CREATE INDEX IF NOT EXISTS ix_person ON person_map (person_id);

CREATE TABLE IF NOT EXISTS order_attribution (
  order_id TEXT NOT NULL, model TEXT NOT NULL, channel TEXT NOT NULL, campaign TEXT,
  touch_event_id TEXT, touch_ms BIGINT, days_to_order DOUBLE PRECISION, person_id TEXT,
  n_touches INTEGER, reason TEXT, window_days INTEGER,
  PRIMARY KEY (order_id, model)
);

-- ---------------- bookkeeping ----------------
CREATE TABLE IF NOT EXISTS dirty_anons (anonymous_id TEXT PRIMARY KEY, gen BIGINT NOT NULL);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS counters (key TEXT PRIMARY KEY, value BIGINT NOT NULL DEFAULT 0);
"""

_META_DEFAULTS = "INSERT INTO meta (key, value) VALUES ('attr_done','0'), ('refresh_count','0') ON CONFLICT DO NOTHING"
_DATA_TABLES = ("events, order_webhooks, orders, ad_spend_pulls, sessions, person_map, order_attribution, dirty_anons, counters, meta")


def configure(url: str) -> None:
    """Point at a database (tests use their own). Closes any open pool."""
    global _pool, _url
    with _init_lock:
        if _pool is not None:
            _pool.close()
            _pool = None
        _url = url


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        with _init_lock:
            if _pool is None:
                pool = ConnectionPool(_url, min_size=2, max_size=config.DB_POOL_MAX, configure=_configure, open=False,
                                      kwargs={"autocommit": False}, name="urbanthread")
                pool.open(wait=True, timeout=30)
                _pool = pool
    return _pool


def init() -> None:
    """Open the pool and create the schema if needed (idempotent, safe if several workers start at once)."""
    pool = _get_pool()
    with pool.connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(7311001)")  # serialise concurrent first-time DDL
        conn.execute(SCHEMA)
        conn.execute(_META_DEFAULTS)


def close() -> None:
    global _pool
    with _init_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


@contextmanager
def write():
    """A write transaction on a pooled connection: commits on success, rolls back on error."""
    with _get_pool().connection() as conn:
        yield conn


@contextmanager
def read():
    """A read-only, REPEATABLE READ transaction: every query inside sees the same snapshot."""
    with _get_pool().connection() as conn:
        conn.isolation_level = IsolationLevel.REPEATABLE_READ
        conn.read_only = True
        try:
            yield conn
        finally:
            conn.rollback()  # read-only: nothing to commit; also ends the snapshot
            conn.isolation_level = None
            conn.read_only = None


def executemany(conn, sql: str, rows) -> None:
    """Batch statement (psycopg 3 exposes executemany on cursors, and pipelines the round-trips)."""
    with conn.cursor() as cur:
        cur.executemany(sql, rows)


def bump(conn, key: str, n: int = 1) -> None:
    conn.execute("INSERT INTO counters (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = counters.value + EXCLUDED.value",
                 (key, n))


def next_gen(conn) -> int:
    """Draw the next change number (sequences are non-transactional, so this never blocks other writers)."""
    return conn.execute("SELECT nextval('gen_seq') AS g").fetchone()["g"]


def get_gen(conn) -> int:
    return conn.execute("SELECT CASE WHEN is_called THEN last_value ELSE 0 END AS g FROM gen_seq").fetchone()["g"]


def get_meta(conn, key, default=None):
    r = conn.execute("SELECT value FROM meta WHERE key = %s", (key,)).fetchone()
    return r["value"] if r else default


def set_meta(conn, key, value) -> None:
    conn.execute("INSERT INTO meta (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (key, str(value)))


def reset() -> None:
    with write() as c:
        c.execute(f"TRUNCATE {_DATA_TABLES}")
        c.execute("SELECT setval('gen_seq', 1, false)")
        c.execute(_META_DEFAULTS)
