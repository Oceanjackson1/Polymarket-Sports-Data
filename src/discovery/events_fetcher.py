"""事件采集 — 分页获取所有体育赛事事件，解析市场并存入数据库"""
from __future__ import annotations

from tqdm import tqdm

from config import EVENTS_PAGE_SIZE
from src.api_client import gamma_get
from src.database import (
    init_db, save_events, save_markets, save_progress, get_progress,
    get_event_count, get_market_count,
)
from src.discovery.sports_meta import get_sport_tag_map
from src.discovery.markets_parser import parse_event, parse_markets, detect_sport_from_event


def fetch_sports_events(
    sport_names: list[str] | None = None,
    active_only: bool = False,
    include_closed: bool = True,
    resume: bool = True,
    limit: int | None = None,
) -> tuple[int, int]:
    """
    批量获取体育赛事事件及其市场数据。

    参数:
        sport_names: 要采集的运动列表（None = 全部）
        active_only: 是否只采集活跃事件
        include_closed: 是否包含已关闭事件
        resume: 是否从断点恢复
        limit: 最多采集事件数（调试用）

    返回:
        (新增事件数, 新增市场数)
    """
    init_db()
    tag_map = get_sport_tag_map()

    tag_ids_to_fetch = _resolve_tags(sport_names, tag_map)

    task_name = f"events_{'_'.join(sport_names) if sport_names else 'all'}"
    start_offset = 0
    if resume:
        progress = get_progress(task_name)
        if progress:
            start_offset = progress["last_offset"]
            print(f"[Events] 从断点恢复: offset={start_offset}")

    total_events = 0
    total_markets = 0

    for tag_id in tag_ids_to_fetch:
        e, m = _fetch_events_by_tag(
            tag_id=tag_id,
            tag_map=tag_map,
            active_only=active_only,
            include_closed=include_closed,
            task_name=task_name,
            start_offset=start_offset if tag_id == tag_ids_to_fetch[0] else 0,
            limit=limit,
        )
        total_events += e
        total_markets += m

        if limit and total_events >= limit:
            break

    print(f"\n[Events] 采集完成: 新增 {total_events} 个事件, {total_markets} 个市场")
    print(f"[Events] 数据库总计: {get_event_count()} 事件, {get_market_count()} 市场")
    save_progress(task_name, last_offset=0)
    return total_events, total_markets


def _resolve_tags(sport_names: list[str] | None, tag_map: dict) -> list[int]:
    """确定要使用的 tag_id 列表。"""
    if not sport_names:
        # 使用通用体育标签
        return [1]

    generic = {1, 100639}
    tags = []
    for name in sport_names:
        name_lower = name.lower().strip()
        if name_lower in tag_map:
            sport_tags = tag_map[name_lower]
            specific = [t for t in sport_tags if t not in generic]
            tags.append(specific[0] if specific else sport_tags[0])
        else:
            print(f"[Events] 未知运动: {name}，跳过")
    return tags if tags else [1]


def _fetch_events_by_tag(
    tag_id: int,
    tag_map: dict,
    active_only: bool,
    include_closed: bool,
    task_name: str,
    start_offset: int,
    limit: int | None,
) -> tuple[int, int]:
    """用指定 tag_id 分页获取事件。"""
    offset = start_offset
    new_events = 0
    new_markets = 0
    consecutive_empty = 0

    pbar = tqdm(desc=f"tag_id={tag_id}", unit="页")

    while True:
        params: dict = {
            "tag_id": tag_id,
            "limit": EVENTS_PAGE_SIZE,
            "offset": offset,
            "order": "id",
            "ascending": "true",
        }
        if active_only:
            params["active"] = "true"
            params["closed"] = "false"
        elif not include_closed:
            params["closed"] = "false"

        data = gamma_get("/events", params=params)

        if data is None:
            print(f"\n  [Events] 请求失败 offset={offset}，保存进度")
            save_progress(task_name, last_offset=offset)
            break

        if not data:
            break

        batch_events = []
        batch_markets = []

        for raw in data:
            sport = detect_sport_from_event(raw, tag_map)
            if not sport and tag_id == 1:
                continue

            parsed = parse_event(raw, sport)
            if not parsed:
                continue

            batch_events.append(parsed)
            markets = parse_markets(raw, parsed["id"])
            batch_markets.extend(markets)

        if batch_events:
            inserted_e = save_events(batch_events)
            inserted_m = save_markets(batch_markets)
            new_events += inserted_e
            new_markets += inserted_m
            if inserted_e > 0:
                consecutive_empty = 0
            else:
                consecutive_empty += 1
        else:
            consecutive_empty += 1

        pbar.update(1)
        pbar.set_postfix({"events": new_events, "markets": new_markets, "offset": offset})

        save_progress(task_name, last_offset=offset + EVENTS_PAGE_SIZE)

        if len(data) < EVENTS_PAGE_SIZE:
            break

        if limit and new_events >= limit:
            break

        offset += EVENTS_PAGE_SIZE

    pbar.close()
    return new_events, new_markets
