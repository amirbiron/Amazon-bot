import sqlite3
import os
from datetime import datetime, timezone

DB_PATH = os.getenv("DB_PATH", "bot.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS products (
            asin                 TEXT PRIMARY KEY,
            title                TEXT,
            image_url            TEXT,
            product_url          TEXT,
            added_at             TEXT DEFAULT (datetime('now')),
            last_seen_in_catalog TEXT
        );

        CREATE TABLE IF NOT EXISTS product_state (
            asin                  TEXT PRIMARY KEY,
            last_in_stock         INTEGER DEFAULT 0,
            last_price_usd        REAL,
            last_checked_at       TEXT,
            last_restock_alert_at TEXT,
            last_price_alert_at   TEXT
        );

        CREATE TABLE IF NOT EXISTS fx_cache (
            id            INTEGER PRIMARY KEY DEFAULT 1,
            usd_ils_rate  REAL,
            fetched_at    TEXT
        );

        CREATE TABLE IF NOT EXISTS auth_cache (
            id            INTEGER PRIMARY KEY DEFAULT 1,
            access_token  TEXT,
            expires_at    TEXT
        );
        """)


# ── Products ──────────────────────────────────────────────────────────────────

def upsert_product(asin, title, image_url, product_url):
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO products (asin, title, image_url, product_url, added_at, last_seen_in_catalog)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(asin) DO UPDATE SET
                title                = excluded.title,
                image_url            = excluded.image_url,
                product_url          = excluded.product_url,
                last_seen_in_catalog = excluded.last_seen_in_catalog
        """, (asin, title, image_url, product_url, now, now))


def get_all_asins():
    with get_conn() as conn:
        rows = conn.execute("SELECT asin FROM products").fetchall()
    return [r["asin"] for r in rows]


def get_product(asin):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM products WHERE asin=?", (asin,)).fetchone()


# ── Product State ─────────────────────────────────────────────────────────────

def get_state(asin):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM product_state WHERE asin=?", (asin,)).fetchone()


def update_state(asin, in_stock, price_usd):
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO product_state (asin, last_in_stock, last_price_usd, last_checked_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(asin) DO UPDATE SET
                last_in_stock   = excluded.last_in_stock,
                last_price_usd  = excluded.last_price_usd,
                last_checked_at = excluded.last_checked_at
        """, (asin, 1 if in_stock else 0, price_usd, now))


def mark_restock_alert(asin):
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE product_state SET last_restock_alert_at=? WHERE asin=?", (now, asin)
        )


def mark_price_alert(asin):
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE product_state SET last_price_alert_at=? WHERE asin=?", (now, asin)
        )


# ── FX Cache ──────────────────────────────────────────────────────────────────

def get_fx_rate():
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM fx_cache WHERE id=1").fetchone()
    return row


def set_fx_rate(rate):
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO fx_cache (id, usd_ils_rate, fetched_at) VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET usd_ils_rate=excluded.usd_ils_rate, fetched_at=excluded.fetched_at
        """, (rate, now))


# ── Auth Cache ────────────────────────────────────────────────────────────────

def get_token_cache():
    with get_conn() as conn:
        return conn.execute("SELECT * FROM auth_cache WHERE id=1").fetchone()


def clear_token_cache():
    with get_conn() as conn:
        conn.execute("DELETE FROM auth_cache WHERE id=1")


def set_token_cache(access_token, expires_at_iso):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO auth_cache (id, access_token, expires_at) VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET access_token=excluded.access_token, expires_at=excluded.expires_at
        """, (access_token, expires_at_iso))
