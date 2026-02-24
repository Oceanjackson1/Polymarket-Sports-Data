#!/usr/bin/env python3
"""
Polymarket 体育赛事预测市场 — 数据采集工具

用法:
    python main.py discover                    # 发现所有体育事件和市场
    python main.py discover --sport nba,nfl    # 只发现指定运动
    python main.py discover --active-only      # 只发现当前活跃事件

    python main.py orderbook                   # 获取订单簿快照
    python main.py orderbook --sport nba       # 只获取 NBA 的订单簿
    python main.py orderbook --stream          # WebSocket 实时流模式

    python main.py trades                      # 获取成交记录
    python main.py trades --sport nba          # 只获取 NBA 的成交

    python main.py results                     # 提取比赛结果
    python main.py results --live              # WebSocket 实时比分

    python main.py export                      # 导出 CSV
    python main.py export --format json        # 导出 JSON

    python main.py all                         # 完整流程
    python main.py all --sport nba             # 只采集 NBA 的完整数据

    python main.py summary                     # 数据库摘要
    python main.py sports                      # 列出所有可用运动
"""
from __future__ import annotations

import argparse
import json
import sys

from config import DATA_DIR
from src.database import (
    init_db, close_db, get_event_count, get_market_count,
    get_snapshot_count, get_trade_count, get_result_count,
    get_active_markets,
)


def cmd_discover(args):
    from src.discovery.sports_meta import fetch_sports_metadata
    from src.discovery.events_fetcher import fetch_sports_events

    fetch_sports_metadata()

    sport_names = None
    if args.sport:
        sport_names = [s.strip().lower() for s in args.sport.split(",")]

    fetch_sports_events(
        sport_names=sport_names,
        active_only=args.active_only,
        include_closed=not args.active_only,
        resume=not args.no_resume,
        limit=args.limit,
    )


def cmd_orderbook(args):
    from src.orderbook.rest_fetcher import fetch_all_active_orderbooks

    if args.stream:
        _stream_orderbook(args)
    else:
        fetch_all_active_orderbooks(sport_filter=args.sport)


def _stream_orderbook(args):
    from src.orderbook.ws_streamer import OrderBookStreamer

    markets = get_active_markets()
    if args.sport:
        sport_lower = args.sport.lower()
        markets = [m for m in markets
                   if sport_lower in (m.get("slug") or "").lower()
                   or sport_lower in (m.get("question") or "").lower()]

    token_ids = []
    for m in markets:
        try:
            ids = json.loads(m.get("clob_token_ids", "[]"))
            token_ids.extend([t for t in ids if t])
        except (json.JSONDecodeError, TypeError):
            pass

    if not token_ids:
        print("[OrderBook] 没有可订阅的 token，请先运行 discover 命令")
        return

    max_tokens = 200
    if len(token_ids) > max_tokens:
        print(f"[OrderBook] 共 {len(token_ids)} 个 token，只订阅前 {max_tokens} 个")
        token_ids = token_ids[:max_tokens]

    streamer = OrderBookStreamer(token_ids, save_to_db=True)
    streamer.on_book = lambda d: print(
        f"  [Book] {d.get('asset_id', '')[:16]}... "
        f"bids={len(d.get('bids', []))} asks={len(d.get('asks', []))}"
    )
    try:
        streamer.start()
    except KeyboardInterrupt:
        print("\n[OrderBook] 已停止")
        streamer.stop()


def cmd_trades(args):
    from src.realized.trades_fetcher import fetch_all_trades

    fetch_all_trades(
        sport_filter=args.sport,
        resume=not args.no_resume,
    )


def cmd_results(args):
    if args.live:
        _stream_scores()
    else:
        from src.realized.results_fetcher import extract_results_from_db
        extract_results_from_db()


def _stream_scores():
    from src.realized.results_fetcher import SportsScoreStreamer

    streamer = SportsScoreStreamer()
    streamer.on_score = lambda d: print(
        f"  [{d.get('leagueAbbreviation', '').upper()}] "
        f"{d.get('awayTeam', '')} @ {d.get('homeTeam', '')} "
        f"{d.get('score', '')} | {d.get('period', '')} "
        f"{'🔴 LIVE' if d.get('live') else ''}"
    )
    try:
        streamer.start()
    except KeyboardInterrupt:
        print("\n[Scores] 已停止")
        streamer.stop()


def cmd_export(args):
    from src.export.exporter import export_all
    export_all(fmt=args.format)


def cmd_all(args):
    """完整流程: discover → orderbook → trades → results → export"""
    from src.discovery.sports_meta import fetch_sports_metadata
    from src.discovery.events_fetcher import fetch_sports_events
    from src.orderbook.rest_fetcher import fetch_all_active_orderbooks
    from src.realized.trades_fetcher import fetch_all_trades
    from src.realized.results_fetcher import extract_results_from_db
    from src.export.exporter import export_all

    sport_names = None
    if args.sport:
        sport_names = [s.strip().lower() for s in args.sport.split(",")]

    print("=" * 60)
    print("Step 1/5: 获取体育元数据")
    print("=" * 60)
    fetch_sports_metadata()

    print("\n" + "=" * 60)
    print("Step 2/5: 发现体育事件和市场")
    print("=" * 60)
    fetch_sports_events(
        sport_names=sport_names,
        active_only=args.active_only,
        include_closed=not args.active_only,
        resume=not args.no_resume,
        limit=args.limit,
    )

    print("\n" + "=" * 60)
    print("Step 3/5: 获取订单簿快照")
    print("=" * 60)
    fetch_all_active_orderbooks(
        sport_filter=args.sport.split(",")[0] if args.sport else None
    )

    print("\n" + "=" * 60)
    print("Step 4/5: 获取成交记录")
    print("=" * 60)
    fetch_all_trades(
        sport_filter=args.sport.split(",")[0] if args.sport else None,
        resume=not args.no_resume,
    )

    print("\n" + "=" * 60)
    print("Step 5/5: 提取比赛结果并导出")
    print("=" * 60)
    extract_results_from_db()
    export_all()

    print("\n" + "=" * 60)
    cmd_summary(args)


def cmd_summary(args):
    init_db()
    print("=" * 50)
    print("         Polymarket 体育数据 — 摘要")
    print("=" * 50)
    print(f"  事件总数:       {get_event_count():>8,}")
    print(f"  市场总数:       {get_market_count():>8,}")
    print(f"  订单簿快照:     {get_snapshot_count():>8,}")
    print(f"  成交记录:       {get_trade_count():>8,}")
    print(f"  比赛结果:       {get_result_count():>8,}")
    print(f"  数据目录:       {DATA_DIR}")
    print("=" * 50)


def cmd_sports(args):
    from src.discovery.sports_meta import fetch_sports_metadata, get_sport_tag_map

    fetch_sports_metadata()
    tag_map = get_sport_tag_map()

    print(f"\n可用运动类型 ({len(tag_map)} 种):")
    print("-" * 40)
    for sport in sorted(tag_map.keys()):
        tags = tag_map[sport]
        print(f"  {sport:<12} tags: {tags}")


def main():
    parser = argparse.ArgumentParser(
        description="Polymarket 体育赛事预测市场数据采集工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", help="子命令")

    # discover
    p_disc = sub.add_parser("discover", help="发现体育事件和市场")
    p_disc.add_argument("--sport", type=str, default=None, help="运动类型 (逗号分隔, e.g. nba,nfl)")
    p_disc.add_argument("--active-only", action="store_true", help="只采集当前活跃事件")
    p_disc.add_argument("--no-resume", action="store_true", help="不使用断点续传")
    p_disc.add_argument("--limit", type=int, default=None, help="最多采集事件数")

    # orderbook
    p_ob = sub.add_parser("orderbook", help="获取订单簿快照")
    p_ob.add_argument("--sport", type=str, default=None, help="运动类型过滤")
    p_ob.add_argument("--stream", action="store_true", help="WebSocket 实时流模式")

    # trades
    p_tr = sub.add_parser("trades", help="获取成交记录")
    p_tr.add_argument("--sport", type=str, default=None, help="运动类型过滤")
    p_tr.add_argument("--no-resume", action="store_true", help="不使用断点续传")

    # results
    p_res = sub.add_parser("results", help="提取比赛结果")
    p_res.add_argument("--live", action="store_true", help="WebSocket 实时比分")

    # export
    p_exp = sub.add_parser("export", help="导出数据")
    p_exp.add_argument("--format", choices=["csv", "json"], default="csv", help="导出格式")

    # all
    p_all = sub.add_parser("all", help="完整采集流程")
    p_all.add_argument("--sport", type=str, default=None, help="运动类型 (逗号分隔)")
    p_all.add_argument("--active-only", action="store_true", help="只采集活跃事件")
    p_all.add_argument("--no-resume", action="store_true", help="不使用断点续传")
    p_all.add_argument("--limit", type=int, default=None, help="最多采集事件数")

    # summary
    sub.add_parser("summary", help="数据库摘要统计")

    # sports
    sub.add_parser("sports", help="列出所有可用运动类型")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    init_db()

    commands = {
        "discover": cmd_discover,
        "orderbook": cmd_orderbook,
        "trades": cmd_trades,
        "results": cmd_results,
        "export": cmd_export,
        "all": cmd_all,
        "summary": cmd_summary,
        "sports": cmd_sports,
    }

    try:
        commands[args.command](args)
    except KeyboardInterrupt:
        print("\n操作已取消")
    finally:
        close_db()


if __name__ == "__main__":
    main()
