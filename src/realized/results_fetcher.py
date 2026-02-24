"""比赛结果采集 — 从 event 数据中提取结算结果，以及 WebSocket 实时比分"""
from __future__ import annotations

import json
import time

import websocket

from config import WS_SPORTS_URL
from src.database import (
    init_db, get_all_events, get_markets_by_event, save_game_result,
    get_result_count,
)


def extract_results_from_db() -> int:
    """从已存储的事件和市场数据中提取比赛结果。"""
    init_db()
    events = get_all_events()
    saved = 0

    for ev in events:
        if not ev.get("closed"):
            continue

        markets = get_markets_by_event(ev["id"])
        winning_outcome = _determine_winner(markets)

        result = {
            "event_id": ev["id"],
            "game_id": ev.get("game_id", ""),
            "sport": ev.get("sport", ""),
            "home_team": "",
            "away_team": "",
            "final_score": ev.get("score", ""),
            "period": "",
            "status": ev.get("game_status", ""),
            "winning_outcome": winning_outcome,
        }

        moneyline = [m for m in markets if m.get("sports_market_type") == "moneyline"]
        if moneyline:
            m = moneyline[0]
            try:
                outcomes = json.loads(m.get("outcomes", "[]"))
                if len(outcomes) >= 2:
                    result["home_team"] = outcomes[0]
                    result["away_team"] = outcomes[1]
            except (json.JSONDecodeError, TypeError):
                pass

        saved += save_game_result(result)

    print(f"[Results] 提取 {saved} 条比赛结果, 数据库总计 {get_result_count()}")
    return saved


def _determine_winner(markets: list[dict]) -> str:
    """从 outcomePrices 推断获胜 outcome。
    outcomePrices = ["1","0"] 表示第一个 outcome 胜出。
    """
    moneyline = [m for m in markets if m.get("sports_market_type") == "moneyline"]
    if not moneyline:
        moneyline = markets[:1]
    if not moneyline:
        return ""

    m = moneyline[0]
    try:
        prices = json.loads(m.get("outcome_prices", "[]"))
        outcomes = json.loads(m.get("outcomes", "[]"))
    except (json.JSONDecodeError, TypeError):
        return ""

    if not prices or not outcomes:
        return ""

    for i, p in enumerate(prices):
        try:
            if float(p) == 1.0 and i < len(outcomes):
                return outcomes[i]
        except (ValueError, TypeError):
            pass

    return ""


class SportsScoreStreamer:
    """实时比分 WebSocket 客户端。

    用法:
        streamer = SportsScoreStreamer()
        streamer.on_score = lambda data: print(data)
        streamer.start()
    """

    def __init__(self):
        self._ws: websocket.WebSocketApp | None = None
        self._stop = False
        self.on_score = None

    def start(self):
        print("[SportsWS] 连接实时比分推送...")

        self._ws = websocket.WebSocketApp(
            WS_SPORTS_URL,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )

        while not self._stop:
            try:
                self._ws.run_forever()
            except Exception as exc:
                print(f"[SportsWS] 异常: {exc}")
            if not self._stop:
                print("[SportsWS] 3 秒后重连...")
                time.sleep(3)

    def stop(self):
        self._stop = True
        if self._ws:
            self._ws.close()

    def _on_open(self, ws):
        print("[SportsWS] 已连接，等待比分推送...")

    def _on_message(self, ws, message):
        if message == "ping":
            ws.send("pong")
            return

        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return

        game_id = data.get("gameId")
        if game_id and self.on_score:
            self.on_score(data)

        if data.get("ended"):
            result = {
                "event_id": 0,
                "game_id": str(data.get("gameId", "")),
                "sport": data.get("leagueAbbreviation", ""),
                "home_team": data.get("homeTeam", ""),
                "away_team": data.get("awayTeam", ""),
                "final_score": data.get("score", ""),
                "period": data.get("period", ""),
                "status": data.get("status", ""),
                "winning_outcome": "",
                "resolved_at": data.get("finished_timestamp", ""),
            }
            print(f"  [Score] {result['sport'].upper()} "
                  f"{result['away_team']} @ {result['home_team']}: "
                  f"{result['final_score']} ({result['status']})")

    def _on_error(self, ws, error):
        print(f"[SportsWS] 错误: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        print(f"[SportsWS] 关闭: {close_status_code}")
