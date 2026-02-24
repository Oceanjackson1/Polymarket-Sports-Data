"""数据导出 — CSV / JSON 导出功能"""
from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone

from config import DATA_DIR
from src.database import get_connection, init_db


def export_events_csv(output_path: str | None = None) -> str:
    init_db()
    path = output_path or os.path.join(DATA_DIR, "events.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = get_connection()
    rows = conn.execute("SELECT * FROM events ORDER BY id").fetchall()
    if not rows:
        print("[Export] 无事件数据")
        return path
    _write_csv(path, [dict(r) for r in rows])
    print(f"[Export] 事件 → {path} ({len(rows)} 条)")
    return path


def export_markets_csv(output_path: str | None = None) -> str:
    init_db()
    path = output_path or os.path.join(DATA_DIR, "markets.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = get_connection()
    rows = conn.execute("SELECT * FROM markets ORDER BY event_id").fetchall()
    if not rows:
        print("[Export] 无市场数据")
        return path
    _write_csv(path, [dict(r) for r in rows])
    print(f"[Export] 市场 → {path} ({len(rows)} 条)")
    return path


def export_orderbooks_csv(output_path: str | None = None) -> str:
    init_db()
    path = output_path or os.path.join(DATA_DIR, "orderbooks.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, token_id, condition_id, snapshot_time, "
        "best_bid, best_ask, spread, mid_price, last_trade_price, "
        "tick_size, total_bid_depth, total_ask_depth "
        "FROM orderbook_snapshots ORDER BY snapshot_time"
    ).fetchall()
    if not rows:
        print("[Export] 无订单簿数据")
        return path
    _write_csv(path, [dict(r) for r in rows])
    print(f"[Export] 订单簿 → {path} ({len(rows)} 条)")
    return path


def export_orderbooks_full_json(output_path: str | None = None) -> str:
    """导出完整订单簿（含 bids/asks 明细）为 JSON。"""
    init_db()
    path = output_path or os.path.join(DATA_DIR, "orderbooks_full.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM orderbook_snapshots ORDER BY snapshot_time"
    ).fetchall()
    if not rows:
        print("[Export] 无订单簿数据")
        return path
    data = []
    for r in rows:
        d = dict(r)
        try:
            d["bids"] = json.loads(d.pop("bids_json", "[]"))
            d["asks"] = json.loads(d.pop("asks_json", "[]"))
        except (json.JSONDecodeError, TypeError):
            d["bids"] = []
            d["asks"] = []
        data.append(d)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[Export] 订单簿(完整) → {path} ({len(data)} 条)")
    return path


def export_trades_csv(output_path: str | None = None) -> str:
    init_db()
    path = output_path or os.path.join(DATA_DIR, "trades.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = get_connection()
    rows = conn.execute("SELECT * FROM trades ORDER BY trade_timestamp").fetchall()
    if not rows:
        print("[Export] 无交易数据")
        return path
    dicts = []
    for r in rows:
        d = dict(r)
        d.pop("server_received_ms", None)
        ts_ms = d.get("timestamp_ms")
        if ts_ms is not None:
            ts_s = ts_ms // 1000
            ms_frac = ts_ms % 1000
            dt = datetime.fromtimestamp(ts_s, tz=timezone.utc)
            d["trade_time_ms"] = f"{dt.strftime('%Y-%m-%d %H:%M:%S')}.{ms_frac:03d} UTC"
        else:
            d["trade_time_ms"] = ""
        dicts.append(d)
    _write_csv(path, dicts)
    print(f"[Export] 交易 → {path} ({len(rows)} 条)")
    return path


def export_results_csv(output_path: str | None = None) -> str:
    init_db()
    path = output_path or os.path.join(DATA_DIR, "results.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = get_connection()
    rows = conn.execute("SELECT * FROM game_results ORDER BY event_id").fetchall()
    if not rows:
        print("[Export] 无比赛结果数据")
        return path
    _write_csv(path, [dict(r) for r in rows])
    print(f"[Export] 结果 → {path} ({len(rows)} 条)")
    return path


def export_all(fmt: str = "csv"):
    """导出所有数据表。"""
    export_events_csv()
    export_markets_csv()
    export_trades_csv()
    export_results_csv()
    if fmt == "json":
        export_orderbooks_full_json()
    else:
        export_orderbooks_csv()
    print("[Export] 所有数据已导出至 data/ 目录")


def _write_csv(path: str, rows: list[dict]):
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
