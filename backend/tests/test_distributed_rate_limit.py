from __future__ import annotations

from redis.exceptions import ConnectionError as RedisConnectionError

import pytest

from app.core import distributed_rate_limit


class _FakeRedisClient:
    def __init__(self, results: list[list[int] | tuple[int, int] | Exception]) -> None:
        self._results = list(results)
        self.calls: list[tuple[str, int, tuple[object, ...]]] = []

    def eval(self, script: str, numkeys: int, *args: object) -> list[int] | tuple[int, int]:
        self.calls.append((script, numkeys, args))
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def test_wait_for_redis_sliding_window_slot_waits_until_allowed(monkeypatch) -> None:
    fake_client = _FakeRedisClient(
        [
            [0, 250],
            [1, 0],
        ]
    )
    sleeps: list[float] = []

    monkeypatch.setattr(distributed_rate_limit, "_get_redis_client", lambda: fake_client)
    monkeypatch.setattr(distributed_rate_limit.time, "sleep", lambda duration: sleeps.append(duration))

    waited_seconds = distributed_rate_limit.wait_for_redis_sliding_window_slot(
        redis_key="ratelimit:etsy:test:global",
        limit=5,
        window_seconds=1.0,
    )

    assert waited_seconds == pytest.approx(0.25)
    assert sleeps == [0.25]
    assert len(fake_client.calls) == 2
    assert fake_client.calls[0][1] == 1
    assert fake_client.calls[0][2][0] == "ratelimit:etsy:test:global"


def test_wait_for_redis_sliding_window_slot_raises_unavailable_on_redis_error(monkeypatch) -> None:
    fake_client = _FakeRedisClient([RedisConnectionError("redis offline")])

    monkeypatch.setattr(distributed_rate_limit, "_get_redis_client", lambda: fake_client)

    with pytest.raises(distributed_rate_limit.RateLimiterUnavailable, match="redis offline"):
        distributed_rate_limit.wait_for_redis_sliding_window_slot(
            redis_key="ratelimit:etsy:test:global",
            limit=5,
            window_seconds=1.0,
        )


def test_try_acquire_redis_sliding_window_slots_is_atomic_across_keys(
    monkeypatch,
) -> None:
    fake_client = _FakeRedisClient([[1, 0]])
    monkeypatch.setattr(
        distributed_rate_limit, "_get_redis_client", lambda: fake_client
    )

    allowed, retry_after = (
        distributed_rate_limit.try_acquire_redis_sliding_window_slots(
            redis_keys=["ratelimit:ai:org", "ratelimit:ai:user"],
            limit=3,
            window_seconds=60,
        )
    )

    assert allowed is True
    assert retry_after == 0
    assert fake_client.calls[0][1] == 2
    assert fake_client.calls[0][2][:2] == (
        "ratelimit:ai:org",
        "ratelimit:ai:user",
    )


def test_try_acquire_redis_sliding_window_slots_returns_retry_delay(
    monkeypatch,
) -> None:
    fake_client = _FakeRedisClient([[0, 12_500]])
    monkeypatch.setattr(
        distributed_rate_limit, "_get_redis_client", lambda: fake_client
    )

    allowed, retry_after = (
        distributed_rate_limit.try_acquire_redis_sliding_window_slots(
            redis_keys=["ratelimit:ai:org", "ratelimit:ai:user"],
            limit=3,
            window_seconds=60,
        )
    )

    assert allowed is False
    assert retry_after == pytest.approx(12.5)
