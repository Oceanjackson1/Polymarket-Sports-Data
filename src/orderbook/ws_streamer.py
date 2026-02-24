"""订单簿 WebSocket 实时流 — 接收 CLOB market channel 的增量更新"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from typing import Callable

import websocket

from config import WS_MARKET_URL
from src.database import init_db, save_orderbook_snapshots


class OrderBookStreamer:
    """WebSocket 订单簿实时流客户端。

    用法:
        streamer = OrderBookStreamer(token_ids=["abc...", "def..."])
        streamer.on_book = lambda data: print(data)
        streamer.start()    # 阻塞，Ctrl+C 退出
    """

    def __init__(
        self,
        token_ids: list[str],
        save_to_db: bool = True,
        save_interval: int = 60,
    ):
        self.token_ids = token_ids
        self.save_to_db = save_to_db
        self.save_interval = save_interval
        self._ws: websocket.WebSocketApp | None = None
        self._stop = False

        self.on_book: Callable[[dict], None] | None = None
        self.on_price_change: Callable[[dict], None] | None = None
        self.on_trade: Callable[[dict], None] | None = None

        self._pending_snapshots: list[dict] = []
        self._lock = threading.Lock()

    def start(self):
        """启动 WebSocket 连接（阻塞）。"""
        init_db()
        print(f"[WS] 订阅 {len(self.token_ids)} 个 token 的 order book 实时流...")

        if self.save_to_db:
            self._start_flush_thread()

        self._ws = websocket.WebSocketApp(
            WS_MARKET_URL,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )

        while not self._stop:
            try:
                self._ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception as exc:
                print(f"[WS] 连接异常: {exc}")
            if not self._stop:
                print("[WS] 3 秒后重连...")
                time.sleep(3)

    def stop(self):
        self._stop = True
        if self._ws:
            self._ws.close()

    def subscribe(self, token_ids: list[str]):
        """动态追加订阅。"""
        if self._ws:
            msg = json.dumps({"assets_ids": token_ids, "operation": "subscribe"})
            self._ws.send(msg)
            self.token_ids.extend(token_ids)

    def unsubscribe(self, token_ids: list[str]):
        if self._ws:
            msg = json.dumps({"assets_ids": token_ids, "operation": "unsubscribe"})
            self._ws.send(msg)

    def _on_open(self, ws):
        sub_msg = json.dumps({
            "assets_ids": self.token_ids,
            "type": "market",
            "custom_feature_enabled": True,
        })
        ws.send(sub_msg)
        print(f"[WS] 已连接并订阅 {len(self.token_ids)} 个 token")

    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return

        event_type = data.get("event_type", "")

        if event_type == "book":
            self._handle_book(data)
        elif event_type == "price_change":
            if self.on_price_change:
                self.on_price_change(data)
        elif event_type == "last_trade_price":
            if self.on_trade:
                self.on_trade(data)

    def _handle_book(self, data: dict):
        if self.on_book:
            self.on_book(data)

        if self.save_to_db:
            bids = data.get("bids", [])
            asks = data.get("asks", [])
            best_bid = float(bids[0]["price"]) if bids else 0
            best_ask = float(asks[0]["price"]) if asks else 0
            spread = best_ask - best_bid if (best_bid and best_ask) else 0
            mid = (best_bid + best_ask) / 2 if (best_bid and best_ask) else 0

            snapshot = {
                "token_id": data.get("asset_id", ""),
                "condition_id": data.get("market", ""),
                "snapshot_time": datetime.now(timezone.utc).isoformat(),
                "bids_json": json.dumps(bids),
                "asks_json": json.dumps(asks),
                "best_bid": best_bid,
                "best_ask": best_ask,
                "spread": round(spread, 6),
                "mid_price": round(mid, 6),
                "last_trade_price": 0,
                "tick_size": "",
                "total_bid_depth": sum(float(b.get("size", 0)) for b in bids),
                "total_ask_depth": sum(float(a.get("size", 0)) for a in asks),
            }
            with self._lock:
                self._pending_snapshots.append(snapshot)

    def _on_error(self, ws, error):
        print(f"[WS] 错误: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        print(f"[WS] 连接关闭: {close_status_code} {close_msg}")

    def _start_flush_thread(self):
        def _flush():
            while not self._stop:
                time.sleep(self.save_interval)
                with self._lock:
                    batch = self._pending_snapshots.copy()
                    self._pending_snapshots.clear()
                if batch:
                    saved = save_orderbook_snapshots(batch)
                    print(f"  [WS-DB] 写入 {saved} 条快照")

        t = threading.Thread(target=_flush, daemon=True)
        t.start()
