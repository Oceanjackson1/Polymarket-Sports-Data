"""HTTP 客户端 — 封装 GET/POST 请求，含重试、指数退避、速率控制"""
from __future__ import annotations

import json
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import (
    GAMMA_API_BASE,
    CLOB_API_BASE,
    DATA_API_BASE,
    MAX_RETRIES,
    RETRY_BACKOFF,
    REQUEST_DELAY,
)

_last_request_time = 0.0


def _rate_limit():
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < REQUEST_DELAY:
        time.sleep(REQUEST_DELAY - elapsed)
    _last_request_time = time.time()


def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=MAX_RETRIES,
        connect=MAX_RETRIES,
        read=MAX_RETRIES,
        status=MAX_RETRIES,
        allowed_methods=["GET", "POST"],
        status_forcelist=[500, 502, 503, 504],
        backoff_factor=RETRY_BACKOFF,
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": "polymarket-sports-data/1.0",
        "Accept": "application/json",
    })
    return session


_session: requests.Session | None = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = _build_session()
    return _session


def api_get(url: str, params: dict[str, Any] | None = None, timeout: int = 30) -> Any | None:
    """GET 请求，含 429 退避和错误处理。成功返回 JSON，失败返回 None。"""
    _rate_limit()
    session = _get_session()
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, params=params, timeout=timeout)
            if resp.status_code == 429:
                wait = RETRY_BACKOFF * (2 ** attempt)
                print(f"  [429] 被限流，等待 {wait:.1f}s (尝试 {attempt}/{MAX_RETRIES})")
                time.sleep(wait)
                continue
            if resp.status_code == 400:
                return None
            resp.raise_for_status()
            return json.loads(resp.text, strict=False)
        except requests.exceptions.RequestException as exc:
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF * (2 ** attempt)
                print(f"  [ERR] {exc} — 重试 {attempt}/{MAX_RETRIES}，等待 {wait:.1f}s")
                time.sleep(wait)
            else:
                print(f"  [FAIL] 请求最终失败: {url}")
                return None
    return None


def api_post(url: str, json_body: Any, timeout: int = 30) -> Any | None:
    """POST 请求（用于批量 order book 查询等）。"""
    _rate_limit()
    session = _get_session()
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.post(url, json=json_body, timeout=timeout)
            if resp.status_code == 429:
                wait = RETRY_BACKOFF * (2 ** attempt)
                print(f"  [429] 被限流，等待 {wait:.1f}s (尝试 {attempt}/{MAX_RETRIES})")
                time.sleep(wait)
                continue
            if resp.status_code == 400:
                return None
            resp.raise_for_status()
            return json.loads(resp.text, strict=False)
        except requests.exceptions.RequestException as exc:
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF * (2 ** attempt)
                print(f"  [ERR] {exc} — 重试 {attempt}/{MAX_RETRIES}，等待 {wait:.1f}s")
                time.sleep(wait)
            else:
                print(f"  [FAIL] POST 请求最终失败: {url}")
                return None
    return None


def gamma_get(path: str, params: dict[str, Any] | None = None) -> Any | None:
    return api_get(f"{GAMMA_API_BASE}{path}", params=params)


def clob_get(path: str, params: dict[str, Any] | None = None) -> Any | None:
    return api_get(f"{CLOB_API_BASE}{path}", params=params)


def clob_post(path: str, json_body: Any) -> Any | None:
    return api_post(f"{CLOB_API_BASE}{path}", json_body)


def data_get(path: str, params: dict[str, Any] | None = None) -> Any | None:
    return api_get(f"{DATA_API_BASE}{path}", params=params)
