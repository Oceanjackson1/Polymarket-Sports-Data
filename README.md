# Polymarket 体育赛事预测市场 — 数据采集工具

从 [Polymarket](https://polymarket.com) 采集体育类预测事件的 **Full Order Book（完整订单簿）** 和 **Realized Data（已实现数据）**。

支持 145 种体育/电竞赛事（NBA、NFL、EPL、UFC、CS2 等），纯 Python 实现，**无需 API Key**（链上实时模式需 Polygon RPC）。

**核心能力：**
- **批量拉取**：Data API 历史成交，覆盖 ~97%
- **链上实时监听**：Polygon OrderFilled 事件，覆盖 100%，毫秒级时间戳
- **本地 WebSocket 推送**：实时交易事件广播，可对接下游系统

---

## 目录

- [核心概念定义](#核心概念定义)
- [项目能力总结](#项目能力总结)
- [快速开始](#快速开始)
- [使用方式](#使用方式)
- [实时链上监听（stream-trades）](#实时链上监听stream-trades)
- [数据结构与字段说明](#数据结构与字段说明)
- [技术架构](#技术架构)
- [API 限制与应对策略](#api-限制与应对策略)
- [常见问题](#常见问题)

---

## 核心概念定义

### 什么是 Full Order Book（完整订单簿）

**Full Order Book** 是某一个预测市场 outcome token 在某个时间点的 **全部未成交挂单的深度数据**。

在 Polymarket 中，每个预测事件（如"Lakers vs Celtics 谁赢？"）有若干个 market（盘口），每个 market 有 2 个或多个 outcome token（如 "Lakers Win" 和 "Celtics Win"）。每个 token 都有一个独立的订单簿。

**订单簿包含两个方向：**

```
买盘 (Bids)                              卖盘 (Asks)
──────────────────                       ──────────────────
想以某个价格买入的所有挂单                想以某个价格卖出的所有挂单
按价格从高到低排列                        按价格从低到高排列

价格    数量(USDC)                       价格    数量(USDC)
0.55    1,500          ← 最优买价        0.57    800         ← 最优卖价
0.54    3,200                            0.58    1,200
0.53    5,000                            0.59    2,000
0.52    2,800                            0.60    4,500
0.50    10,000                           0.65    8,000
...     ...                              ...     ...
```

**关键指标：**

| 指标 | 含义 |
|------|------|
| **best_bid** | 最优买价 — 当前最高的买入报价 |
| **best_ask** | 最优卖价 — 当前最低的卖出报价 |
| **spread** | 价差 = best_ask - best_bid，越小说明市场越活跃 |
| **mid_price** | 中间价 = (best_bid + best_ask) / 2，Polymarket 显示的"概率"即此值 |
| **total_bid_depth** | 买盘总深度 — 所有买单 size 的总和 |
| **total_ask_depth** | 卖盘总深度 — 所有卖单 size 的总和 |
| **bid_levels / ask_levels** | 买/卖盘的价位档数 |

**"Full" 的含义：**

本项目获取的是 Polymarket CLOB（Central Limit Order Book）API 返回的 **聚合后的完整订单簿**：
- ✅ 包含所有价位档的 bid 和 ask
- ✅ 同一价格的所有订单 size 已合并
- ✅ 涵盖当前活跃市场的全部挂单深度
- ❌ 不包含单个订单的明细（如谁挂了多少）
- ❌ 已结算市场的 order book 为空

**数据获取方式：**

| 方式 | 端点 | 说明 |
|------|------|------|
| REST 快照 | `GET https://clob.polymarket.com/book?token_id=TOKEN_ID` | 获取某一时刻的完整快照 |
| REST 批量 | `POST https://clob.polymarket.com/books` | 最多 500 个 token 同时查询 |
| WebSocket | `wss://ws-subscriptions-clob.polymarket.com/ws/market` | 实时增量推送 |

---

### 什么是 Realized Data（已实现数据）

**Realized Data** 是预测市场中 **已经实际发生和确认** 的数据，与 Order Book 中"尚未成交的挂单"相对。

Realized Data 由两部分构成：

#### 1. 已成交交易（Realized Trades / Fills）

每一笔已经被撮合成交的买卖记录。当一个新订单与订单簿中的现有挂单匹配时，就产生一笔"成交"。

```
示例成交记录:
┌──────────────────┬────────────────────────────────────────┐
│ 字段              │ 值                                      │
├──────────────────┼────────────────────────────────────────┤
│ side             │ BUY                                     │
│ outcome          │ Lakers                                  │
│ price            │ 0.55                                    │
│ size             │ 100.00 USDC                             │
│ timestamp        │ 2026-02-24 08:30:00 UTC                 │
│ timestamp_ms     │ 1771929600635                            │
│ trade_time_ms    │ 2026-02-24 08:30:00.635 UTC             │
│ transaction_hash │ 0x3c240944c4c1a49c0c11c4ce99...         │
│ proxy_wallet     │ 0xe7f7e2d3d4d0e164239f3cc30a...         │
└──────────────────┴────────────────────────────────────────┘
```

> `timestamp_ms` 和 `trade_time_ms` 仅在链上实时监听模式下有值。Data API 批量拉取的数据该字段为 NULL/空。

**字段含义：**

| 字段 | 含义 |
|------|------|
| `side` | 交易方向：BUY（买入该 outcome 的份额）或 SELL（卖出） |
| `outcome` | 预测的结果标签（如 "Lakers"、"Over 210.5"、"Yes"） |
| `price` | 成交价格，范围 0~1，代表市场对该结果发生的概率估计 |
| `size` | 成交金额（USDC），即该笔交易投入的资金量 |
| `timestamp` | 成交时间（Unix 时间戳） |
| `transaction_hash` | Polygon 链上的交易哈希，可在区块浏览器中验证 |
| `proxy_wallet` | 交易者的代理钱包地址 |

**价格与概率的关系：**
- `price = 0.55` 表示市场认为该结果有 55% 的概率发生
- 买入 $100 在 price=0.55 时，如果预测正确，可获得 $100/0.55 ≈ $181.8（净赚 $81.8）
- 如果预测错误，$100 全部损失

#### 2. 比赛结果（Realized Outcomes）

赛事结束后的最终结算数据：

| 字段 | 含义 |
|------|------|
| `score` | 最终比分，如 "110-105" |
| `winning_outcome` | 获胜方，如 "Lakers" |
| `outcome_prices` | 结算值：`["1","0"]` 表示第一个 outcome 胜出，持有者可 1:1 兑回 USDC |
| `game_status` | 比赛状态：Final / F/OT（加时） / Canceled 等 |

**数据获取方式：**

| 方式 | 端点 | 覆盖率 | 说明 |
|------|------|--------|------|
| Data API 批量拉取 | `GET https://data-api.polymarket.com/trades` | ~97% | 纯 API，无需认证，BUY+SELL 分拆策略 |
| **链上实时监听** | **Polygon CTF Exchange `OrderFilled` 事件** | **100%** | **WebSocket RPC 订阅新区块，毫秒级时间戳** |
| Subgraph | Goldsky GraphQL | 100% | 索引后的链上数据，GraphQL 查询 |
| Sports WS | `wss://sports-api.polymarket.com/ws` | 实时 | 实时比分推送 |

**两种 Trades 获取模式对比：**

| 维度 | 批量拉取 (`trades`) | 实时监听 (`stream-trades`) |
|------|---------------------|---------------------------|
| 数据来源 | Data API | Polygon 链上 OrderFilled 事件 |
| 覆盖率 | ~97% (受 offset 上限限制) | 100% (直接读链) |
| 时间精度 | 秒级 (API 原生限制) | 毫秒级 (`block_ts × 1000 + log_index`) |
| 适用场景 | 历史回补、批量分析 | 实时交易监控、低延迟信号 |
| 额外能力 | — | 本地 WebSocket 推送、`server_received_ms` |

**为什么 Data API 覆盖率是 ~97%？**

Data API 的 `/trades` 端点有分页限制：`offset + limit` 不能超过 4000。本项目使用 BUY+SELL 分拆策略覆盖约 97%。**如需 100% 覆盖，使用 `stream-trades` 链上实时监听模式。**

---

### Realized Data 与 Full Order Book 的对比

| 维度 | Full Order Book | Realized Data |
|------|-----------------|---------------|
| **本质** | 未成交的挂单 | 已成交的交易 + 最终结果 |
| **时态** | 当前时刻的"意愿" | 过去已发生的"事实" |
| **变化性** | 实时变化（每秒可能更新） | 不可变（成交后永久记录） |
| **数据来源** | CLOB API（订单簿引擎） | Data API / 链上事件 |
| **用途** | 分析市场深度、流动性、价差 | 分析历史价格、交易量、交易者行为 |
| **举例** | "当前有人挂了 $1000 在 0.55 买 Lakers" | "昨天某人花了 $500 在 0.55 买入了 Lakers" |

---

## 项目能力总结

| 能力 | 状态 | 说明 |
|------|------|------|
| 发现所有体育赛事事件 | ✅ | 通过 Gamma API 的 `/sports` + `/events`，覆盖 145 种运动 |
| 解析每个事件下所有盘口 | ✅ | moneyline、spreads、totals、player props 等全部盘口类型 |
| 获取 Full Order Book | ✅ | REST 快照（批量）+ WebSocket 实时流 |
| 批量拉取 Realized Trades | ✅ | Data API + BUY/SELL 分拆策略，覆盖 ~97% |
| **链上实时监听 Trades** | ✅ | **Polygon OrderFilled 事件，100% 覆盖，毫秒级时间戳** |
| **本地 WebSocket 推送** | ✅ | **实时交易事件广播至 `ws://localhost:8765`** |
| **毫秒级时间戳** | ✅ | **`timestamp_ms = block_ts × 1000 + log_index`** |
| 获取比赛结果 | ✅ | 从 event 数据提取 + Sports WebSocket 实时比分 |
| 按运动类型过滤 | ✅ | `--sport nba,nfl` 支持任意组合 |
| 断点续传 | ✅ | 所有长时间任务支持中断后恢复 |
| 数据导出 | ✅ | CSV 和 JSON 格式，含 `timestamp_ms` 和 `trade_time_ms` 列 |
| 断线自动重连 | ✅ | 链上监听指数退避重连（1s→2s→4s→...→60s） |

---

## 快速开始

### 环境要求

- Python 3.9+
- 网络连接（需访问 Polymarket API）

### 安装

```bash
git clone <this-repo>
cd polymarket-sports-data
pip install -r requirements.txt
```

### 一键采集 NBA 数据

```bash
# 采集当前活跃的 NBA 事件的所有数据
python main.py all --sport nba --active-only
```

这将依次执行：
1. 获取体育元数据（145 种运动）
2. 发现 NBA 事件和市场
3. 获取所有活跃市场的 Full Order Book 快照
4. 获取所有市场的历史成交记录
5. 提取比赛结果并导出 CSV

### 实时监听 NBA 链上成交

```bash
python main.py stream-trades --sport nba --rpc-url wss://polygon-mainnet.g.alchemy.com/v2/YOUR_KEY
```

启动后持续运行：
1. 回补最近 100 个区块的历史数据
2. 实时订阅新区块，解析 OrderFilled 事件
3. 匹配体育交易，写入 SQLite（与批量数据共表）
4. 通过 `ws://localhost:8765` 推送 JSON 格式交易事件

### 生成样本数据到桌面

```bash
python generate_sample.py
```

输出到 `~/Desktop/polymarket_sample_data/`，包含 CSV 和 TXT 说明文件。

---

## 使用方式

### 查看所有可用运动

```bash
python main.py sports
```

输出 145 种运动缩写及其 tag_id，例如：
```
  nba          tags: [1, 745, 100639]
  nfl          tags: [1, 450, 100639]
  epl          tags: [1, 82, 306, 100639, 100350]
  cs2          tags: [1, 64, 100780, 100639]
```

### 发现事件和市场

```bash
python main.py discover                        # 所有体育事件
python main.py discover --sport nba,nfl         # 只发现 NBA 和 NFL
python main.py discover --active-only           # 只发现当前活跃事件
python main.py discover --sport nba --limit 10  # 限制数量（调试用）
```

### 获取 Full Order Book

```bash
python main.py orderbook                        # 所有活跃市场
python main.py orderbook --sport nba            # 只获取 NBA
python main.py orderbook --stream               # WebSocket 实时流模式
```

**REST 模式**：一次性获取所有活跃市场的 order book 快照并存入数据库。

**Stream 模式**：通过 WebSocket 持续接收实时订单簿更新，每 60 秒自动存入数据库。按 Ctrl+C 停止。

### 获取 Realized Data（成交记录）

```bash
python main.py trades                           # 所有市场
python main.py trades --sport nba               # 只获取 NBA
python main.py trades --no-resume               # 不使用断点续传，从头开始
```

注意：成交记录采集耗时较长（每个市场需要多次 API 请求）。支持断点续传，可以随时中断后再继续。

---

## 实时链上监听（stream-trades）

通过 Polygon WebSocket RPC 订阅新区块，实时解析 CTF Exchange 和 NegRisk CTF Exchange 合约的 `OrderFilled` 事件。

### 基本用法

```bash
# 监听所有体育赛事
python main.py stream-trades --rpc-url wss://polygon-mainnet.g.alchemy.com/v2/YOUR_KEY

# 只监听 NBA
python main.py stream-trades --sport nba --rpc-url wss://polygon-mainnet.g.alchemy.com/v2/YOUR_KEY

# 自定义推送端口和回补深度
python main.py stream-trades --rpc-url wss://... --ws-port 9000 --backfill 500
```

### 参数说明

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--rpc-url` | 是 | — | Polygon WebSocket RPC URL |
| `--sport` | 否 | 全部体育 | 运动类型过滤 |
| `--ws-port` | 否 | 8765 | 本地 WebSocket 推送端口 |
| `--backfill` | 否 | 100 | 启动时回补的区块数 |

### 工作流程

```
启动
  │
  ├── 1. 从数据库构建 token_id → (condition_id, event_slug, outcome) 映射
  │
  ├── 2. 连接 Polygon WebSocket RPC
  │
  ├── 3. 回补最近 N 个区块的 OrderFilled 事件
  │       eth_getLogs → 解析 → 写入 SQLite
  │
  ├── 4. eth_subscribe("newHeads") 订阅新区块
  │       每个新区块到达时:
  │       ├── eth_getLogs 获取该区块的 OrderFilled 事件
  │       ├── 解析事件 → 过滤匹配的体育 token
  │       ├── 写入 SQLite (与 Data API 数据共表)
  │       └── 通过本地 WebSocket 推送 JSON
  │
  └── 5. 断线自动重连 (指数退避: 1s→2s→4s→...→60s)
```

### 链上合约

| 合约 | 地址 | 说明 |
|------|------|------|
| CTF Exchange | `0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e` | 标准条件 Token 交易 |
| NegRisk CTF Exchange | `0xc5d563a36ae78145c45a50134d48a1215220f80a` | 负风险条件 Token 交易 |
| OrderFilled 事件签名 | `0xd0a08e8c493f9c...` | 每笔撮合成交触发 |

### OrderFilled 事件解析

```
OrderFilled(
    bytes32 indexed orderHash,     ← 订单哈希
    address indexed maker,         ← 挂单方
    address indexed taker,         ← 吃单方
    uint256 makerAssetId,          ← 挂单方资产 ID (0=USDC, 非0=outcome token)
    uint256 takerAssetId,          ← 吃单方资产 ID
    uint256 makerAmountFilled,     ← 挂单方成交量 (6 位小数)
    uint256 takerAmountFilled,     ← 吃单方成交量
    uint256 fee                    ← 手续费
)

判断方向:
  makerAssetId == 0 → BUY  (挂单方提供 USDC, 买入 outcome token)
  takerAssetId == 0 → SELL (挂单方提供 token, 卖出换 USDC)

价格计算:
  price = usdc_amount / token_amount
```

### 本地 WebSocket 推送

启动后在 `ws://localhost:8765` 广播 JSON 格式的实时交易事件：

```json
{
  "event_slug": "nba-bos-phx-2026-02-24",
  "condition_id": "0xd97ee697...",
  "trade_timestamp": 1771929646,
  "side": "BUY",
  "outcome": "Suns",
  "size": 8.867924,
  "price": 0.47,
  "proxy_wallet": "0xe05d8288...",
  "transaction_hash": "0x2aab5d56...",
  "timestamp_ms": 1771929647635,
  "server_received_ms": 1771930210882
}
```

可用 Python 快速接收：

```python
import asyncio, websockets, json

async def listen():
    async with websockets.connect("ws://localhost:8765") as ws:
        async for msg in ws:
            trade = json.loads(msg)
            print(f"{trade['side']} {trade['outcome']} ${trade['size']:.2f} @ {trade['price']}")

asyncio.run(listen())
```

### 毫秒级时间戳

链上实时监听模式为每笔交易生成两个高精度时间戳：

| 字段 | 计算方式 | 说明 |
|------|----------|------|
| `timestamp_ms` | `block_timestamp × 1000 + log_index` | 区块内单调递增的伪毫秒戳 |
| `server_received_ms` | `int(time.time() * 1000)` | 服务器收到区块的本地时间（仅实时模式） |

**`timestamp_ms` 示例：**

```
block_timestamp = 1771929646  (2026-02-24 10:40:46 UTC)
log_index       = 635         (该区块内第 636 条事件)
timestamp_ms    = 1771929647635
trade_time_ms   = "2026-02-24 10:40:47.635 UTC"
```

同一区块内的不同交易通过 `log_index` 保证顺序：
```
trade 1: timestamp_ms = 1771929647635  (log_index=635)
trade 2: timestamp_ms = 1771929647637  (log_index=637)
trade 3: timestamp_ms = 1771929648216  (log_index=1216)
```

**CSV 导出时**，末尾追加两列：`timestamp_ms` 和 `trade_time_ms`（可读格式），原有列顺序不变。Data API 拉取的数据两列为空。

---

### 获取比赛结果

```bash
python main.py results                          # 从已采集的数据中提取结果
python main.py results --live                   # WebSocket 实时比分推送
```

### 导出数据

```bash
python main.py export                           # 导出 CSV
python main.py export --format json             # 导出 JSON（含完整 order book 明细）
```

导出文件位于 `data/` 目录：
```
data/
├── events.csv          — 所有事件
├── markets.csv         — 所有市场/盘口
├── trades.csv          — 所有成交记录
├── orderbooks.csv      — 订单簿摘要
├── orderbooks_full.json — 订单簿完整数据（含 bids/asks 明细）
└── results.csv         — 比赛结果
```

### 完整采集流程

```bash
python main.py all --sport nba                  # NBA 全量采集
python main.py all --sport nba --active-only    # 只采集 NBA 活跃事件
python main.py all                              # 所有体育赛事（量很大，慎用）
```

### 查看数据库摘要

```bash
python main.py summary
```

---

## 数据结构与字段说明

### Polymarket 体育赛事的层级结构

```
Sport (运动)                    ← /sports 端点获取
  └── Event (事件/比赛)         ← /events 端点获取
        ├── slug: "nba-lal-bos-2026-02-24"
        ├── title: "Lakers vs. Celtics"
        ├── score: "110-105"
        ├── game_status: "Final"
        └── Markets[] (盘口)
              ├── Market 1: "Who wins?" (moneyline)
              │     ├── condition_id: "0xabc..."
              │     ├── outcomes: ["Lakers", "Celtics"]
              │     └── clob_token_ids: ["token_lakers", "token_celtics"]
              │           ├── token_lakers → Order Book (bids + asks)
              │           └── token_celtics → Order Book (bids + asks)
              ├── Market 2: "Total > 210.5?" (totals)
              │     ├── outcomes: ["Over", "Under"]
              │     └── clob_token_ids: ["token_over", "token_under"]
              └── Market 3: "Lakers -5.5?" (spreads)
                    ├── outcomes: ["Yes", "No"]
                    └── clob_token_ids: ["token_yes", "token_no"]
```

### 盘口类型 (sportsMarketType)

| 类型 | 含义 | 示例 |
|------|------|------|
| `moneyline` | 胜负盘 | "Who wins?" |
| `spreads` | 让分盘 | "Lakers -5.5?" |
| `totals` | 大小盘 | "Total > 210.5?" |
| `team_totals` | 队伍得分 | "Lakers > 108.5?" |
| `first_half_moneyline` | 上半场胜负 | "Who leads at halftime?" |
| `first_half_spreads` | 上半场让分 | |
| `first_half_totals` | 上半场大小分 | |
| `anytime_touchdowns` | 达阵球员 (NFL) | "Will Player X score a TD?" |
| `passing_yards` | 传球码数 (NFL) | "QB > 250.5 passing yards?" |
| `points` | 球员得分 (NBA) | "LeBron > 25.5 points?" |
| `assists` | 助攻 (NBA) | |
| `rebounds` | 篮板 (NBA) | |
| `total_goals` | 总进球 (足球) | |
| `correct_score` | 比分竞猜 (足球) | "Final score 2-1?" |
| `moba_first_blood` | 一血 (电竞) | |

### 数据库表结构

| 表名 | 说明 | 记录示例 |
|------|------|----------|
| `sports` | 运动类型元数据 | 145 种运动 |
| `events` | 事件（一场比赛或一个赛季问题） | NBA 2026 Champion |
| `markets` | 市场（事件下的具体盘口） | "Will Lakers win?" |
| `orderbook_snapshots` | 订单簿快照 | bids/asks + 深度统计 |
| `trades` | 成交记录 (Data API + 链上) | 每笔买卖的价格/数量/时间/毫秒戳 |
| `game_results` | 比赛结果 | 最终比分 + 获胜方 |
| `fetch_progress` | 采集进度（断点续传用） | |

**trades 表字段：**

| 字段 | 类型 | 说明 | 来源 |
|------|------|------|------|
| `id` | INTEGER | 自增主键 | 自动 |
| `event_slug` | TEXT | 事件标识 | 两者 |
| `condition_id` | TEXT | 市场条件 ID | 两者 |
| `trade_timestamp` | INTEGER | 秒级时间戳 (Unix) | 两者 |
| `side` | TEXT | BUY / SELL | 两者 |
| `outcome` | TEXT | 预测结果标签 | 两者 |
| `size` | REAL | 成交金额 (USDC) | 两者 |
| `price` | REAL | 成交价格 (0~1) | 两者 |
| `proxy_wallet` | TEXT | 交易者钱包地址 | 两者 |
| `transaction_hash` | TEXT | Polygon 链上交易哈希 | 两者 |
| `fetched_at` | TEXT | 数据入库时间 | 两者 |
| `timestamp_ms` | INTEGER | 毫秒级时间戳 (`block_ts*1000+log_index`) | 仅链上 |
| `server_received_ms` | INTEGER | 服务器收到区块的本地时间 | 仅实时 |

---

## 技术架构

### API 体系

本项目使用 Polymarket 的三套公开 API（全部无需认证）：

```
┌──────────────────────────────────────────────────────┐
│                 Polymarket API 架构                    │
├──────────────────────────────────────────────────────┤
│                                                       │
│  Gamma API (gamma-api.polymarket.com)                 │
│  ├── /sports         → 运动类型元数据                   │
│  ├── /events         → 事件列表 + 市场数据              │
│  ├── /markets        → 单个市场查询                    │
│  └── /teams          → 队伍信息                        │
│                                                       │
│  CLOB API (clob.polymarket.com)                       │
│  ├── GET  /book      → 单个 token 的 order book       │
│  ├── POST /books     → 批量 order book（最多 500 个）   │
│  ├── /price          → 最优买/卖价                     │
│  ├── /midpoint       → 中间价                          │
│  └── /spread         → 买卖价差                        │
│                                                       │
│  Data API (data-api.polymarket.com)                   │
│  └── /trades         → 历史成交记录                     │
│                                                       │
│  WebSocket                                            │
│  ├── wss://.../ws/market  → 实时订单簿更新              │
│  └── wss://sports-api.polymarket.com/ws → 实时比分     │
│                                                       │
│  Polygon 链上 (stream-trades 模式)                     │
│  ├── eth_subscribe("newHeads") → 新区块通知            │
│  ├── eth_getLogs → OrderFilled 事件查询                │
│  ├── CTF Exchange        → 0x4bfb41d5...              │
│  └── NegRisk CTF Exchange → 0xc5d563a3...             │
│                                                       │
└──────────────────────────────────────────────────────┘
```

### 代码模块

```
polymarket-sports-data/
├── main.py                    # CLI 主入口（9 个子命令）
├── config.py                  # API 端点、速率控制、链上合约地址
├── generate_sample.py         # 样本数据生成脚本
├── requirements.txt           # 依赖：requests, websocket-client, websockets, tqdm
├── src/
│   ├── api_client.py          # HTTP 客户端（重试 + 指数退避 + 限流）
│   ├── database.py            # SQLite 存储层（7 张表，含 schema 迁移）
│   ├── models.py              # 数据模型定义
│   ├── discovery/             # 事件发现模块
│   │   ├── sports_meta.py     # 获取 145 种运动的元数据和 tag 映射
│   │   ├── events_fetcher.py  # 分页采集事件 + 断点续传
│   │   └── markets_parser.py  # 解析 markets 和 clobTokenIds
│   ├── orderbook/             # 订单簿模块
│   │   ├── rest_fetcher.py    # REST 批量快照（POST /books）
│   │   └── ws_streamer.py     # WebSocket 实时流 + 自动持久化
│   ├── realized/              # 已实现数据模块
│   │   ├── trades_fetcher.py  # 成交记录批量采集 + BUY/SELL 分拆去重
│   │   ├── chain_streamer.py  # 链上实时监听 + 本地 WS 推送 (NEW)
│   │   └── results_fetcher.py # 比赛结果提取 + 实时比分 WebSocket
│   └── export/
│       └── exporter.py        # CSV / JSON 导出（含 timestamp_ms 列）
└── data/                      # 运行时自动创建
    ├── polymarket_sports.db   # SQLite 数据库
    └── *.csv / *.json         # 导出文件
```

### 数据采集流程

```
Step 1: 体育元数据
  GET /sports → 145 种运动的 tag_id 映射
                ↓
Step 2: 事件发现
  GET /events?tag_id=745 → NBA 事件列表
  解析 event.markets[] → conditionId + clobTokenIds
                ↓
    ┌──────────┼──────────┐
    ↓          ↓          ↓
Step 3:      Step 4a:   Step 4b:
Order Book   Trades     stream-trades (链上实时)
POST /books  Data API   eth_subscribe("newHeads")
token_id →   BUY+SELL   每区块 eth_getLogs
bids+asks    分拆去重    → OrderFilled 解析
    ↓          ↓        → timestamp_ms
    │          │        → WS 推送 localhost:8765
    │          ↓          ↓
    │     ┌────┴──────────┘
    │     ↓                  两种来源共用
    │   trades 表 ←──────── 同一张 SQLite 表
    ↓     ↓
Step 5: 结果提取 + 导出 CSV/JSON
```

---

## API 限制与应对策略

| 限制 | 详情 | 应对策略 |
|------|------|----------|
| Data API offset 上限 | `offset + limit >= 4000` 返回 400 | BUY + SELL 分拆策略覆盖 ~97%；或用 `stream-trades` 覆盖 100% |
| API 限流 (429) | 请求过快会被拒绝 | 请求间隔 0.35s + 指数退避重试 |
| Gamma API 分页 | 每页最多 100 条 | 自动分页 + offset 递增 |
| Data API 每页上限 | 每次最多 1000 条 | 固定 limit=1000 |
| WebSocket 心跳 | Sports WS 需 pong 回应 | 自动处理 ping/pong |
| RPC 连接断开 | 网络波动或节点维护 | 指数退避自动重连 (1s→2s→4s→...→60s) |

### 速率控制参数（可在 config.py 中调整）

```python
REQUEST_DELAY = 0.35      # 请求间隔（秒）
MAX_RETRIES = 5           # 最大重试次数
RETRY_BACKOFF = 0.8       # 指数退避因子
BOOKS_BATCH_SIZE = 100    # 每批 order book 查询数量

# 链上监听参数
CTF_EXCHANGE = "0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e"
NEG_RISK_CTF_EXCHANGE = "0xc5d563a36ae78145c45a50134d48a1215220f80a"
ORDER_FILLED_TOPIC = "0xd0a08e8c493f9c94f29311604c9de1b4e8c8d4c06bd0c789af57f2d65bfec0f6"
CHAIN_WS_PORT = 8765      # 本地 WebSocket 推送端口
CHAIN_BACKFILL_BLOCKS = 100  # 启动时回补的区块数
```

---

## 常见问题

### Q: 首次完整采集需要多长时间？

- **事件发现**：1-5 分钟（取决于运动种类数量）
- **订单簿快照**：10-30 秒（批量查询，很快）
- **成交记录**：数小时到数天（取决于市场数量和交易活跃度）
- 支持断点续传，可以分多次运行

### Q: 为什么 Data API 覆盖率不是 100%？

Data API 的 offset 上限是硬限制。BUY+SELL 分拆策略可覆盖约 97%。**如需 100% 覆盖，使用链上实时监听模式**：

```bash
python main.py stream-trades --rpc-url wss://polygon-mainnet.g.alchemy.com/v2/YOUR_KEY
```

该模式直接从 Polygon 链上读取所有 `OrderFilled` 事件，不受 API 分页限制。

### Q: stream-trades 需要什么准备？

需要一个支持 WebSocket 的 Polygon RPC URL。推荐：
- [Alchemy](https://www.alchemy.com/) — `wss://polygon-mainnet.g.alchemy.com/v2/YOUR_KEY`
- [Infura](https://infura.io/) — `wss://polygon-mainnet.infura.io/ws/v3/YOUR_KEY`
- [QuickNode](https://www.quicknode.com/)
- 公共 RPC: `wss://polygon-bor-rpc.publicnode.com` (有速率限制)

### Q: 两种 trades 模式可以同时使用吗？

可以。批量拉取 (`trades`) 和实时监听 (`stream-trades`) 的数据写入同一张 `trades` 表，通过 `transaction_hash` 自动去重（`INSERT OR IGNORE`）。推荐工作流：

```bash
# 先批量拉取历史数据
python main.py trades --sport nba

# 然后启动实时监听获取新交易
python main.py stream-trades --sport nba --rpc-url wss://...
```

### Q: timestamp_ms 是真正的毫秒时间戳吗？

不完全是。Polygon 区块时间戳精度为秒级。`timestamp_ms = block_timestamp × 1000 + log_index` 是一个**伪毫秒戳**，保证同一区块内不同交易的单调递增顺序。跨区块的精度仍为秒级。如需实际到达时间，参考 `server_received_ms`（服务器本地时间，毫秒精度）。

### Q: 已关闭的市场能获取 Order Book 吗？

不能。已结算市场的订单簿为空。但可以通过历史成交记录（trades）还原当时的交易活动。

### Q: 能获取到所有挂单的单独订单明细吗？

CLOB API 返回的是 **聚合后** 的 order book：同一价格的所有订单 size 合并为一个数字。无法区分是 1 个人挂了 $10,000 还是 10 个人各挂了 $1,000。这是 Polymarket 的 API 设计，与传统交易所的 Level 2 数据类似。

### Q: 如何只采集特定的运动？

```bash
# 单个运动
python main.py all --sport nba

# 多个运动
python main.py discover --sport nba,nfl,epl

# 查看所有可用运动缩写
python main.py sports
```

### Q: 数据存在哪里？

数据存储在 `data/polymarket_sports.db`（SQLite 数据库）。可以用任何 SQLite 工具直接查看，或使用 `export` 命令导出 CSV/JSON。

### Q: 如何做增量更新？

```bash
# 只采集新增的事件
python main.py discover --sport nba

# 只采集还没有 trades 的市场
python main.py trades --sport nba
```

脚本会自动跳过已采集的数据。

---

## 依赖

| 包名 | 版本 | 用途 |
|------|------|------|
| `requests` | ≥2.31.0 | HTTP 请求（REST API） |
| `websocket-client` | ≥1.7.0 | WebSocket 连接（订单簿/比分流） |
| `websockets` | ≥10.0 | 链上 RPC + 本地推送（asyncio） |
| `tqdm` | ≥4.66.0 | 进度条 |

- 批量拉取模式无需 API Key
- 链上实时监听模式需要 Polygon WebSocket RPC URL

---

## 免责声明

本项目仅用于数据研究和学习目的，不构成任何投资建议。Polymarket 上的预测市场涉及真实资金交易，请自行评估风险。
