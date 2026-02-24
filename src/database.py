"""SQLite 存储层 — 建表、CRUD、进度管理"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

from config import DB_PATH, DATA_DIR

_conn: sqlite3.Connection | None = None


def get_connection() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        os.makedirs(DATA_DIR, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA synchronous=NORMAL")
    return _conn


def init_db():
    conn = get_connection()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS sports (
        sport           TEXT PRIMARY KEY,
        tag_ids         TEXT,
        series_id       TEXT,
        image_url       TEXT,
        resolution_url  TEXT
    );

    CREATE TABLE IF NOT EXISTS events (
        id              INTEGER PRIMARY KEY,
        slug            TEXT UNIQUE,
        title           TEXT,
        sport           TEXT,
        start_time      TEXT,
        end_time        TEXT,
        game_id         TEXT,
        game_status     TEXT,
        score           TEXT,
        volume          REAL,
        active          INTEGER,
        closed          INTEGER,
        neg_risk        INTEGER,
        polymarket_url  TEXT,
        fetched_at      TEXT
    );

    CREATE TABLE IF NOT EXISTS markets (
        id                  TEXT PRIMARY KEY,
        event_id            INTEGER,
        condition_id        TEXT,
        slug                TEXT,
        question            TEXT,
        sports_market_type  TEXT,
        line                REAL,
        outcomes            TEXT,
        outcome_prices      TEXT,
        clob_token_ids      TEXT,
        team_a_id           TEXT,
        team_b_id           TEXT,
        volume              REAL,
        closed              INTEGER,
        accepting_orders    INTEGER,
        tick_size            REAL,
        neg_risk            INTEGER,
        fetched_at          TEXT,
        FOREIGN KEY (event_id) REFERENCES events(id)
    );
    CREATE INDEX IF NOT EXISTS idx_markets_event ON markets(event_id);
    CREATE INDEX IF NOT EXISTS idx_markets_condition ON markets(condition_id);

    CREATE TABLE IF NOT EXISTS orderbook_snapshots (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        token_id         TEXT,
        condition_id     TEXT,
        snapshot_time    TEXT,
        bids_json        TEXT,
        asks_json        TEXT,
        best_bid         REAL,
        best_ask         REAL,
        spread           REAL,
        mid_price        REAL,
        last_trade_price REAL,
        tick_size        TEXT,
        total_bid_depth  REAL,
        total_ask_depth  REAL
    );
    CREATE INDEX IF NOT EXISTS idx_ob_token ON orderbook_snapshots(token_id);
    CREATE INDEX IF NOT EXISTS idx_ob_time  ON orderbook_snapshots(snapshot_time);

    CREATE TABLE IF NOT EXISTS trades (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        event_slug       TEXT,
        condition_id     TEXT,
        trade_timestamp  INTEGER,
        side             TEXT,
        outcome          TEXT,
        size             REAL,
        price            REAL,
        proxy_wallet     TEXT,
        transaction_hash TEXT,
        fetched_at       TEXT,
        UNIQUE(transaction_hash, trade_timestamp, size, side, proxy_wallet)
    );
    CREATE INDEX IF NOT EXISTS idx_trades_cond ON trades(condition_id);

    CREATE TABLE IF NOT EXISTS game_results (
        event_id         INTEGER PRIMARY KEY,
        game_id          TEXT,
        sport            TEXT,
        home_team        TEXT,
        away_team        TEXT,
        final_score      TEXT,
        period           TEXT,
        status           TEXT,
        winning_outcome  TEXT,
        resolved_at      TEXT,
        FOREIGN KEY (event_id) REFERENCES events(id)
    );

    CREATE TABLE IF NOT EXISTS fetch_progress (
        task_name   TEXT PRIMARY KEY,
        last_offset INTEGER DEFAULT 0,
        last_key    TEXT,
        updated_at  TEXT
    );
    """)

    for col, ctype in [("timestamp_ms", "INTEGER"), ("server_received_ms", "INTEGER")]:
        try:
            conn.execute(f"ALTER TABLE trades ADD COLUMN {col} {ctype}")
        except sqlite3.OperationalError:
            pass

    conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Sports ────────────────────────────────────────────────

def save_sports(rows: list[dict]) -> int:
    conn = get_connection()
    inserted = 0
    for r in rows:
        try:
            conn.execute(
                "INSERT OR REPLACE INTO sports (sport, tag_ids, series_id, image_url, resolution_url) "
                "VALUES (?, ?, ?, ?, ?)",
                (r["sport"], r["tag_ids"], r["series_id"], r.get("image_url", ""), r.get("resolution_url", "")),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    return inserted


def get_all_sports() -> list[dict]:
    conn = get_connection()
    return [dict(r) for r in conn.execute("SELECT * FROM sports").fetchall()]


# ── Events ────────────────────────────────────────────────

def save_events(rows: list[dict]) -> int:
    conn = get_connection()
    inserted = 0
    for r in rows:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO events "
                "(id, slug, title, sport, start_time, end_time, game_id, game_status, "
                "score, volume, active, closed, neg_risk, polymarket_url, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    r["id"], r["slug"], r["title"], r.get("sport", ""),
                    r.get("start_time", ""), r.get("end_time", ""),
                    r.get("game_id", ""), r.get("game_status", ""),
                    r.get("score", ""), r.get("volume", 0),
                    int(r.get("active", False)), int(r.get("closed", False)),
                    int(r.get("neg_risk", False)), r.get("polymarket_url", ""),
                    _now(),
                ),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    return inserted


def get_event_count() -> int:
    conn = get_connection()
    return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]


def get_all_events() -> list[dict]:
    conn = get_connection()
    return [dict(r) for r in conn.execute("SELECT * FROM events ORDER BY id").fetchall()]


def get_active_events() -> list[dict]:
    conn = get_connection()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM events WHERE active=1 AND closed=0 ORDER BY id"
    ).fetchall()]


# ── Markets ───────────────────────────────────────────────

def save_markets(rows: list[dict]) -> int:
    conn = get_connection()
    inserted = 0
    for r in rows:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO markets "
                "(id, event_id, condition_id, slug, question, sports_market_type, line, "
                "outcomes, outcome_prices, clob_token_ids, team_a_id, team_b_id, "
                "volume, closed, accepting_orders, tick_size, neg_risk, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    r["id"], r["event_id"], r["condition_id"], r.get("slug", ""),
                    r.get("question", ""), r.get("sports_market_type", ""),
                    r.get("line"), r.get("outcomes", ""), r.get("outcome_prices", ""),
                    r.get("clob_token_ids", ""), r.get("team_a_id", ""),
                    r.get("team_b_id", ""), r.get("volume", 0),
                    int(r.get("closed", False)), int(r.get("accepting_orders", False)),
                    r.get("tick_size"), int(r.get("neg_risk", False)),
                    _now(),
                ),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    return inserted


def get_market_count() -> int:
    conn = get_connection()
    return conn.execute("SELECT COUNT(*) FROM markets").fetchone()[0]


def get_all_markets() -> list[dict]:
    conn = get_connection()
    return [dict(r) for r in conn.execute("SELECT * FROM markets ORDER BY event_id").fetchall()]


def get_active_markets() -> list[dict]:
    conn = get_connection()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM markets WHERE closed=0 AND accepting_orders=1 ORDER BY event_id"
    ).fetchall()]


def get_markets_by_event(event_id: int) -> list[dict]:
    conn = get_connection()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM markets WHERE event_id=?", (event_id,)
    ).fetchall()]


# ── Order Book Snapshots ──────────────────────────────────

def save_orderbook_snapshots(rows: list[dict]) -> int:
    conn = get_connection()
    inserted = 0
    for r in rows:
        conn.execute(
            "INSERT INTO orderbook_snapshots "
            "(token_id, condition_id, snapshot_time, bids_json, asks_json, "
            "best_bid, best_ask, spread, mid_price, last_trade_price, "
            "tick_size, total_bid_depth, total_ask_depth) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                r["token_id"], r["condition_id"], r["snapshot_time"],
                r["bids_json"], r["asks_json"],
                r["best_bid"], r["best_ask"], r["spread"], r["mid_price"],
                r["last_trade_price"], r["tick_size"],
                r["total_bid_depth"], r["total_ask_depth"],
            ),
        )
        inserted += 1
    conn.commit()
    return inserted


def get_snapshot_count() -> int:
    conn = get_connection()
    return conn.execute("SELECT COUNT(*) FROM orderbook_snapshots").fetchone()[0]


# ── Trades ────────────────────────────────────────────────

def save_trades(rows: list[dict]) -> int:
    conn = get_connection()
    inserted = 0
    for r in rows:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO trades "
                "(event_slug, condition_id, trade_timestamp, side, outcome, "
                "size, price, proxy_wallet, transaction_hash, fetched_at, "
                "timestamp_ms, server_received_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    r.get("event_slug", ""), r["condition_id"],
                    r["trade_timestamp"], r["side"], r.get("outcome", ""),
                    r["size"], r["price"], r.get("proxy_wallet", ""),
                    r.get("transaction_hash", ""), _now(),
                    r.get("timestamp_ms"),
                    r.get("server_received_ms"),
                ),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    return inserted


def get_trade_count() -> int:
    conn = get_connection()
    return conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]


def get_trade_count_by_condition(condition_id: str) -> int:
    conn = get_connection()
    return conn.execute(
        "SELECT COUNT(*) FROM trades WHERE condition_id=?", (condition_id,)
    ).fetchone()[0]


# ── Game Results ──────────────────────────────────────────

def save_game_result(r: dict) -> int:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO game_results "
            "(event_id, game_id, sport, home_team, away_team, final_score, "
            "period, status, winning_outcome, resolved_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                r["event_id"], r.get("game_id", ""), r.get("sport", ""),
                r.get("home_team", ""), r.get("away_team", ""),
                r.get("final_score", ""), r.get("period", ""),
                r.get("status", ""), r.get("winning_outcome", ""),
                r.get("resolved_at", _now()),
            ),
        )
        conn.commit()
        return 1
    except sqlite3.IntegrityError:
        return 0


def get_result_count() -> int:
    conn = get_connection()
    return conn.execute("SELECT COUNT(*) FROM game_results").fetchone()[0]


# ── Progress ──────────────────────────────────────────────

def save_progress(task_name: str, last_offset: int = 0, last_key: str = ""):
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO fetch_progress (task_name, last_offset, last_key, updated_at) "
        "VALUES (?, ?, ?, ?)",
        (task_name, last_offset, last_key, _now()),
    )
    conn.commit()


def get_progress(task_name: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM fetch_progress WHERE task_name=?", (task_name,)
    ).fetchone()
    return dict(row) if row else None


def close_db():
    global _conn
    if _conn:
        _conn.close()
        _conn = None
