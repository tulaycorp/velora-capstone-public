from __future__ import annotations

import time
import uuid

import redis
from redis.exceptions import RedisError

from app.core.config import settings

_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local member = ARGV[3]

local time_parts = redis.call('TIME')
local now_ms = (tonumber(time_parts[1]) * 1000) + math.floor(tonumber(time_parts[2]) / 1000)
local cutoff = now_ms - window_ms

redis.call('ZREMRANGEBYSCORE', key, 0, cutoff)

local current = redis.call('ZCARD', key)
if current < limit then
  redis.call('ZADD', key, now_ms, member)
  redis.call('PEXPIRE', key, window_ms)
  return {1, 0}
end

local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
local oldest_ms = tonumber(oldest[2]) or now_ms
local wait_ms = oldest_ms + window_ms - now_ms
if wait_ms < 0 then
  wait_ms = 0
end
return {0, wait_ms}
"""

_MULTI_KEY_SLIDING_WINDOW_LUA = """
local limit = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local member = ARGV[3]

local time_parts = redis.call('TIME')
local now_ms = (tonumber(time_parts[1]) * 1000) + math.floor(tonumber(time_parts[2]) / 1000)
local cutoff = now_ms - window_ms
local max_wait_ms = 0

for _, key in ipairs(KEYS) do
  redis.call('ZREMRANGEBYSCORE', key, 0, cutoff)
  if redis.call('ZCARD', key) >= limit then
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local oldest_ms = tonumber(oldest[2]) or now_ms
    local wait_ms = oldest_ms + window_ms - now_ms
    if wait_ms > max_wait_ms then
      max_wait_ms = wait_ms
    end
  end
end

if max_wait_ms > 0 then
  return {0, max_wait_ms}
end

for _, key in ipairs(KEYS) do
  redis.call('ZADD', key, now_ms, member)
  redis.call('PEXPIRE', key, window_ms)
end
return {1, 0}
"""


class RateLimiterUnavailable(RuntimeError):
    """Raised when the shared Redis-backed limiter cannot be reached."""


_REDIS_CLIENT: redis.Redis | None = None


def _build_redis_client() -> redis.Redis:
    return redis.Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=0.1,
        socket_timeout=0.1,
        retry_on_timeout=False,
    )


def _get_redis_client() -> redis.Redis:
    global _REDIS_CLIENT
    if _REDIS_CLIENT is None:
        _REDIS_CLIENT = _build_redis_client()
    return _REDIS_CLIENT


def _invalidate_redis_client() -> None:
    global _REDIS_CLIENT
    _REDIS_CLIENT = None


def _normalize_eval_result(result: object) -> tuple[bool, float]:
    if not isinstance(result, (list, tuple)) or len(result) != 2:
        raise RateLimiterUnavailable("Redis rate limiter returned an unexpected response.")

    allowed = bool(int(result[0]))
    wait_ms = max(float(result[1]), 0.0)
    return allowed, wait_ms / 1000.0


def wait_for_redis_sliding_window_slot(
    *,
    redis_key: str,
    limit: int,
    window_seconds: float = 1.0,
) -> float:
    waited_seconds = 0.0
    window_ms = max(1, int(round(window_seconds * 1000)))
    normalized_limit = max(1, int(limit))

    while True:
        client = _get_redis_client()
        member = uuid.uuid4().hex
        try:
            result = client.eval(
                _SLIDING_WINDOW_LUA,
                1,
                redis_key,
                normalized_limit,
                window_ms,
                member,
            )
        except RedisError as exc:
            _invalidate_redis_client()
            raise RateLimiterUnavailable(str(exc) or "Redis rate limiter is unavailable.") from exc

        allowed, wait_seconds = _normalize_eval_result(result)
        if allowed:
            return waited_seconds

        sleep_seconds = max(wait_seconds, 0.05)
        time.sleep(sleep_seconds)
        waited_seconds += sleep_seconds


def try_acquire_redis_sliding_window_slots(
    *,
    redis_keys: list[str],
    limit: int,
    window_seconds: float,
) -> tuple[bool, float]:
    """Atomically acquire one non-blocking slot across every supplied key."""
    normalized_keys = [key.strip() for key in redis_keys if key.strip()]
    if not normalized_keys:
        raise ValueError("At least one Redis rate-limit key is required.")

    client = _get_redis_client()
    window_ms = max(1, int(round(window_seconds * 1000)))
    normalized_limit = max(1, int(limit))
    try:
        result = client.eval(
            _MULTI_KEY_SLIDING_WINDOW_LUA,
            len(normalized_keys),
            *normalized_keys,
            normalized_limit,
            window_ms,
            uuid.uuid4().hex,
        )
    except RedisError as exc:
        _invalidate_redis_client()
        raise RateLimiterUnavailable(
            str(exc) or "Redis rate limiter is unavailable."
        ) from exc
    return _normalize_eval_result(result)
