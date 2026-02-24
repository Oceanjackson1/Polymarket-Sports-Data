"""体育元数据 — 获取所有运动类型及其 tag 映射"""
from __future__ import annotations

from src.api_client import gamma_get
from src.database import init_db, save_sports, get_all_sports


def fetch_sports_metadata() -> list[dict]:
    """从 /sports 端点获取所有运动类型元数据并存入数据库。"""
    init_db()
    print("[Sports] 正在获取体育元数据...")

    data = gamma_get("/sports")
    if not data:
        print("[Sports] 获取失败")
        return []

    rows = []
    for item in data:
        tag_str = item.get("tags", "")
        rows.append({
            "sport": item.get("sport", ""),
            "tag_ids": tag_str,
            "series_id": str(item.get("series", "")),
            "image_url": item.get("image", ""),
            "resolution_url": item.get("resolution", ""),
        })

    saved = save_sports(rows)
    print(f"[Sports] 完成: 共 {len(rows)} 种运动，存入 {saved} 条")
    return rows


def get_sport_tag_map() -> dict[str, list[int]]:
    """返回 sport -> tag_id 列表 的映射。"""
    sports = get_all_sports()
    if not sports:
        fetch_sports_metadata()
        sports = get_all_sports()

    result = {}
    for s in sports:
        tag_str = s.get("tag_ids", "")
        tags = []
        for t in tag_str.split(","):
            t = t.strip()
            if t.isdigit():
                tags.append(int(t))
        result[s["sport"]] = tags
    return result


def get_sport_primary_tags(sport_names: list[str] | None = None) -> list[int]:
    """
    获取指定运动（或全部）的主要 tag_id 列表（去除通用标签 1 和 100639）。
    用于 Gamma API 的 tag_id 过滤参数。
    """
    tag_map = get_sport_tag_map()
    generic_tags = {1, 100639}

    if sport_names:
        selected = {k: v for k, v in tag_map.items() if k in sport_names}
    else:
        selected = tag_map

    primary_tags = []
    for sport, tags in selected.items():
        specific = [t for t in tags if t not in generic_tags]
        if specific:
            primary_tags.append(specific[0])
        elif tags:
            primary_tags.append(tags[0])
    return primary_tags


def list_available_sports() -> list[str]:
    """列出数据库中所有可用的运动缩写。"""
    tag_map = get_sport_tag_map()
    return sorted(tag_map.keys())
