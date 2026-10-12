"""Fixed-window rate limiting with Redis (shared across workers) or in-process memory (dev/test)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Protocol

import redis

logger = logging.getLogger("freelancer_os.ratelimit")


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after: int = 0


class RateLimiter(Protocol):
    def hit(self, key: str, limit: int, window_seconds: int) -> Decision: ...

    def reset(self, key: str) -> None: ...


class MemoryRateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = {}

    def hit(self, key: str, limit: int, window_seconds: int) -> Decision:
        now = time.monotonic()
        window = [t for t in self._hits.get(key, []) if now - t < window_seconds]
        if len(window) >= limit:
            self._hits[key] = window
            return Decision(False, max(1, int(window_seconds - (now - window[0])) + 1))
        window.append(now)
        self._hits[key] = window
        return Decision(True)

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)

    def clear(self) -> None:
        self._hits.clear()


class RedisRateLimiter:
    def __init__(self, url: str) -> None:
        self._client = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)

    def hit(self, key: str, limit: int, window_seconds: int) -> Decision:
        redis_key = f"rl:{key}"
        try:
            count = int(self._client.incr(redis_key))
            if count == 1:
                self._client.expire(redis_key, window_seconds)
            if count > limit:
                ttl = int(self._client.ttl(redis_key))
                return Decision(False, max(1, ttl))
            return Decision(True)
        except redis.RedisError:
            # Availability over strictness: per-account lockout still protects passwords, and the
            # failure is logged so operators notice. Documented in docs/SECURITY.md.
            logger.warning("rate limiter unavailable; allowing request")
            return Decision(True)

    def reset(self, key: str) -> None:
        try:
            self._client.delete(f"rl:{key}")
        except redis.RedisError:
            logger.warning("rate limiter unavailable; could not reset key")
