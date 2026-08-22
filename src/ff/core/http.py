"""A small cached, retrying JSON-over-HTTP client.

Why this exists:
  * Sleeper asks callers to stay under 1000 req/min and to fetch the ~15MB
    players file at most once a day. A disk cache with per-endpoint TTLs makes
    that automatic.
  * Both public APIs occasionally 429/5xx; urllib3's Retry handles backoff.

The cache is keyed by URL+params and stored as plain JSON under FF_HOME/cache,
so it is inspectable and trivially clearable (`rm -rf .ff/cache`).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ff.core.config import cache_dir

DEFAULT_TIMEOUT = 30  # seconds


def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=4,
        backoff_factor=0.5,  # 0.5, 1, 2, 4s between tries
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": "ff/0.1 (+https://github.com/savvides/ff)"})
    return session


_SESSION: Optional[requests.Session] = None


def _session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = _build_session()
    return _SESSION


def _cache_file(url: str, params: Optional[Dict[str, Any]]) -> Path:
    key = url + "?" + json.dumps(params or {}, sort_keys=True)
    digest = hashlib.sha256(key.encode()).hexdigest()[:24]
    return cache_dir() / f"{digest}.json"


def _fresh(path: Path, ttl: Optional[float]) -> bool:
    if not path.exists():
        return False
    if ttl is None:  # cache forever once written
        return True
    return (time.time() - path.stat().st_mtime) < ttl


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temp file + os.replace so a crash mid-write never leaves a
    truncated/corrupt cache entry behind."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def get_json(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    ttl: Optional[float] = 3600.0,
    timeout: int = DEFAULT_TIMEOUT,
    use_cache: bool = True,
) -> Any:
    """GET `url` and return parsed JSON, served from disk cache when fresh.

    ttl: seconds the cached copy stays valid. None = never expires until cleared.
         Pass ttl=0 / use_cache=False to force a live fetch.
    """
    cache_path = _cache_file(url, params)
    # Delegate freshness entirely to _fresh: it returns True for ttl=None
    # (cache forever) and False for ttl=0 (force live). Guarding on `and ttl`
    # here would wrongly skip the cache when ttl is None.
    if use_cache and _fresh(cache_path, ttl):
        try:
            return json.loads(cache_path.read_text())
        except (ValueError, OSError):
            # A corrupt/unreadable cache entry must not surface as an error
            # (it would be misreported as a bad config). Ignore it and refetch.
            pass

    resp = _session().get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    if use_cache:
        _atomic_write(cache_path, json.dumps(data))
    return data
