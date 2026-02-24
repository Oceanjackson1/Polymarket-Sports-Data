"""链上实时交易监听 — 订阅 Polygon 新区块，解析 OrderFilled 事件

工作流程:
  1. 从数据库构建 token_id → (condition_id, event_slug, outcome) 映射
  2. 连接 Polygon WebSocket RPC，回补最近 N 个区块
  3. eth_subscribe("newHeads") 订阅新区块
  4. 每个区块: eth_getLogs 查询 OrderFilled → 解析 → 写 SQLite → WS 推送
  5. 断线指数退避重连 (1s→2s→4s→…→60s)
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import websockets
import websockets.exceptions

from config import (
    CTF_EXCHANGE,
    NEG_RISK_CTF_EXCHANGE,
    ORDER_FILLED_TOPIC,
    CHAIN_WS_PORT,
    CHAIN_BACKFILL_BLOCKS,
)
from src.database import init_db, get_connection, save_trades


class ChainTradeStreamer:
    """Polygon 链上 OrderFilled 事件实时监听 + 本地 WebSocket 推送。"""

    def __init__(
        self,
        rpc_url: str,
        sport_filter: str | None = None,
        ws_port: int = CHAIN_WS_PORT,
        backfill_blocks: int = CHAIN_BACKFILL_BLOCKS,
    ):
        self.rpc_url = rpc_url
        self.sport_filter = sport_filter
        self.ws_port = ws_port
        self.backfill_blocks = backfill_blocks

        self._rpc_ws: Any = None
        self._req_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._head_sub_id: str | None = None

        self._ws_clients: set = set()
        self._token_lookup: dict[str, dict] = {}
        self._running = False
        self._stats = {"blocks": 0, "trades": 0, "saved": 0}

    # ── Public entry ──────────────────────────────────────

    def run(self):
        """同步入口: 初始化 DB → 构建映射 → 启动事件循环。"""
        init_db()
        self._build_token_lookup()

        if not self._token_lookup:
            print("[ChainStream] 无匹配 token 映射，请先运行 discover 命令")
            return

        unique_conditions = {v["condition_id"] for v in self._token_lookup.values()}
        print(f"[ChainStream] 已加载 {len(self._token_lookup)} 个 token "
              f"({len(unique_conditions)} 个市场)")
        print(f"[ChainStream] RPC: {self.rpc_url[:60]}...")
        print(f"[ChainStream] 本地推送: ws://localhost:{self.ws_port}")
        if self.sport_filter:
            print(f"[ChainStream] 运动过滤: {self.sport_filter}")
        print()

        self._running = True
        try:
            asyncio.run(self._main())
        except KeyboardInterrupt:
            pass
        finally:
            self._running = False
            print("\n[ChainStream] 已停止")

    # ── Async core ────────────────────────────────────────

    async def _main(self):
        ws_task = asyncio.create_task(self._run_ws_server())
        rpc_task = asyncio.create_task(self._rpc_loop())
        try:
            await asyncio.gather(rpc_task, ws_task)
        except asyncio.CancelledError:
            pass

    # ── Token lookup from DB ──────────────────────────────

    def _build_token_lookup(self):
        """从 markets + events 表构建 token_id → 市场信息 映射。"""
        conn = get_connection()
        sql = """
            SELECT m.condition_id, m.clob_token_ids, m.outcomes, m.neg_risk,
                   e.slug AS event_slug, e.sport
            FROM markets m
            JOIN events e ON m.event_id = e.id
        """
        params: list = []
        if self.sport_filter:
            sql += " WHERE LOWER(e.sport) LIKE ? OR LOWER(e.slug) LIKE ?"
            like = f"%{self.sport_filter.lower()}%"
            params = [like, like]

        for row in conn.execute(sql, params).fetchall():
            r = dict(row)
            try:
                tids = json.loads(r.get("clob_token_ids") or "[]")
                outs = json.loads(r.get("outcomes") or "[]")
            except (json.JSONDecodeError, TypeError):
                continue
            for i, tid in enumerate(tids):
                if not tid:
                    continue
                self._token_lookup[str(tid)] = {
                    "condition_id": r["condition_id"],
                    "event_slug": r["event_slug"],
                    "outcome": outs[i] if i < len(outs) else "",
                }

    # ── RPC connection loop (reconnect with backoff) ──────

    async def _rpc_loop(self):
        backoff = 1
        while self._running:
            try:
                await self._connect_and_stream()
                backoff = 1
            except Exception as exc:
                if not self._running:
                    break
                wait = min(backoff, 60)
                print(f"[ChainStream] 连接断开: {exc}")
                print(f"[ChainStream] {wait}s 后重连...")
                await asyncio.sleep(wait)
                backoff = min(backoff * 2, 60)

    async def _connect_and_stream(self):
        async with websockets.connect(
            self.rpc_url,
            max_size=10 * 1024 * 1024,
            ping_interval=30,
            ping_timeout=10,
        ) as ws:
            self._rpc_ws = ws
            self._pending.clear()
            recv_task = asyncio.create_task(self._recv_loop())

            try:
                cur_hex = await self._rpc_call("eth_blockNumber", [])
                cur_num = int(cur_hex, 16)
                print(f"[ChainStream] 当前区块: {cur_num}")

                from_blk = max(0, cur_num - self.backfill_blocks)
                await self._backfill(from_blk, cur_num)

                sub_id = await self._rpc_call("eth_subscribe", ["newHeads"])
                self._head_sub_id = sub_id
                print(f"[ChainStream] 订阅 newHeads OK (sub={sub_id})")
                print("[ChainStream] 实时监听中... Ctrl+C 退出\n")

                await recv_task
            finally:
                recv_task.cancel()
                self._rpc_ws = None

    # ── WebSocket recv multiplexer ────────────────────────

    async def _recv_loop(self):
        try:
            async for raw_msg in self._rpc_ws:
                data = json.loads(raw_msg)

                req_id = data.get("id")
                if req_id is not None and req_id in self._pending:
                    self._pending[req_id].set_result(data)
                    continue

                if data.get("method") == "eth_subscription":
                    p = data.get("params", {})
                    if p.get("subscription") == self._head_sub_id:
                        asyncio.create_task(
                            self._on_head(p.get("result", {}))
                        )
        except websockets.exceptions.ConnectionClosed:
            return

    async def _rpc_call(self, method: str, params: list, timeout: float = 30) -> Any:
        self._req_id += 1
        rid = self._req_id
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[rid] = fut

        await self._rpc_ws.send(json.dumps({
            "jsonrpc": "2.0", "id": rid, "method": method, "params": params,
        }))

        try:
            resp = await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            raise RuntimeError(f"RPC timeout: {method}")
        finally:
            self._pending.pop(rid, None)

        if "error" in resp:
            raise RuntimeError(f"RPC error: {resp['error']}")
        return resp.get("result")

    # ── Backfill recent blocks ────────────────────────────

    async def _backfill(self, from_blk: int, to_blk: int):
        n = to_blk - from_blk + 1
        print(f"[ChainStream] 回补 {from_blk} → {to_blk} ({n} 个区块)...")

        CHUNK = 100
        total_saved = 0

        for start in range(from_blk, to_blk + 1, CHUNK):
            end = min(start + CHUNK - 1, to_blk)
            logs = await self._get_logs(start, end)
            if not logs:
                continue

            ts_cache: dict[int, int] = {}
            for lg in logs:
                bn = int(lg["blockNumber"], 16)
                if bn not in ts_cache:
                    blk = await self._rpc_call(
                        "eth_getBlockByNumber", [hex(bn), False]
                    )
                    ts_cache[bn] = int(blk["timestamp"], 16)

            trades = []
            for lg in logs:
                bn = int(lg["blockNumber"], 16)
                t = self._parse_fill(lg, ts_cache[bn], server_ms=None)
                if t:
                    trades.append(t)

            if trades:
                total_saved += save_trades(trades)

        print(f"[ChainStream] 回补完成: 新增 {total_saved} 笔体育交易")

    # ── New block handler ─────────────────────────────────

    async def _on_head(self, head: dict):
        bn = int(head["number"], 16)
        bts = int(head["timestamp"], 16)
        srv_ms = int(time.time() * 1000)

        self._stats["blocks"] += 1

        logs = await self._get_logs(bn, bn)
        if not logs:
            return

        trades = []
        for lg in logs:
            t = self._parse_fill(lg, bts, srv_ms)
            if t:
                trades.append(t)

        if not trades:
            return

        saved = save_trades(trades)
        self._stats["trades"] += len(trades)
        self._stats["saved"] += saved

        print(
            f"  [Block {bn}] {len(trades)} 笔体育交易, 新增 {saved} | "
            f"累计 {self._stats['trades']} 笔 / {self._stats['blocks']} 区块"
        )

        for t in trades:
            await self._broadcast(t)

    # ── eth_getLogs helper ────────────────────────────────

    async def _get_logs(self, from_blk: int, to_blk: int) -> list[dict]:
        result = await self._rpc_call("eth_getLogs", [{
            "fromBlock": hex(from_blk),
            "toBlock": hex(to_blk),
            "address": [CTF_EXCHANGE, NEG_RISK_CTF_EXCHANGE],
            "topics": [[ORDER_FILLED_TOPIC]],
        }])
        return result or []

    # ── OrderFilled event parser ──────────────────────────

    def _parse_fill(
        self,
        lg: dict,
        block_ts: int,
        server_ms: int | None,
    ) -> dict | None:
        """解析 OrderFilled 事件日志为交易记录 dict。

        OrderFilled(bytes32 indexed orderHash, address indexed maker,
                    address indexed taker, uint256 makerAssetId,
                    uint256 takerAssetId, uint256 makerAmountFilled,
                    uint256 takerAmountFilled, uint256 fee)

        data 布局 (5×32 bytes):
          [0:64]    makerAssetId
          [64:128]  takerAssetId
          [128:192] makerAmountFilled
          [192:256] takerAmountFilled
          [256:320] fee
        """
        topics = lg.get("topics", [])
        data_hex = lg.get("data", "0x")
        if len(topics) < 4 or len(data_hex) < 322:
            return None

        raw = data_hex[2:]
        mk_asset = int(raw[0:64], 16)
        tk_asset = int(raw[64:128], 16)
        mk_amt = int(raw[128:192], 16)
        tk_amt = int(raw[192:256], 16)

        if mk_asset == 0:
            side, token_int, usdc, tokens = "BUY", tk_asset, mk_amt, tk_amt
        elif tk_asset == 0:
            side, token_int, usdc, tokens = "SELL", mk_asset, tk_amt, mk_amt
        else:
            mk_s, tk_s = str(mk_asset), str(tk_asset)
            if mk_s in self._token_lookup:
                side, token_int, usdc, tokens = "SELL", mk_asset, tk_amt, mk_amt
            elif tk_s in self._token_lookup:
                side, token_int, usdc, tokens = "BUY", tk_asset, mk_amt, tk_amt
            else:
                return None

        info = self._token_lookup.get(str(token_int))
        if not info:
            return None

        price = usdc / tokens if tokens > 0 else 0
        log_idx = int(lg.get("logIndex", "0x0"), 16)

        return {
            "event_slug": info["event_slug"],
            "condition_id": info["condition_id"],
            "trade_timestamp": block_ts,
            "side": side,
            "outcome": info["outcome"],
            "size": round(usdc / 1_000_000, 6),
            "price": round(price, 6),
            "proxy_wallet": "0x" + topics[3][-40:],
            "transaction_hash": lg.get("transactionHash", ""),
            "timestamp_ms": block_ts * 1000 + log_idx,
            "server_received_ms": server_ms,
        }

    # ── Local WebSocket broadcast server ──────────────────

    async def _run_ws_server(self):
        async def on_connect(ws, *_args):
            self._ws_clients.add(ws)
            try:
                async for _ in ws:
                    pass
            except websockets.exceptions.ConnectionClosed:
                pass
            finally:
                self._ws_clients.discard(ws)

        server = await websockets.serve(on_connect, "0.0.0.0", self.ws_port)
        print(f"[ChainStream] 推送服务已启动: ws://localhost:{self.ws_port}")
        try:
            await asyncio.Future()
        finally:
            server.close()

    async def _broadcast(self, trade: dict):
        if not self._ws_clients:
            return
        msg = json.dumps(trade, ensure_ascii=False)
        dead = set()
        for ws in list(self._ws_clients):
            try:
                await ws.send(msg)
            except Exception:
                dead.add(ws)
        self._ws_clients -= dead
