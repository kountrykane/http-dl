from __future__ import annotations

import asyncio
import threading
import time
from typing import Optional


class AsyncTokenBucket:
    """Process-wide async token bucket protected by a threading lock."""

    _min_sleep = 0.005

    def __init__(self, rate: float, capacity: Optional[float] = None):
        if rate <= 0:
            raise ValueError("rate must be positive")
        capacity = float(capacity) if capacity is not None else float(rate)
        if capacity <= 0:
            raise ValueError("capacity must be positive")

        self._rate = float(rate)
        self._capacity = capacity
        self._tokens = min(1.0, capacity)
        self._updated_at = time.monotonic()
        self._lock = threading.Lock()

    def _refill_locked(self, now: float) -> None:
        elapsed = now - self._updated_at
        if elapsed > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._updated_at = now

    def configure(self, rate: float, capacity: Optional[float] = None) -> None:
        """Adopt stricter rate/capacity settings if a client requests them."""
        new_rate = float(rate)
        new_capacity = float(capacity) if capacity is not None else new_rate
        if new_rate <= 0 or new_capacity <= 0:
            raise ValueError("rate and capacity must be positive")

        with self._lock:
            now = time.monotonic()
            self._refill_locked(now)
            if new_rate < self._rate:
                self._rate = new_rate
            if new_capacity != self._capacity:
                self._capacity = new_capacity
                self._tokens = min(self._tokens, self._capacity)

    async def wait(self, tokens: float = 1.0) -> None:
        if tokens <= 0:
            return

        while True:
            with self._lock:
                now = time.monotonic()
                self._refill_locked(now)
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                deficit = tokens - self._tokens
                wait_time = max(deficit / self._rate, self._min_sleep)
            await asyncio.sleep(wait_time)

    @property
    def rate(self) -> float:
        with self._lock:
            return self._rate

    @property
    def capacity(self) -> float:
        with self._lock:
            return self._capacity


class AsyncRateLimiter:
    """Process-wide rate limiter that shares a singleton AsyncTokenBucket."""

    _shared_bucket: Optional[AsyncTokenBucket] = None
    _bucket_guard = threading.Lock()

    def __init__(self, rate: int, capacity: Optional[int] = None):
        bucket = self._ensure_bucket(float(rate), capacity)
        self._bucket = bucket

    @classmethod
    def _ensure_bucket(cls, rate: float, capacity: Optional[int]) -> AsyncTokenBucket:
        bucket_capacity = float(capacity) if capacity is not None else rate
        with cls._bucket_guard:
            if cls._shared_bucket is None:
                cls._shared_bucket = AsyncTokenBucket(rate=rate, capacity=bucket_capacity)
            else:
                cls._shared_bucket.configure(rate=rate, capacity=bucket_capacity)
            return cls._shared_bucket

    async def wait(self, tokens: float = 1.0) -> None:
        await self._bucket.wait(tokens)

    @property
    def rate(self) -> float:
        return self._bucket.rate

    @property
    def capacity(self) -> float:
        return self._bucket.capacity
