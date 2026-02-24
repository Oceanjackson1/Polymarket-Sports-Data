# Polymarket 体育赛事预测市场 — 数据采集工具

从 [Polymarket](https://polymarket.com) 采集体育类预测事件的 **Full Order Book（完整订单簿）** 和 **Realized Data（已实现数据）**。

支持 145 种体育/电竞赛事（NBA、NFL、EPL、UFC、CS2 等），纯 Python 实现，**无需 API Key**。

---

## 目录

- [核心概念定义](#核心概念定义)
- [项目能力总结](#项目能力总结)
- [快速开始](#快速开始)
- [使用方式](#使用方式)
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
┌─────────────────┬────────────────────────────────────────┐
│ 字段             │ 值                                      │
├─────────────────┼────────────────────────────────────────┤
│ side            │ BUY                                     │
│ outcome         │ Lakers                                  │
│ price           │ 0.55                                    │
│ size            │ 100.00 USDC                             │
│ timestamp       │ 2026-02-24 08:30:00 UTC                 │
│ transaction_hash│ 0x3c240944c4c1a49c0c11c4ce99...         │
│ proxy_wallet    │ 0xe7f7e2d3d4d0e164239f3cc30a...         │
└─────────────────┴────────────────────────────────────────┘
```

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
| Data API | `GET https://data-api.polymarket.com/trades` | ~97% | 纯 API，无需认证，使用 BUY+SELL 分拆策略 |
| 链上回放 | Polygon CTF Exchange 的 `OrderFilled` 事件 | 100% | 需要 RPC 节点，适合严格审计 |
| Subgraph | Goldsky GraphQL | 100% | 索引后的链上数据，GraphQL 查询 |
| Sports WS | `wss://sports-api.polymarket.com/ws` | 实时 | 实时比分推送 |

**为什么 API 路径覆盖率是 ~97% 而不是 100%？**

Polymarket Data API 的 `/trades` 端点有分页限制：`offset + limit` 不能超过 4000。对于高交易量的市场，普通分页最多获取 4000 条。本项目使用 BUY + SELL 分拆策略：分别查询 BUY 方向和 SELL 方向的交易（各最多 4000 条），合并去重后可覆盖约 97%。剩余 3% 是因为某个方向的交易数也超过了 4000 条。

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
| 获取 Realized Trades | ✅ | Data API + BUY/SELL 分拆策略，覆盖 ~97% |
| 获取比赛结果 | ✅ | 从 event 数据提取 + Sports WebSocket 实时比分 |
| 按运动类型过滤 | ✅ | `--sport nba,nfl` 支持任意组合 |
| 断点续传 | ✅ | 所有长时间任务支持中断后恢复 |
| 数据导出 | ✅ | CSV 和 JSON 格式 |
| 链上 100% 覆盖 | 🔧 | 架构已支持，需扩展 Subgraph 查询 |

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
| `trades` | 成交记录 | 每笔买卖的价格/数量/时间 |
| `game_results` | 比赛结果 | 最终比分 + 获胜方 |
| `fetch_progress` | 采集进度（断点续传用） | |

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
└──────────────────────────────────────────────────────┘
```

### 代码模块

```
polymarket-sports-data/
├── main.py                    # CLI 主入口（8 个子命令）
├── config.py                  # API 端点、速率控制参数
├── generate_sample.py         # 样本数据生成脚本
├── requirements.txt           # 依赖：requests, websocket-client, tqdm
├── src/
│   ├── api_client.py          # HTTP 客户端（重试 + 指数退避 + 限流）
│   ├── database.py            # SQLite 存储层（7 张表）
│   ├── models.py              # 数据模型定义
│   ├── discovery/             # 事件发现模块
│   │   ├── sports_meta.py     # 获取 145 种运动的元数据和 tag 映射
│   │   ├── events_fetcher.py  # 分页采集事件 + 断点续传
│   │   └── markets_parser.py  # 解析 markets 和 clobTokenIds
│   ├── orderbook/             # 订单簿模块
│   │   ├── rest_fetcher.py    # REST 批量快照（POST /books）
│   │   └── ws_streamer.py     # WebSocket 实时流 + 自动持久化
│   ├── realized/              # 已实现数据模块
│   │   ├── trades_fetcher.py  # 成交记录采集 + BUY/SELL 分拆去重
│   │   └── results_fetcher.py # 比赛结果提取 + 实时比分 WebSocket
│   └── export/
│       └── exporter.py        # CSV / JSON 导出
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
          ┌─────┴─────┐
          ↓           ↓
Step 3: Order Book  Step 4: Trades
  POST /books         GET /trades?market=conditionId
  token_id →          BUY + SELL 分拆策略
  bids[] + asks[]     合并去重
          ↓           ↓
          └─────┬─────┘
                ↓
Step 5: 结果提取 + 导出 CSV/JSON
```

---

## API 限制与应对策略

| 限制 | 详情 | 应对策略 |
|------|------|----------|
| Data API offset 上限 | `offset + limit >= 4000` 返回 400 | BUY + SELL 分拆策略，覆盖 ~97% |
| API 限流 (429) | 请求过快会被拒绝 | 请求间隔 0.35s + 指数退避重试 |
| Gamma API 分页 | 每页最多 100 条 | 自动分页 + offset 递增 |
| Data API 每页上限 | 每次最多 1000 条 | 固定 limit=1000 |
| WebSocket 心跳 | Sports WS 需 pong 回应 | 自动处理 ping/pong |

### 速率控制参数（可在 config.py 中调整）

```python
REQUEST_DELAY = 0.35      # 请求间隔（秒）
MAX_RETRIES = 5           # 最大重试次数
RETRY_BACKOFF = 0.8       # 指数退避因子
BOOKS_BATCH_SIZE = 100    # 每批 order book 查询数量
```

---

## 常见问题

### Q: 首次完整采集需要多长时间？

- **事件发现**：1-5 分钟（取决于运动种类数量）
- **订单簿快照**：10-30 秒（批量查询，很快）
- **成交记录**：数小时到数天（取决于市场数量和交易活跃度）
- 支持断点续传，可以分多次运行

### Q: 为什么 Realized Data 覆盖率不是 100%？

Data API 的 offset 上限是硬限制。BUY+SELL 分拆策略可覆盖约 97%。如需 100%，可以：
1. 使用 Goldsky Subgraph 查询链上 OrderFilled 事件
2. 直接扫描 Polygon 链上 CTF Exchange 合约

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
| `requests` | ≥2.31.0 | HTTP 请求 |
| `websocket-client` | ≥1.7.0 | WebSocket 连接 |
| `tqdm` | ≥4.66.0 | 进度条 |

无需 API Key，无需链上基础设施。

---

## 免责声明

本项目仅用于数据研究和学习目的，不构成任何投资建议。Polymarket 上的预测市场涉及真实资金交易，请自行评估风险。
