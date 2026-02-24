#!/usr/bin/env python3
"""
生成样本数据到桌面 — 从数据库中抽样，生成 CSV 和 TXT 说明文件。
输出目录: ~/Desktop/polymarket_sample_data/
"""
from __future__ import annotations

import csv
import json
import os
import sqlite3
from datetime import datetime, timezone

from config import DB_PATH

SAMPLE_DIR = os.path.expanduser("~/Desktop/polymarket_sample_data")


def main():
    os.makedirs(SAMPLE_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    print("=" * 60)
    print("  Polymarket 体育数据 — 样本数据生成")
    print("=" * 60)

    # ── 1. 事件样本 ──────────────────────────────────────────
    events = conn.execute(
        "SELECT * FROM events ORDER BY volume DESC LIMIT 20"
    ).fetchall()
    events_path = os.path.join(SAMPLE_DIR, "sample_events.csv")
    _write_csv(events_path, events)
    print(f"[1/6] 事件样本 → {events_path} ({len(events)} 条)")

    # ── 2. 市场样本（选 3 个高交易量事件的所有市场）─────────
    top_event_ids = [e["id"] for e in events[:3]]
    placeholders = ",".join("?" * len(top_event_ids))
    markets = conn.execute(
        f"SELECT * FROM markets WHERE event_id IN ({placeholders}) ORDER BY volume DESC",
        top_event_ids,
    ).fetchall()
    markets_path = os.path.join(SAMPLE_DIR, "sample_markets.csv")
    _write_csv(markets_path, markets)
    print(f"[2/6] 市场样本 → {markets_path} ({len(markets)} 条)")

    # ── 3. 订单簿样本（选取有深度的 20 个快照）──────────────
    orderbooks = conn.execute(
        "SELECT * FROM orderbook_snapshots "
        "WHERE total_bid_depth > 0 AND total_ask_depth > 0 "
        "ORDER BY total_bid_depth + total_ask_depth DESC LIMIT 20"
    ).fetchall()
    ob_path = os.path.join(SAMPLE_DIR, "sample_orderbooks.csv")
    _write_ob_csv(ob_path, orderbooks)
    print(f"[3/6] 订单簿样本(摘要) → {ob_path} ({len(orderbooks)} 条)")

    # ── 4. 订单簿完整样本（含 bids/asks 明细，JSON）────────
    ob_full = []
    for row in orderbooks[:5]:
        d = dict(row)
        try:
            d["bids"] = json.loads(d.pop("bids_json", "[]"))
            d["asks"] = json.loads(d.pop("asks_json", "[]"))
        except (json.JSONDecodeError, TypeError):
            d["bids"] = []
            d["asks"] = []
        ob_full.append(d)
    ob_full_path = os.path.join(SAMPLE_DIR, "sample_orderbooks_full.json")
    with open(ob_full_path, "w", encoding="utf-8") as f:
        json.dump(ob_full, f, ensure_ascii=False, indent=2)
    print(f"[4/6] 订单簿完整样本 → {ob_full_path} ({len(ob_full)} 条)")

    # ── 5. 成交记录样本（选 2 个 market 的全部 trades）─────
    if markets:
        sample_conds = [markets[0]["condition_id"]]
        if len(markets) > 1:
            sample_conds.append(markets[1]["condition_id"])
        ph = ",".join("?" * len(sample_conds))
        trades = conn.execute(
            f"SELECT * FROM trades WHERE condition_id IN ({ph}) "
            "ORDER BY trade_timestamp",
            sample_conds,
        ).fetchall()
    else:
        trades = conn.execute(
            "SELECT * FROM trades ORDER BY trade_timestamp LIMIT 500"
        ).fetchall()
    trades_path = os.path.join(SAMPLE_DIR, "sample_trades.csv")
    _write_csv(trades_path, trades)
    print(f"[5/6] 成交样本 → {trades_path} ({len(trades)} 条)")

    # ── 6. TXT 说明文件 ──────────────────────────────────────
    total_events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    total_markets = conn.execute("SELECT COUNT(*) FROM markets").fetchone()[0]
    total_snapshots = conn.execute("SELECT COUNT(*) FROM orderbook_snapshots").fetchone()[0]
    total_trades = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]

    txt_path = os.path.join(SAMPLE_DIR, "样本数据说明.txt")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    event_titles = [e["title"] for e in events[:5]]
    market_questions = [m["question"] for m in markets[:5]]

    sample_trade_stats = ""
    if trades:
        total_volume = sum(r["size"] for r in trades)
        min_ts = min(r["trade_timestamp"] for r in trades)
        max_ts = max(r["trade_timestamp"] for r in trades)
        min_dt = datetime.fromtimestamp(min_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        max_dt = datetime.fromtimestamp(max_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        buy_count = sum(1 for r in trades if r["side"] == "BUY")
        sell_count = sum(1 for r in trades if r["side"] == "SELL")
        sample_trade_stats = (
            f"\n  样本交易统计:\n"
            f"    总成交笔数: {len(trades)}\n"
            f"    总成交额:   ${total_volume:,.2f} USDC\n"
            f"    时间范围:   {min_dt} ~ {max_dt} UTC\n"
            f"    BUY 笔数:   {buy_count}\n"
            f"    SELL 笔数:  {sell_count}\n"
        )

    ob_stats = ""
    if orderbooks:
        avg_bid_depth = sum(r["total_bid_depth"] for r in orderbooks) / len(orderbooks)
        avg_ask_depth = sum(r["total_ask_depth"] for r in orderbooks) / len(orderbooks)
        avg_spread = sum(r["spread"] for r in orderbooks) / len(orderbooks)
        ob_stats = (
            f"\n  样本订单簿统计:\n"
            f"    样本数:        {len(orderbooks)}\n"
            f"    平均买盘深度:  ${avg_bid_depth:,.2f}\n"
            f"    平均卖盘深度:  ${avg_ask_depth:,.2f}\n"
            f"    平均价差:      {avg_spread:.4f}\n"
        )

    txt_content = f"""================================================================================
                Polymarket 体育赛事预测市场 — 样本数据说明
================================================================================

生成时间: {now}
数据来源: Polymarket (https://polymarket.com)
采集运动: NBA (National Basketball Association)
采集工具: polymarket-sports-data

================================================================================
一、数据库全量统计
================================================================================

  事件总数:       {total_events:>8,}
  市场总数:       {total_markets:>8,}
  订单簿快照:     {total_snapshots:>8,}
  成交记录:       {total_trades:>8,}

================================================================================
二、样本文件清单
================================================================================

  1. sample_events.csv        — 事件样本（交易量最高的 20 个事件）
  2. sample_markets.csv       — 市场样本（Top 3 事件下的所有市场/盘口）
  3. sample_orderbooks.csv    — 订单簿摘要（深度最大的 20 个快照）
  4. sample_orderbooks_full.json — 订单簿完整数据（含每个价位的 bids/asks 明细）
  5. sample_trades.csv        — 成交记录（2 个代表性市场的全部历史交易）
  6. 样本数据说明.txt          — 本文件

================================================================================
三、样本事件示例（交易量最高的前 5 个）
================================================================================

{chr(10).join(f"  {i+1}. {t}" for i, t in enumerate(event_titles))}

================================================================================
四、样本市场/盘口示例（前 5 个）
================================================================================

{chr(10).join(f"  {i+1}. {q}" for i, q in enumerate(market_questions))}

================================================================================
五、数据统计
================================================================================
{sample_trade_stats}{ob_stats}
================================================================================
六、关键概念定义
================================================================================

  【Full Order Book (完整订单簿)】

  指某一个预测市场 outcome token 在某个时间点的完整挂单深度数据。
  包含两个方向的所有未成交挂单（按价格聚合后）:

    - bids (买单): 所有买方挂出的限价单，按价格从高到低排列
      每一档: {{ "price": "0.55", "size": "1500" }}
      含义: 有人愿意以 $0.55 的价格买入 1500 份该 outcome 的 token

    - asks (卖单): 所有卖方挂出的限价单，按价格从低到高排列
      每一档: {{ "price": "0.60", "size": "800" }}
      含义: 有人愿意以 $0.60 的价格卖出 800 份该 outcome 的 token

  本项目通过 Polymarket CLOB API (GET /book) 获取，返回的是
  聚合后的完整订单簿，即同一价格的所有订单 size 已合并。
  
  注意: 只有当前活跃且接受订单的市场才有有效的 order book。
  已结算的市场 order book 为空。

  【Realized Data (已实现数据)】

  指预测市场中已经实际发生和确认的数据，包含两类:

    1. 已成交交易 (Realized Trades):
       每一笔真实发生的买卖成交记录，包含:
       - side: 方向 (BUY/SELL)
       - price: 成交价格 (0~1，代表概率)
       - size: 成交金额 (USDC)
       - outcome: 预测的结果 (e.g., "Lakers", "Over 210.5")
       - timestamp: 成交时间
       - transaction_hash: Polygon 链上交易哈希

    2. 比赛结果 (Realized Outcomes):
       赛事结束后的最终结果:
       - 最终比分 (score)
       - 获胜方 (winning_outcome)
       - outcome_prices 结算值: ["1","0"] 表示第一个 outcome 胜出

  本项目通过 Polymarket Data API (GET /trades) 获取已成交交易。
  覆盖率约 97%（受 API offset 上限 4000 条限制，使用 BUY+SELL
  分拆策略优化后）。如需 100% 覆盖，可使用链上 OrderFilled
  事件回放模式。

================================================================================
七、CSV 字段说明
================================================================================

  【sample_events.csv】
  id               - Polymarket 事件 ID
  slug             - 事件标识符 (URL 路径)
  title            - 事件标题
  sport            - 运动类型 (nba)
  start_time       - 开始时间
  end_time         - 结束时间
  volume           - 总交易量 (USDC)
  active           - 是否活跃 (1/0)
  closed           - 是否已结算 (1/0)
  neg_risk         - 是否为多结果市场 (1/0)
  polymarket_url   - Polymarket 页面链接

  【sample_markets.csv】
  id               - 市场 ID
  event_id         - 所属事件 ID
  condition_id     - 合约条件 ID (用于查询交易和订单簿)
  question         - 市场问题 (e.g., "Will the Lakers win?")
  sports_market_type - 盘口类型 (moneyline/spreads/totals/...)
  line             - 盘口线 (e.g., -5.5)
  outcomes         - 可能结果 (JSON: ["Yes","No"] 或 ["Lakers","Celtics"])
  outcome_prices   - 当前价格 (JSON: ["0.55","0.45"])
  clob_token_ids   - CLOB Token ID (JSON，用于查询 order book)
  volume           - 市场交易量 (USDC)

  【sample_orderbooks.csv】
  token_id         - CLOB Token ID
  condition_id     - 合约条件 ID
  snapshot_time    - 快照时间 (ISO 8601)
  best_bid         - 最优买价
  best_ask         - 最优卖价
  spread           - 买卖价差
  mid_price        - 中间价 (= (best_bid + best_ask) / 2)
  total_bid_depth  - 买盘总深度 (所有买单的 size 之和)
  total_ask_depth  - 卖盘总深度 (所有卖单的 size 之和)
  bid_levels       - 买盘价位数
  ask_levels       - 卖盘价位数

  【sample_orderbooks_full.json】
  同上 + bids/asks 数组，包含每个价位的 price 和 size

  【sample_trades.csv】
  condition_id     - 合约条件 ID
  trade_timestamp  - 成交时间 (Unix 时间戳)
  side             - 方向 (BUY/SELL)
  outcome          - 预测结果
  size             - 成交额 (USDC)
  price            - 成交价格 (0~1)
  proxy_wallet     - 交易者代理钱包地址
  transaction_hash - Polygon 链上交易哈希

================================================================================
"""

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(txt_content)
    print(f"[6/6] 说明文件 → {txt_path}")

    conn.close()

    print(f"\n{'=' * 60}")
    print(f"  所有样本数据已输出到: {SAMPLE_DIR}")
    print(f"{'=' * 60}")


def _write_csv(path: str, rows: list):
    if not rows:
        return
    fieldnames = list(dict(rows[0]).keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(dict(r))


def _write_ob_csv(path: str, rows: list):
    """订单簿 CSV：排除 raw JSON，增加价位数统计。"""
    if not rows:
        return
    fieldnames = [
        "id", "token_id", "condition_id", "snapshot_time",
        "best_bid", "best_ask", "spread", "mid_price",
        "last_trade_price", "tick_size",
        "total_bid_depth", "total_ask_depth",
        "bid_levels", "ask_levels",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            d = dict(r)
            try:
                bids = json.loads(d.get("bids_json", "[]"))
                asks = json.loads(d.get("asks_json", "[]"))
            except (json.JSONDecodeError, TypeError):
                bids, asks = [], []
            writer.writerow({
                "id": d["id"],
                "token_id": d["token_id"],
                "condition_id": d["condition_id"],
                "snapshot_time": d["snapshot_time"],
                "best_bid": d["best_bid"],
                "best_ask": d["best_ask"],
                "spread": d["spread"],
                "mid_price": d["mid_price"],
                "last_trade_price": d["last_trade_price"],
                "tick_size": d["tick_size"],
                "total_bid_depth": d["total_bid_depth"],
                "total_ask_depth": d["total_ask_depth"],
                "bid_levels": len(bids),
                "ask_levels": len(asks),
            })


if __name__ == "__main__":
    main()
