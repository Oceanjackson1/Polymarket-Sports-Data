"""数据模型 — 纯 dataclass 定义，无外部依赖"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Sport:
    sport: str
    tag_ids: list[int]
    series_id: str
    image_url: str = ""
    resolution_url: str = ""


@dataclass
class Market:
    id: str
    event_id: int
    condition_id: str
    slug: str
    question: str
    sports_market_type: str
    line: Optional[float]
    outcomes: str           # JSON string: ["Team A", "Team B"]
    outcome_prices: str     # JSON string: ["0.55", "0.45"]
    clob_token_ids: str     # JSON string: ["token_yes", "token_no"]
    team_a_id: str
    team_b_id: str
    volume: float
    closed: bool
    accepting_orders: bool
    tick_size: Optional[float]
    neg_risk: bool = False

    def token_id_list(self) -> list[str]:
        try:
            raw = json.loads(self.clob_token_ids)
            return [t for t in raw if t]
        except (json.JSONDecodeError, TypeError):
            return []


@dataclass
class Event:
    id: int
    slug: str
    title: str
    sport: str
    start_time: str
    end_time: str
    game_id: str
    game_status: str
    score: str
    volume: float
    active: bool
    closed: bool
    neg_risk: bool
    polymarket_url: str
    markets: list[Market] = field(default_factory=list)


@dataclass
class OrderBookSnapshot:
    token_id: str
    condition_id: str
    snapshot_time: str
    bids_json: str
    asks_json: str
    best_bid: float
    best_ask: float
    spread: float
    mid_price: float
    last_trade_price: float
    tick_size: str
    total_bid_depth: float
    total_ask_depth: float


@dataclass
class Trade:
    event_slug: str
    condition_id: str
    trade_timestamp: int
    side: str
    outcome: str
    size: float
    price: float
    proxy_wallet: str
    transaction_hash: str
    timestamp_ms: Optional[int] = None
    server_received_ms: Optional[int] = None
