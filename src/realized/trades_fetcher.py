"""成交记录采集 — 从 Data API 获取历史 trades（含 BUY+SELL 分拆策略）"""
from __future__ import annotations

from tqdm import tqdm

from config import TRADES_PAGE_SIZE, TRADES_MAX_OFFSET
from src.api_client import data_get
from src.database import (
    init_db, get_all_markets, save_trades, save_progress, get_progress,
    get_trade_count, get_trade_count_by_condition,
)


def fetch_trades_for_market(condition_id: str, event_slug: str = "") -> list[dict]:
    """
    获取单个 market 的所有成交记录。
    先用无 side 过滤分页获取；如果触及 offset 上限，
    改用 BUY + SELL 分拆策略扩大覆盖。
    """
    trades, hit_limit = _paginate_trades(condition_id)

    if hit_limit:
        buy_trades, _ = _paginate_trades(condition_id, side="BUY")
        sell_trades, _ = _paginate_trades(condition_id, side="SELL")
        merged = _merge_deduplicate(buy_trades + sell_trades)
        if len(merged) > len(trades):
            trades = merged

    for t in trades:
        t["event_slug"] = event_slug

    return trades


def fetch_all_trades(
    sport_filter: str | None = None,
    resume: bool = True,
    skip_fetched: bool = True,
) -> int:
    """获取所有市场的成交记录。"""
    init_db()
    markets = get_all_markets()
    if not markets:
        print("[Trades] 没有市场数据，请先运行 discover 命令")
        return 0

    if sport_filter:
        sport_lower = sport_filter.lower()
        markets = [m for m in markets
                   if sport_lower in (m.get("slug") or "").lower()
                   or sport_lower in (m.get("question") or "").lower()]

    task_name = f"trades_{sport_filter or 'all'}"
    start_slug = ""
    if resume:
        progress = get_progress(task_name)
        if progress and progress.get("last_key"):
            start_slug = progress["last_key"]
            print(f"[Trades] 从断点恢复: last_slug={start_slug}")

    skipping = bool(start_slug)
    total_new = 0

    pbar = tqdm(total=len(markets), desc="采集 Trades", unit="market")

    for m in markets:
        slug = m.get("slug", "")
        condition_id = m.get("condition_id", "")

        if skipping:
            if slug == start_slug:
                skipping = False
            pbar.update(1)
            continue

        if not condition_id:
            pbar.update(1)
            continue

        if skip_fetched and get_trade_count_by_condition(condition_id) > 0:
            pbar.update(1)
            continue

        trades = fetch_trades_for_market(condition_id, event_slug=slug)
        if trades:
            saved = save_trades(trades)
            total_new += saved
        else:
            saved = 0

        pbar.update(1)
        pbar.set_postfix({"new": total_new, "batch": saved})
        save_progress(task_name, last_key=slug)

    pbar.close()
    print(f"[Trades] 完成: 新增 {total_new} 条交易, 数据库总计 {get_trade_count()}")
    save_progress(task_name, last_key="")
    return total_new


def _paginate_trades(
    condition_id: str,
    side: str | None = None,
) -> tuple[list[dict], bool]:
    """分页获取 trades，返回 (trades列表, 是否触及offset上限)。"""
    all_trades: list[dict] = []
    offset = 0
    hit_limit = False

    while True:
        params: dict = {
            "market": condition_id,
            "limit": TRADES_PAGE_SIZE,
            "offset": offset,
        }
        if side:
            params["side"] = side

        data = data_get("/trades", params=params)

        if data is None:
            break
        if not data:
            break

        for raw in data:
            all_trades.append(_parse_trade(raw, condition_id))

        if len(data) < TRADES_PAGE_SIZE:
            break

        offset += TRADES_PAGE_SIZE
        if offset > TRADES_MAX_OFFSET:
            hit_limit = True
            break

    return all_trades, hit_limit


def _parse_trade(raw: dict, condition_id: str) -> dict:
    return {
        "condition_id": condition_id,
        "trade_timestamp": int(raw.get("timestamp", 0)),
        "side": raw.get("side", ""),
        "outcome": raw.get("outcome", ""),
        "size": float(raw.get("size", 0)),
        "price": float(raw.get("price", 0)),
        "proxy_wallet": raw.get("proxyWallet", ""),
        "transaction_hash": raw.get("transactionHash", ""),
        "event_slug": raw.get("eventSlug", ""),
    }


def _merge_deduplicate(trades: list[dict]) -> list[dict]:
    """基于 (txHash, timestamp, size, side, wallet) 去重。"""
    seen = set()
    unique = []
    for t in trades:
        key = (
            t.get("transaction_hash", ""),
            t.get("trade_timestamp", 0),
            round(t.get("size", 0), 8),
            t.get("side", ""),
            t.get("proxy_wallet", ""),
        )
        if key not in seen:
            seen.add(key)
            unique.append(t)
    return unique
