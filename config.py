"""全局配置：API 端点、分页参数、速率控制、数据库路径"""
import os

# ── API 端点 ──────────────────────────────────────────────
GAMMA_API_BASE = "https://gamma-api.polymarket.com"
CLOB_API_BASE = "https://clob.polymarket.com"
DATA_API_BASE = "https://data-api.polymarket.com"

SPORTS_URL = f"{GAMMA_API_BASE}/sports"
SPORTS_MARKET_TYPES_URL = f"{GAMMA_API_BASE}/sports/market-types"
EVENTS_URL = f"{GAMMA_API_BASE}/events"
MARKETS_URL = f"{GAMMA_API_BASE}/markets"
TEAMS_URL = f"{GAMMA_API_BASE}/teams"

BOOK_URL = f"{CLOB_API_BASE}/book"
BOOKS_URL = f"{CLOB_API_BASE}/books"

TRADES_URL = f"{DATA_API_BASE}/trades"

# ── WebSocket ─────────────────────────────────────────────
WS_MARKET_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
WS_SPORTS_URL = "wss://sports-api.polymarket.com/ws"

# ── 分页与速率控制 ────────────────────────────────────────
EVENTS_PAGE_SIZE = 100
TRADES_PAGE_SIZE = 1000
TRADES_MAX_OFFSET = 3000       # offset + limit >= 4000 → 400 error
BOOKS_BATCH_SIZE = 100         # 每批 order book 查询数量（上限 500）

REQUEST_DELAY = 0.35           # 请求间隔（秒）
MAX_RETRIES = 5
RETRY_BACKOFF = 0.8            # 指数退避因子

# ── 路径 ──────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
DB_PATH = os.path.join(DATA_DIR, "polymarket_sports.db")
SNAPSHOTS_DIR = os.path.join(DATA_DIR, "orderbook_snapshots")

# ── Polygon 链上监听 ─────────────────────────────────────
CTF_EXCHANGE = "0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e"
NEG_RISK_CTF_EXCHANGE = "0xc5d563a36ae78145c45a50134d48a1215220f80a"
ORDER_FILLED_TOPIC = "0xd0a08e8c493f9c94f29311604c9de1b4e8c8d4c06bd0c789af57f2d65bfec0f6"
CHAIN_WS_PORT = 8765
CHAIN_BACKFILL_BLOCKS = 100

# ── Polymarket 页面链接 ───────────────────────────────────
POLYMARKET_EVENT_URL = "https://polymarket.com/event/{slug}"
