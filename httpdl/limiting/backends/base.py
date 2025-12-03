from __future__ import annotations
from typing import Optional
import asyncio
from abc import ABC, abstractmethod

class AsyncReentrantLock:
    """Re-entrant asyncio-compatible lock keyed by current task."""

    def __init__(self) -> None:
        self._lock: Optional[asyncio.Lock] = None
        self._owner: Optional[asyncio.Task] = None
        self._depth = 0
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def _ensure_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._lock is None or self._loop is not loop:
            self._lock = asyncio.Lock()
            self._loop = loop
        return self._lock

    async def acquire(self) -> None:
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("Async lock requires a running task")

        if self._owner is task:
            self._depth += 1
            return

        lock = self._ensure_lock()
        await lock.acquire()
        self._owner = task
        self._depth = 1

    def release(self) -> None:
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("Async lock requires a running task")
        if self._owner is not task:
            raise RuntimeError("Lock can only be released by the owning task")

        self._depth -= 1
        if self._depth == 0:
            self._owner = None
            assert self._lock is not None
            self._lock.release()

    async def __aenter__(self) -> "_AsyncReentrantLock":
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.release()

class BaseLimiterBackend(ABC):
    """Abstract base class for rate limiter backends."""

    @abstractmethod
    async def get_tokens(self) -> float:
        """Get current token count."""
        pass

    @abstractmethod
    async def set_tokens(self, tokens: float) -> None:
        """Set token count."""
        pass

    @abstractmethod
    async def get_last_refill(self) -> float:
        """Get last refill timestamp."""
        pass

    @abstractmethod
    async def set_last_refill(self, timestamp: float) -> None:
        """Set last refill timestamp."""
        pass

    @abstractmethod
    async def acquire_lock(self) -> bool:
        """Acquire distributed lock. Returns True if acquired."""
        pass

    @abstractmethod
    async def release_lock(self) -> None:
        """Release distributed lock."""
        pass