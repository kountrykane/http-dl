from __future__ import annotations

import asyncio
import time
from .base import BaseLimiterBackend

class MultiprocessBackend(BaseLimiterBackend):
    """
    Multiprocessing-based backend for multi-process scenarios without Redis.

    Uses multiprocessing.Manager for shared state across processes.
    Suitable for local multi-process applications where a parent process
    spawns worker processes.

    Note: This backend requires manual initialization of the Manager
    in the main process before forking. Not suitable for Celery-style
    distributed workers (use RedisBackend instead).

    Example:
        from multiprocessing import Manager

        manager = Manager()
        backend = MultiprocessBackend(manager)
    """

    def __init__(self, manager):
        """
        Initialize multiprocessing backend.

        Args:
            manager: multiprocessing.Manager instance
        """
        self._namespace = manager.Namespace()
        self._namespace.tokens = 0.0
        self._namespace.last_refill = time.monotonic()
        self._lock = manager.Lock()

    async def get_tokens(self) -> float:
        return float(self._namespace.tokens)

    async def set_tokens(self, tokens: float) -> None:
        self._namespace.tokens = tokens

    async def get_last_refill(self) -> float:
        return float(self._namespace.last_refill)

    async def set_last_refill(self, timestamp: float) -> None:
        self._namespace.last_refill = timestamp

    async def acquire_lock(self) -> bool:
        """Acquire multiprocessing lock."""
        # Run in executor since Lock.acquire() is synchronous
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._lock.acquire)
        return True

    async def release_lock(self) -> None:
        """Release multiprocessing lock."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._lock.release)
