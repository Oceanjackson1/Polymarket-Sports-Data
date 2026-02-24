# Polymarket 体育赛事预测市场 — 数据采集方案

## 一、调研总结

### 1.1 Polymarket API 架构

Polymarket 提供三套独立的 API，分别负责不同的数据层：

| API | Base URL | 用途 | 认证 |
|-----|----------|------|------|
| **Gamma API** | `https://gamma-api.polymarket.com` | 事件/市场发现、体育元数据、标签系统 | 无需 |
| **CLOB API** | `https://clob.polymarket.com` | 实时订单簿（bids/asks）、价格、价差 | 读取无需 |
| **Data API** | `https://data-api.polymarket.com` | 历史成交记录（已实现交易） | 无需 |

此外还有两个 WebSocket 端点：
- **Market Channel**: `wss://ws-subscriptions-clob.polymarket.com/ws/market` — 实时订单簿更新
- **Sports Channel**: `wss://sports-api.polymarket.com/ws` — 实时比分和比赛状态

### 1.2 体育赛事在 Polymarket 的结构

```
Sports Metadata (/sports)
  └── Sport (e.g., NBA, NFL, EPL...)
        ├── tag_ids: [1, 745, 100639]   ← 用于过滤事件
        └── series: "10345"              ← 赛事系列

Event (/events?tag_id=745)              ← 一场具体比赛
  ├── id, slug, title
  ├── score, period, elapsed, live, ended  ← 体育赛事特有字段
  ├── gameStatus
  └── markets[]                          ← 一场比赛可能有多个市场
        ├── Market: "Who wins?" (moneyline)
        │     ├── conditionId          ← 用于查询 trades
        │     ├── clobTokenIds         ← 用于查询 order book
        │     ├── sportsMarketType: "moneyline"
        │     ├── teamAID, teamBID
        │     └── outcomes: ["Team A", "Team B"]
        ├── Market: "Total points > 210.5?" (totals)
        └── Market: "Spread -5.5?" (spreads)

Token (clobTokenId)                      ← 每个 outcome 对应一个 token
  ├── Order Book: bids[] + asks[]       ← CLOB API
  └── Trades: 历史成交记录               ← Data API
```

### 1.3 体育赛事覆盖范围

调研 `/sports` 端点返回的数据，Polymarket 覆盖了 **100+ 种体育/电竞赛事**，主要包括：

| 类别 | 赛事 | 专属 tag_id |
|------|------|-------------|
| **美国主流** | NFL, NBA, MLB, NHL, CFB, CBB, WNBA | 450, 745, 100381, 899, 100351, 101178, 100254 |
| **足球** | EPL, La Liga, Bundesliga, Serie A, Ligue 1, UCL, UEL, MLS... | 82, 780, 1494, 101962, 102070, 100977, 101787, 100100... |
| **板球** | IPL, ODI, T20, BBL, Test... | 101977, 102815, 102810, 102813, 102842... |
| **网球** | ATP, WTA | 101232, 102123 |
| **格斗** | UFC | (在 series 下管理) |
| **电竞** | CS2, LoL, Dota2, Valorant, MLBB... | 100780, 65, 102366, 101672, 102750... |
| **其他** | 橄榄球、乒乓球、冬奥会... | 各自独立 tag |

**通用标签**: `tag_id=1` 是所有体育赛事的公共标签。`tag_id=100639` 也在几乎所有体育赛事中出现。

### 1.4 市场类型 (sportsMarketType)

体育赛事包含多种市场类型：

| 类型 | 含义 | 示例 |
|------|------|------|
| `moneyline` | 胜负盘 | "Lakers vs Celtics — 谁赢?" |
| `spreads` | 让分盘 | "Lakers -5.5" |
| `totals` | 大小盘 | "总分 > 210.5?" |
| `team_totals` | 队伍得分 | "Lakers 总分 > 108.5?" |
| `player_props` | 球员数据 | "LeBron 得分 > 25.5?" |
| `nrfi` | 首局无得分 | 棒球特有 |
| `first_half_*` | 上半场盘口 | 上半场胜负/让分/大小 |
| `anytime_touchdowns` | 达阵球员 | NFL 特有 |
| 电竞类型 | 首血、首塔等 | `moba_first_blood`, `shooter_rounds_total` 等 |

### 1.5 Order Book 获取方式

#### REST API（快照）
```
GET https://clob.polymarket.com/book?token_id={TOKEN_ID}
```
返回结构：
```json
{
  "market": "0xbd31dc8a...",      // conditionId
  "asset_id": "52114319...",       // token_id
  "bids": [{"price": "0.48", "size": "1000"}, ...],
  "asks": [{"price": "0.52", "size": "800"}, ...],
  "tick_size": "0.01",
  "min_order_size": "5",
  "neg_risk": false,
  "last_trade_price": "0.50"
}
```
- 批量：`POST /books` 支持最多 500 个 token 同时查询
- 无需认证

#### WebSocket（实时增量）
```
wss://ws-subscriptions-clob.polymarket.com/ws/market
```
- 订阅 `assets_ids` 后，接收 `book`、`price_change`、`last_trade_price`、`best_bid_ask` 等事件
- 支持动态 `subscribe`/`unsubscribe`
- 无需认证

### 1.6 Realized Data（已实现交易）获取方式

#### 方式 A：Data API（纯 API，无需 Key）
```
GET https://data-api.polymarket.com/trades?market={conditionId}&limit=1000
```
- 分页上限：`offset + limit < 4000`（硬限制）
- BUY + SELL 分拆策略可覆盖 ~97%（约 8000 条上限）
- 也可通过 `eventId` 参数查询一个事件下所有市场的交易

#### 方式 B：链上数据（100% 完整，需要 RPC）
- Polygon 链上的 CTF Exchange 合约的 `OrderFilled` 事件
- 通过 Subgraph 查询：`https://api.goldsky.com/.../orderbook-subgraph/0.0.1/gn`
- 完全准确，但需要 RPC 节点或 Subgraph 基础设施

#### 方式 C：比赛结果（体育特有）
- WebSocket：`wss://sports-api.polymarket.com/ws` 推送实时比分
- Event 对象中的 `score`、`period`、`ended`、`outcomePrices` 字段包含结果信息
- `outcomePrices: ["1","0"]` 表示第一个 outcome 胜出

### 1.7 与参考仓库的对比

| 维度 | 参考仓库 (BTC 5m) | 本项目 (Sports) |
|------|-------------------|-----------------|
| 事件发现 | `tag_id=102892` (5M标签) + slug前缀过滤 | `tag_id` 按运动类型过滤 或 `tag_slug=sports` |
| 事件数量 | 数万个（每5分钟一个） | 数千个（取决于赛季和运动种类） |
| 市场结构 | 每个事件1个市场（Up/Down） | 每个事件多个市场（moneyline/spreads/totals/props） |
| Order Book | 参考仓库未覆盖 | **本项目核心需求** |
| Realized Data | 成交历史（trades） | 成交历史 + 比赛结果（score） |
| 数据量 | 极大（高频5分钟） | 中等（每天几十到上百场比赛） |

---

## 二、代码架构方案

### 2.1 目录结构

```
polymarket-sports-data/
├── main.py                         # 主入口（CLI）
├── requirements.txt                # 依赖
├── config.py                       # 配置常量
├── PLAN.md                         # 本文件
│
├── src/
│   ├── __init__.py
│   ├── api_client.py               # HTTP 客户端（重试、限流）
│   ├── models.py                   # 数据模型定义
│   ├── database.py                 # SQLite 存储层
│   │
│   ├── discovery/                  # 事件/市场发现模块
│   │   ├── __init__.py
│   │   ├── sports_meta.py          # 获取体育元数据（运动列表、tag映射）
│   │   ├── events_fetcher.py       # 批量获取体育事件
│   │   └── markets_parser.py       # 解析事件下的市场和 tokenId
│   │
│   ├── orderbook/                  # 订单簿模块
│   │   ├── __init__.py
│   │   ├── rest_fetcher.py         # REST 快照获取（批量 /books）
│   │   ├── ws_streamer.py          # WebSocket 实时订单簿流
│   │   └── snapshot_manager.py     # 订单簿快照管理（定时存储）
│   │
│   ├── realized/                   # 已实现数据模块
│   │   ├── __init__.py
│   │   ├── trades_fetcher.py       # Data API 成交记录采集
│   │   ├── results_fetcher.py      # 比赛结果采集（outcome resolution）
│   │   └── onchain_fetcher.py      # 链上数据采集（可选，100%覆盖）
│   │
│   └── export/                     # 数据导出模块
│       ├── __init__.py
│       └── exporter.py             # CSV/JSON 导出
│
└── data/                           # 运行时自动创建
    ├── polymarket_sports.db        # SQLite 数据库
    ├── orderbook_snapshots/        # 订单簿快照（JSON）
    ├── events.csv
    ├── trades.csv
    └── orderbooks.csv
```

### 2.2 核心模块设计

#### 模块 1: 体育事件发现 (`discovery/`)

**目的**: 发现所有体育类预测事件及其下属市场，提取 `conditionId` 和 `clobTokenIds`。

```
流程:
1. GET /sports → 获取所有运动的 tag_ids
2. 对每个运动（或指定运动），用 tag_id 过滤:
   GET /events?tag_id={sport_tag}&active=true&closed=false&limit=100&offset=N
3. 解析每个 event 中的 markets[]，提取:
   - conditionId（用于 Data API 查询 trades）
   - clobTokenIds（用于 CLOB API 查询 order book）
   - sportsMarketType（moneyline/spreads/totals...）
   - outcomes（"Team A"/"Team B"）
   - gameId, teamAID, teamBID
4. 存入 SQLite
```

**关键设计决策**:
- 支持按运动类型过滤（e.g., 只采集 NBA+NFL）
- 支持采集 `active` 和 `closed` 事件（历史+当前）
- 分页遍历，支持断点续传

#### 模块 2: 订单簿采集 (`orderbook/`)

**目的**: 获取每个市场中每个 token 的完整订单簿（所有挂单价位和数量）。

##### 2a. REST 快照模式

```
流程:
1. 从数据库读取所有 active 市场的 clobTokenIds
2. 批量请求:
   POST https://clob.polymarket.com/books
   Body: [{"token_id": "TOKEN_1"}, {"token_id": "TOKEN_2"}, ...]
   每批最多 500 个 token
3. 解析返回的 bids[] 和 asks[]
4. 存入 SQLite 和/或 JSON 快照文件
```

**注意事项**:
- CLOB API 返回的是**聚合后的价位**（同一价格的所有订单 size 已合并）
- 这是"full order book"的标准含义：所有价位的 bid/ask 深度
- 只有 active 市场才有有效的 order book
- 建议定时轮询（如每 5-30 秒）来构建时间序列

##### 2b. WebSocket 实时模式

```
流程:
1. 连接 wss://ws-subscriptions-clob.polymarket.com/ws/market
2. 发送订阅消息: {"assets_ids": [...], "type": "market", "custom_feature_enabled": true}
3. 接收事件:
   - "book": 完整订单簿快照（首次订阅 + 每次成交后）
   - "price_change": 单个价位变更（新增挂单/撤单）
   - "last_trade_price": 成交事件
   - "best_bid_ask": 最优买卖价变更
4. 维护本地订单簿副本，定期持久化
```

**注意事项**:
- 支持动态 subscribe/unsubscribe（比赛开始时订阅，结束时取消）
- 需要处理心跳（如有要求）
- 建议每个 WebSocket 连接最多订阅 ~100 个 token，超出则多连接

#### 模块 3: 已实现数据采集 (`realized/`)

##### 3a. 成交记录（trades）

```
流程:
1. 从数据库读取所有市场的 conditionId
2. 对每个 conditionId:
   GET /trades?market={conditionId}&limit=1000&offset=0
   GET /trades?market={conditionId}&limit=1000&offset=1000
   ... 直到无数据或达到 offset 上限
3. 如果触及 4000 条上限:
   用 side=BUY 和 side=SELL 分拆请求，分别最多 4000 条
   合并去重（基于 transactionHash + timestamp + size + side）
4. 存入 SQLite
```

##### 3b. 比赛结果

```
流程:
1. 对已关闭的事件:
   读取 event.outcomePrices → ["1","0"] 表示第一个 outcome 胜出
   读取 event.score, event.period → 最终比分
2. 对进行中的比赛（实时）:
   连接 wss://sports-api.polymarket.com/ws
   接收实时比分推送
3. 存入 SQLite
```

##### 3c. 链上数据（可选，100% 完整覆盖）

```
流程:
1. 从 market 获取 clobTokenIds
2. 查询 Polygon 上 CTF Exchange 合约的 OrderFilled 事件
   - 过滤 makerAssetId 或 takerAssetId 匹配目标 token
3. 解析事件字段还原: side, outcome, size, price, notional, fee
4. 或通过 Goldsky Subgraph 查询:
   POST https://api.goldsky.com/.../orderbook-subgraph/0.0.1/gn
   Query: { orderFilledEvents(where: {market: "conditionId"}) { ... } }
```

### 2.3 数据库 Schema

```sql
-- 运动类型表
CREATE TABLE sports (
    sport         TEXT PRIMARY KEY,   -- e.g., "nba", "nfl"
    tag_ids       TEXT,               -- 逗号分隔的 tag ID
    series_id     TEXT,
    image_url     TEXT,
    resolution_url TEXT
);

-- 事件表（一场比赛）
CREATE TABLE events (
    id            INTEGER PRIMARY KEY,
    slug          TEXT UNIQUE,
    title         TEXT,
    sport         TEXT,               -- 关联到 sports 表
    start_time    TEXT,
    end_time      TEXT,
    game_id       TEXT,               -- 体育赛事 ID
    game_status   TEXT,               -- Scheduled/InProgress/Final...
    score         TEXT,               -- 最终比分
    volume        REAL,
    active        INTEGER,
    closed        INTEGER,
    neg_risk      INTEGER,
    polymarket_url TEXT,
    fetched_at    TEXT,
    FOREIGN KEY (sport) REFERENCES sports(sport)
);

-- 市场表（一个事件下的某个盘口）
CREATE TABLE markets (
    id               TEXT PRIMARY KEY,  -- market ID
    event_id         INTEGER,
    condition_id     TEXT UNIQUE,
    slug             TEXT,
    question         TEXT,              -- "Will Lakers win?"
    sports_market_type TEXT,            -- moneyline/spreads/totals...
    line             REAL,              -- 盘口线 (e.g., -5.5)
    outcomes         TEXT,              -- JSON: ["Lakers","Celtics"]
    outcome_prices   TEXT,              -- JSON: ["0.55","0.45"]
    clob_token_ids   TEXT,              -- JSON: ["token_yes","token_no"]
    team_a_id        TEXT,
    team_b_id        TEXT,
    volume           REAL,
    closed           INTEGER,
    accepting_orders INTEGER,
    tick_size        REAL,
    fetched_at       TEXT,
    FOREIGN KEY (event_id) REFERENCES events(id)
);

-- 订单簿快照表
CREATE TABLE orderbook_snapshots (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id       TEXT,               -- clobTokenId
    condition_id   TEXT,               -- 关联市场
    snapshot_time  TEXT,               -- ISO 8601
    bids_json      TEXT,               -- JSON: [{"price":"0.48","size":"1000"}, ...]
    asks_json      TEXT,               -- JSON: [{"price":"0.52","size":"800"}, ...]
    best_bid       REAL,
    best_ask       REAL,
    spread         REAL,
    mid_price      REAL,
    last_trade_price REAL,
    tick_size      TEXT,
    total_bid_depth REAL,              -- 买盘总深度（计算字段）
    total_ask_depth REAL               -- 卖盘总深度（计算字段）
);

-- 成交记录表
CREATE TABLE trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_slug      TEXT,
    condition_id    TEXT,
    trade_timestamp INTEGER,           -- Unix 时间戳
    side            TEXT,              -- BUY/SELL
    outcome         TEXT,              -- "Lakers"/"Celtics"
    size            REAL,              -- 成交额 USDC
    price           REAL,              -- 成交价 (0~1)
    proxy_wallet    TEXT,
    transaction_hash TEXT,
    fetched_at      TEXT,
    UNIQUE(transaction_hash, trade_timestamp, size, side, proxy_wallet)
);

-- 比赛结果表
CREATE TABLE game_results (
    event_id        INTEGER PRIMARY KEY,
    game_id         TEXT,
    sport           TEXT,
    home_team       TEXT,
    away_team       TEXT,
    final_score     TEXT,               -- "110-105"
    period          TEXT,               -- "FT", "FT OT"
    status          TEXT,               -- Final, F/OT...
    winning_outcome TEXT,               -- 哪个 outcome 胜出
    resolved_at     TEXT,
    FOREIGN KEY (event_id) REFERENCES events(id)
);

-- 采集进度表（断点续传）
CREATE TABLE fetch_progress (
    task_name       TEXT PRIMARY KEY,
    last_offset     INTEGER DEFAULT 0,
    last_event_slug TEXT,
    updated_at      TEXT
);
```

### 2.4 CLI 入口设计

```bash
# 完整采集流程（发现 → 订单簿 → 成交）
python main.py all

# 分步执行
python main.py discover                    # 发现所有体育事件和市场
python main.py discover --sport nba,nfl    # 只发现 NBA 和 NFL
python main.py discover --active-only      # 只发现当前活跃事件

python main.py orderbook                   # 获取所有活跃市场的订单簿快照
python main.py orderbook --sport nba       # 只获取 NBA 的订单簿
python main.py orderbook --stream          # WebSocket 实时流模式

python main.py trades                      # 获取所有市场的成交记录
python main.py trades --sport nba          # 只获取 NBA 的成交
python main.py trades --onchain            # 使用链上模式（100%覆盖）

python main.py results                     # 获取比赛结果
python main.py results --live              # WebSocket 实时比分

python main.py export                      # 导出 CSV
python main.py export --format json        # 导出 JSON
python main.py summary                     # 数据库摘要
```

---

## 三、关键技术决策

### 3.1 Order Book: REST 轮询 vs WebSocket

| 维度 | REST 轮询 | WebSocket |
|------|-----------|-----------|
| 实现复杂度 | 低 | 中（连接管理、重连） |
| 数据延迟 | 取决于轮询频率 | 毫秒级 |
| API 负担 | 较高（重复请求） | 低（增量更新） |
| 适用场景 | 历史快照、低频分析 | 实时交易、做市 |
| 数据完整性 | 每次都是完整快照 | 需维护本地状态 |

**建议**: 先实现 REST 轮询模式（简单可靠），再扩展 WebSocket（实时需求时）。

### 3.2 Realized Data: API vs On-chain

| 维度 | Data API | 链上 (On-chain) |
|------|----------|-----------------|
| 覆盖率 | ~97%（BUY+SELL 分拆后） | 100% |
| 实现复杂度 | 低 | 高（需理解合约、ABI、Subgraph） |
| 依赖 | 无 | RPC 节点或 Goldsky Subgraph |
| 速度 | 快 | 慢（需要索引大量区块） |
| 适用场景 | 大多数分析 | 严格审计、研究 |

**建议**: 默认使用 Data API，链上模式作为可选补充。

### 3.3 体育事件过滤策略

两种策略：

**策略 A — 通用 tag 过滤（推荐）**:
```python
# 使用 tag_id=1（所有体育赛事的通用标签）
GET /events?tag_id=1&active=true&closed=false&limit=100
```
- 一次获取所有运动的事件
- 需要客户端过滤非体育事件（极少）

**策略 B — 按运动逐个采集**:
```python
# 先获取 /sports 的 tag 映射，然后逐个运动采集
for sport in sports:
    for tag_id in sport.tag_ids:
        GET /events?tag_id={tag_id}&active=true&closed=false&limit=100
```
- 精确，但请求量更多
- 适合只关注特定运动

**建议**: 先用策略 A 获取全量，再按 sport 字段/tag 做客户端过滤。

---

## 四、实现优先级和里程碑

### Phase 1: 基础架构 + 事件发现 (Day 1)
- [ ] 搭建项目结构、依赖管理
- [ ] 实现 API 客户端（重试、限流、会话管理）
- [ ] 实现体育元数据获取（`/sports` → tag 映射）
- [ ] 实现事件分页采集（Gamma API `/events`）
- [ ] 解析市场数据，提取 conditionId 和 clobTokenIds
- [ ] SQLite 数据库初始化和存储

### Phase 2: 订单簿采集 (Day 2)
- [ ] 实现 REST 订单簿快照（CLOB API `/book` 和 `/books`）
- [ ] 批量获取逻辑（每批最多 500 个 token）
- [ ] 订单簿数据持久化（SQLite + 可选 JSON 快照）
- [ ] 定时轮询模式（可配置间隔）

### Phase 3: Realized Data 采集 (Day 2-3)
- [ ] 实现成交记录采集（Data API `/trades`）
- [ ] BUY + SELL 分拆策略
- [ ] 去重逻辑
- [ ] 比赛结果提取（从 event 字段 + outcomePrices）
- [ ] 断点续传

### Phase 4: 实时流 + 导出 (Day 3-4)
- [ ] WebSocket 订单簿实时流（可选）
- [ ] WebSocket 比分推送（可选）
- [ ] CSV/JSON 数据导出
- [ ] CLI 完善
- [ ] 数据统计摘要

### Phase 5: 链上增强（可选）
- [ ] Subgraph 查询 OrderFilled 事件
- [ ] 或 Polygon RPC 直接扫描
- [ ] 与 API 数据交叉验证

---

## 五、依赖和环境

```
# requirements.txt
requests>=2.31.0          # HTTP 客户端
websocket-client>=1.7.0   # WebSocket（同步）
# 或 websockets>=12.0     # WebSocket（asyncio）
tqdm>=4.66.0              # 进度条
pandas>=2.1.0             # 数据处理（可选，导出用）
```

- Python 3.9+
- 无需 API Key
- 需要稳定的网络连接（Polymarket API 可能需要代理访问）

---

## 六、速率限制和注意事项

### 6.1 Polymarket 官方限制

| API | 限制 |
|-----|------|
| Gamma API | 未明确公开，建议 ≤ 3 req/s |
| CLOB API | 无认证: 较低限制，建议 ≤ 2 req/s |
| Data API | offset + limit < 4000（trades 接口硬限制） |
| WebSocket | 连接后持续接收，需处理 ping/pong |

### 6.2 建议的速率控制参数

```python
REQUEST_DELAY = 0.3       # 请求间隔（秒）
MAX_RETRIES = 5           # 最大重试次数
RETRY_DELAY = 2.0         # 重试间隔（指数退避）
BATCH_SIZE_BOOKS = 100    # 每批查询的 order book 数量（保守值，上限500）
TRADES_PAGE_SIZE = 1000   # Data API 每页大小
TRADES_MAX_OFFSET = 3000  # Data API offset 上限
```

### 6.3 估算数据量

以 NBA 赛季为例：
- ~1230 场常规赛 + 季后赛
- 每场比赛 ~3-10 个市场（moneyline + spreads + totals + props）
- 每个市场 2 个 token（Yes/No outcome）
- **预计**: ~7,000-25,000 个 token 需要查询 order book
- **订单簿快照**: 每个 token 约 1-5 KB → 全量一次约 25-125 MB
- **成交记录**: 取决于交易活跃度，热门比赛可能有数千条 trades

---

## 七、核心数据流图

```
┌──────────────────────────────────────────────────────────────────────┐
│                        数据采集全流程                                  │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  [Step 1] 体育元数据发现                                               │
│  GET /sports → sport→tag_id 映射表                                    │
│  ↓                                                                   │
│  [Step 2] 事件批量采集                                                 │
│  GET /events?tag_id=X&limit=100&offset=N → events[]                  │
│  ↓                                                                   │
│  [Step 3] 解析市场和 Token                                            │
│  event.markets[] → conditionId, clobTokenIds, sportsMarketType       │
│  ↓                                                                   │
│  ┌─────────────────────┬─────────────────────────────────┐           │
│  │                     │                                 │           │
│  ▼                     ▼                                 ▼           │
│  [Step 4a]           [Step 4b]                        [Step 4c]      │
│  Order Book          Trades                           Results        │
│                                                                      │
│  POST /books         GET /trades?market=X             Event fields   │
│  token_id →          conditionId →                    score, period  │
│  bids[], asks[]      side,size,price                  outcomePrices  │
│                      timestamp,txHash                                │
│  ↓                   ↓                                 ↓             │
│  orderbook_snapshots trades 表                        game_results   │
│                                                                      │
│  [可选] WebSocket    [可选] On-chain                  [可选] Sports  │
│  实时增量更新         OrderFilled                      WebSocket 比分 │
│                                                                      │
│  ↓                   ↓                                 ↓             │
│  ┌─────────────────────────────────────────────────────┐             │
│  │                   SQLite 数据库                      │             │
│  └─────────────────────────────────────────────────────┘             │
│  ↓                                                                   │
│  [Step 5] 数据导出                                                    │
│  CSV / JSON / Pandas DataFrame                                       │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 八、风险和应对

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| API 限流 (429) | 数据采集中断 | 指数退避重试 + 请求间隔控制 |
| Data API offset 上限 | 热门市场 trades 不完整 (~97%) | BUY+SELL 分拆 + 可选链上补全 |
| 网络不稳定 | 连接中断 | 断点续传 + 自动重连 |
| Order Book 只有活跃市场 | 已关闭市场无 book | 仅采集 active 市场；历史需用 trades 反推 |
| 体育赛事结构变化 | 字段新增/变更 | 容错解析 + 日志告警 |
| WebSocket 连接上限 | 无法订阅全部 token | 分批连接 + 按优先级订阅 |
