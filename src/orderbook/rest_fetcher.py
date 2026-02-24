"""订单簿 REST 采集 — 通过 CLOB API 获取 order book 快照"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from tqdm import tqdm

from config import BOOKS_BATCH_SIZE
from src.api_client import clob_get, clob_post
from src.database import (
    init_db, get_active_markets, save_orderbook_snapshots, get_snapshot_count,
)


def fetch_single_orderbook(token_id: str) -> dict | None:
    """获取单个 token 的 order book。"""
    data = clob_get("/book", params={"token_id": token_id})
    if not data:
        return None
    return _parse_book(data)


def fetch_orderbooks_batch(token_ids: list[str]) -> list[dict]:
    """批量获取 order book（POST /books，每批最多 500 个）。"""
    if not token_ids:
        return []

    body = [{"token_id": tid} for tid in token_ids]
    data = clob_post("/books", body)
    if not data or not isinstance(data, list):
        return []

    results = []
    for book in data:
        parsed = _parse_book(book)
        if parsed:
            results.append(parsed)
    return results


def fetch_all_active_orderbooks(sport_filter: str | None = None) -> int:
    """获取所有活跃市场的 order book 快照并存入数据库。"""
    init_db()
    markets = get_active_markets()
    if not markets:
        print("[OrderBook] 没有活跃市场，请先运行 discover 命令")
        return 0

    if sport_filter:
        sport_filter_lower = sport_filter.lower()
        markets = [m for m in markets if _market_sport_match(m, sport_filter_lower)]

    # 收集所有 token_id → condition_id 映射
    token_to_condition: dict[str, str] = {}
    for m in markets:
        clob_ids = m.get("clob_token_ids", "")
        condition_id = m.get("condition_id", "")
        try:
            ids = json.loads(clob_ids)
            for tid in ids:
                if tid:
                    token_to_condition[tid] = condition_id
        except (json.JSONDecodeError, TypeError):
            pass

    all_tokens = list(token_to_condition.keys())
    if not all_tokens:
        print("[OrderBook] 没有有效的 token ID")
        return 0

    print(f"[OrderBook] 共 {len(all_tokens)} 个 token 需要查询 order book")

    total_saved = 0
    batches = [all_tokens[i:i + BOOKS_BATCH_SIZE]
               for i in range(0, len(all_tokens), BOOKS_BATCH_SIZE)]

    pbar = tqdm(total=len(all_tokens), desc="获取 Order Book", unit="token")

    for batch in batches:
        books = fetch_orderbooks_batch(batch)
        snapshot_time = datetime.now(timezone.utc).isoformat()

        rows = []
        for book in books:
            token_id = book.get("asset_id", "")
            rows.append({
                "token_id": token_id,
                "condition_id": token_to_condition.get(token_id, book.get("market", "")),
                "snapshot_time": snapshot_time,
                "bids_json": book.get("bids_json", "[]"),
                "asks_json": book.get("asks_json", "[]"),
                "best_bid": book.get("best_bid", 0),
                "best_ask": book.get("best_ask", 0),
                "spread": book.get("spread", 0),
                "mid_price": book.get("mid_price", 0),
                "last_trade_price": book.get("last_trade_price", 0),
                "tick_size": book.get("tick_size", ""),
                "total_bid_depth": book.get("total_bid_depth", 0),
                "total_ask_depth": book.get("total_ask_depth", 0),
            })

        if rows:
            saved = save_orderbook_snapshots(rows)
            total_saved += saved

        pbar.update(len(batch))
        pbar.set_postfix({"saved": total_saved})

    pbar.close()
    print(f"[OrderBook] 完成: 保存 {total_saved} 个快照, 数据库总计 {get_snapshot_count()}")
    return total_saved


def _parse_book(raw: dict) -> dict | None:
    """将 CLOB API 返回的 order book 数据解析为标准格式。"""
    asset_id = raw.get("asset_id", "")
    if not asset_id:
        return None

    bids = raw.get("bids", [])
    asks = raw.get("asks", [])

    best_bid = float(bids[0]["price"]) if bids else 0
    best_ask = float(asks[0]["price"]) if asks else 0
    spread = best_ask - best_bid if (best_bid > 0 and best_ask > 0) else 0
    mid = (best_bid + best_ask) / 2 if (best_bid > 0 and best_ask > 0) else 0

    total_bid = sum(float(b.get("size", 0)) for b in bids)
    total_ask = sum(float(a.get("size", 0)) for a in asks)

    ltp = raw.get("last_trade_price", "0")
    try:
        ltp = float(ltp)
    except (ValueError, TypeError):
        ltp = 0

    return {
        "asset_id": asset_id,
        "market": raw.get("market", ""),
        "bids_json": json.dumps(bids),
        "asks_json": json.dumps(asks),
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread": round(spread, 6),
        "mid_price": round(mid, 6),
        "last_trade_price": ltp,
        "tick_size": raw.get("tick_size", ""),
        "total_bid_depth": round(total_bid, 2),
        "total_ask_depth": round(total_ask, 2),
    }


def _market_sport_match(market: dict, sport_filter: str) -> bool:
    """粗略判断 market 是否属于指定运动（通过 event 关联）。"""
    slug = (market.get("slug") or "").lower()
    question = (market.get("question") or "").lower()
    return sport_filter in slug or sport_filter in question
