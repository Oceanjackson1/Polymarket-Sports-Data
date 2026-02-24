"""市场解析器 — 从 Gamma API 的 event 响应中解析 markets 和 token 信息"""
from __future__ import annotations

import json
from typing import Any

from config import POLYMARKET_EVENT_URL


def detect_sport_from_event(event: dict, sport_tag_map: dict[str, list[int]]) -> str:
    """根据事件的 tags 推断运动类型。"""
    event_tags = set()
    for tag in event.get("tags", []):
        tag_id = tag.get("id")
        if tag_id:
            event_tags.add(int(tag_id))

    generic_tags = {1, 100639}
    best_match = ""
    best_score = 0

    for sport, sport_tags in sport_tag_map.items():
        specific = [t for t in sport_tags if t not in generic_tags]
        overlap = len(event_tags & set(specific))
        if overlap > best_score:
            best_score = overlap
            best_match = sport

    if not best_match:
        series_slug = event.get("seriesSlug", "") or ""
        slug = event.get("slug", "") or ""
        for sport in sport_tag_map:
            if sport in series_slug.lower() or sport in slug.lower():
                return sport

    return best_match


def parse_event(raw: dict, sport: str = "") -> dict | None:
    """解析 Gamma API 返回的 event 原始数据。"""
    event_id = raw.get("id")
    slug = raw.get("slug")
    if not event_id or not slug:
        return None

    return {
        "id": int(event_id),
        "slug": slug,
        "title": raw.get("title", ""),
        "sport": sport,
        "start_time": raw.get("startDate", raw.get("startTime", "")),
        "end_time": raw.get("endDate", ""),
        "game_id": str(raw.get("gameId", "") or ""),
        "game_status": raw.get("gameStatus", ""),
        "score": raw.get("score", ""),
        "volume": float(raw.get("volume", 0) or 0),
        "active": bool(raw.get("active", False)),
        "closed": bool(raw.get("closed", False)),
        "neg_risk": bool(raw.get("negRisk", False)),
        "polymarket_url": POLYMARKET_EVENT_URL.format(slug=slug),
    }


def parse_markets(raw_event: dict, event_id: int) -> list[dict]:
    """从一个 event 的原始数据中提取所有 market。"""
    raw_markets = raw_event.get("markets", [])
    results = []

    for m in raw_markets:
        market_id = m.get("id")
        condition_id = m.get("conditionId", "")
        if not market_id or not condition_id:
            continue

        clob_ids = m.get("clobTokenIds", "")
        if isinstance(clob_ids, list):
            clob_ids = json.dumps(clob_ids)

        outcomes = m.get("outcomes", "")
        if isinstance(outcomes, list):
            outcomes = json.dumps(outcomes)

        outcome_prices = m.get("outcomePrices", "")
        if isinstance(outcome_prices, list):
            outcome_prices = json.dumps(outcome_prices)

        neg_risk = False
        events_in_market = m.get("events", [])
        if events_in_market:
            neg_risk = any(e.get("negRisk") for e in events_in_market)
        if not neg_risk:
            neg_risk = bool(raw_event.get("negRisk", False))

        results.append({
            "id": str(market_id),
            "event_id": event_id,
            "condition_id": condition_id,
            "slug": m.get("slug", ""),
            "question": m.get("question", ""),
            "sports_market_type": m.get("sportsMarketType", ""),
            "line": _safe_float(m.get("line")),
            "outcomes": outcomes,
            "outcome_prices": outcome_prices,
            "clob_token_ids": clob_ids,
            "team_a_id": m.get("teamAID", "") or "",
            "team_b_id": m.get("teamBID", "") or "",
            "volume": float(m.get("volumeNum", 0) or m.get("volume", 0) or 0),
            "closed": bool(m.get("closed", False)),
            "accepting_orders": bool(m.get("acceptingOrders", False)),
            "tick_size": _safe_float(m.get("orderPriceMinTickSize")),
            "neg_risk": neg_risk,
        })

    return results


def _safe_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
