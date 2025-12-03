from __future__ import annotations
import asyncio
import time
from abc import ABC, abstractmethod
from typing import Optional

import httpx

from ..models.config import DownloadSettings
from ..exceptions import (
    RateLimitError,
    RetryAttemptsExceeded,
    TooManyRedirectsError,
    RedirectLoopError,
    retry_after_from_response,
    NetworkError,
    TimeoutError as DownloadTimeoutError,
    ConnectionError as DownloadConnectionError,
    DNSResolutionError,
)
from ..limiting.limiting import AsyncRateLimiter
from ..observability.logging import get_httpdl_logger, log_retry, log_redirect, HttpdlLoggerAdapter

import redis.asyncio as aioredis
from ..limiting.backends import (
    InMemoryBackend,
    RedisBackend,
    MultiprocessBackend
)

class BaseDownload(ABC):
    """
    Abstract base class for async download clients.

    Provides shared functionality:
      - Process-wide rate limiting (shared token bucket)
      - Per-host concurrency control (async semaphores)
      - Async HTTP client management
      - Retry logic with exponential backoff

    Subclasses must implement the async download() method to handle
    specific response processing needs.
    """

    def __init__(self, settings: Optional[DownloadSettings] = None):
        self.settings = settings or DownloadSettings()
        self._client: Optional[httpx.AsyncClient] = None

        # Initialize rate limiter with appropriate backend
        backend = self._create_rate_limit_backend()
        self._limiter = AsyncRateLimiter(
            rate=self.settings.requests_per_second,
            capacity=self.settings.requests_per_second,
            backend=backend,
        )
        self._host_semaphores: dict[str, asyncio.Semaphore] = {}
        self._logger = self.settings.logger or get_httpdl_logger(__name__)

        # Initialize User-Agent rotator if enabled
        self._user_agent_rotator = None
        if self.settings.rotate_user_agent:
            from ..stealth.stealth import UserAgentRotator
            self._user_agent_rotator = UserAgentRotator(
                mode=self.settings.user_agent_mode,
                custom_agents=self.settings.custom_user_agents
            )
            self._logger.info(
                "stealth.rotator_enabled",
                mode=self.settings.user_agent_mode,
                custom_count=len(self.settings.custom_user_agents or [])
            )

        # Initialize session manager if enabled
        self._session_manager = None
        if self.settings.enable_cookies and self.settings.session_file:
            from ..session.manager import SessionManager
            self._session_manager = SessionManager(session_file=self.settings.session_file)
            self._logger.info(
                "session.manager_enabled",
                session_file=str(self.settings.session_file)
            )

    def _create_rate_limit_backend(self):
        """Create appropriate rate limiting backend based on settings."""
        if self.settings.rate_limit_backend == "redis":
            if self.settings.redis_url is None:
                raise ValueError("redis_url must be provided when using redis backend")

            # Create Redis client
            redis_client = aioredis.from_url(
                self.settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )

            backend = RedisBackend(
                redis_client=redis_client,
                key_prefix=self.settings.redis_key_prefix,
            )

            # Note: Redis backend will be initialized on first use in AsyncRateLimiter
            # We cannot await here since this is called from __init__ (non-async context)

            return backend

        elif self.settings.rate_limit_backend == "multiprocess":
            if self.settings.multiprocess_manager is None:
                raise ValueError(
                    "multiprocess_manager must be provided when using multiprocess backend"
                )

            return MultiprocessBackend(self.settings.multiprocess_manager)

        else:
            # Default: in-memory backend (No Mutli-Process Rate Limiting, Only single process/multi-threading)
            return InMemoryBackend()

    async def __aenter__(self) -> "BaseDownload":
        # Rotate User-Agent if enabled
        user_agent = self.settings.user_agent
        if self._user_agent_rotator:
            user_agent = self._user_agent_rotator.get_random_user_agent()
            self._logger.debug("stealth.user_agent_rotated", user_agent=user_agent[:50] + "...")

        self._client = httpx.AsyncClient(
            headers={
                "User-Agent": user_agent,
                "Accept": self.settings.accept,
                "Accept-Encoding": self.settings.accept_encoding,
                "Connection": self.settings.connection,
            },
            timeout=httpx.Timeout(
                connect=self.settings.timeouts.connect,
                read=self.settings.timeouts.read,
                write=self.settings.timeouts.write,
                pool=self.settings.timeouts.pool,
            ),
            http2=self.settings.http2,
            limits=httpx.Limits(
                max_keepalive_connections=self.settings.max_keepalive_connections,
                max_connections=self.settings.max_connections,
                keepalive_expiry=self.settings.timeouts.pool,
            ),
        )

        # Load session if enabled
        if self._session_manager:
            loaded = await self._session_manager.load_session(self._client)
            if loaded:
                self._logger.info("session.loaded", cookie_count=len(self._client.cookies))

        self._logger.debug(
            "client.initialized",
            http2=self.settings.http2,
            requests_per_second=self.settings.requests_per_second,
            max_concurrency_per_host=self.settings.max_concurrency_per_host,
            max_connections=self.settings.max_connections,
            rate_limit_backend=self.settings.rate_limit_backend or "in-memory",
            stealth_enabled=self._user_agent_rotator is not None,
            session_enabled=self._session_manager is not None
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            # Save session if enabled
            if self._session_manager:
                await self._session_manager.save_session(self._client)

            await self._client.aclose()
            self._client = None
            self._logger.debug("client.closed")

    def _sem_for_host(self, host: str) -> asyncio.Semaphore:
        """Get or create a semaphore for per-host concurrency control."""
        sem = self._host_semaphores.get(host)
        if sem is None:
            sem = asyncio.Semaphore(self.settings.max_concurrency_per_host)
            self._host_semaphores[host] = sem
        return sem

    @abstractmethod
    async def download(self, url: str, **kwargs):
        """
        Abstract method for downloading content.
        Must be implemented by subclasses.
        """
        raise NotImplementedError

    async def _do_request_with_retry(
        self, method: str, url: str, stream: bool = False
    ) -> tuple[httpx.Response, list[str]]:
        """
        Execute HTTP request with retry logic, redirect handling, and structured exception handling.

        Converts httpx low-level exceptions to domain-specific download exceptions
        and implements retry logic with exponential backoff. Handles redirects manually
        when follow_redirects is enabled.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Target URL
            stream: Whether to return streaming response

        Returns:
            Tuple of (httpx.Response object, redirect chain list)

        Raises:
            NetworkError: For connection, timeout, DNS failures
            RateLimitError: When server rate limits after all retries
            RetryAttemptsExceeded: When retries exhausted without success
            TooManyRedirectsError: When redirect count exceeds max_redirects
            RedirectLoopError: When circular redirect is detected
        """
        assert self._client is not None, "Use async context manager: `async with DownloadClient()`"
        rp = self.settings.retry
        last_response: Optional[httpx.Response] = None
        last_exception: Optional[BaseException] = None

        request_start = time.time()
        host = self._get_host_from_url(url)

        self._logger.info("request.started", method=method, url=url, host=host)

        for attempt in range(rp.attempts + 1):
            try:
                if stream:
                    resp = await self._client.stream(method, url).__aenter__()
                    # For streaming, we return immediately without redirect handling
                    return resp, []

                # Manual redirect handling
                resp, redirect_chain = await self._follow_redirects(method, url)
            except TooManyRedirectsError:
                # Re-raise redirect errors immediately without retry
                raise
            except RedirectLoopError:
                # Re-raise redirect errors immediately without retry
                raise
            except httpx.ConnectError as exc:
                last_exception = exc
                if attempt == rp.attempts:
                    parsed_url = httpx.URL(url)
                    duration_ms = (time.time() - request_start) * 1000
                    self._logger.error(
                        "request.failed",
                        method=method,
                        url=url,
                        host=host,
                        error_type="connection_error",
                        attempts=rp.attempts + 1,
                        duration_ms=round(duration_ms, 2),
                        exc_info=exc
                    )
                    raise DownloadConnectionError(
                        message=f"Connection failed after {rp.attempts + 1} attempts",
                        url=url,
                        host=parsed_url.host,
                        port=parsed_url.port,
                        cause=exc,
                    ) from exc

                delay_ms = await self._backoff(attempt)
                log_retry(
                    self._logger,
                    attempt=attempt,
                    max_attempts=rp.attempts,
                    delay_ms=delay_ms,
                    reason="connection_error",
                    method=method,
                    url=url
                )
                continue
            except httpx.TimeoutException as exc:
                last_exception = exc
                if attempt == rp.attempts:
                    # Determine timeout type from exception
                    timeout_type = "unknown"
                    if "ConnectTimeout" in type(exc).__name__:
                        timeout_type = "connect"
                    elif "ReadTimeout" in type(exc).__name__:
                        timeout_type = "read"
                    elif "WriteTimeout" in type(exc).__name__:
                        timeout_type = "write"
                    elif "PoolTimeout" in type(exc).__name__:
                        timeout_type = "pool"

                    duration_ms = (time.time() - request_start) * 1000
                    self._logger.error(
                        "request.failed",
                        method=method,
                        url=url,
                        host=host,
                        error_type="timeout",
                        timeout_type=timeout_type,
                        attempts=rp.attempts + 1,
                        duration_ms=round(duration_ms, 2),
                        exc_info=exc
                    )
                    raise DownloadTimeoutError(
                        message=f"Request timed out after {rp.attempts + 1} attempts",
                        url=url,
                        timeout_type=timeout_type,
                        cause=exc,
                    ) from exc

                delay_ms = await self._backoff(attempt)
                log_retry(
                    self._logger,
                    attempt=attempt,
                    max_attempts=rp.attempts,
                    delay_ms=delay_ms,
                    reason="timeout",
                    method=method,
                    url=url
                )
                continue
            except httpx.ConnectTimeout as exc:
                last_exception = exc
                if attempt == rp.attempts:
                    duration_ms = (time.time() - request_start) * 1000
                    self._logger.error(
                        "request.failed",
                        method=method,
                        url=url,
                        host=host,
                        error_type="connect_timeout",
                        attempts=rp.attempts + 1,
                        duration_ms=round(duration_ms, 2),
                        exc_info=exc
                    )
                    raise DownloadTimeoutError(
                        message=f"Connection timed out after {rp.attempts + 1} attempts",
                        url=url,
                        timeout_type="connect",
                        timeout_seconds=self.settings.timeouts.connect,
                        cause=exc,
                    ) from exc

                delay_ms = await self._backoff(attempt)
                log_retry(
                    self._logger,
                    attempt=attempt,
                    max_attempts=rp.attempts,
                    delay_ms=delay_ms,
                    reason="connect_timeout",
                    method=method,
                    url=url
                )
                continue
            except Exception as exc:
                last_exception = exc
                # Check if it's a DNS resolution error
                if "Name or service not known" in str(exc) or "getaddrinfo failed" in str(exc):
                    if attempt == rp.attempts:
                        parsed_url = httpx.URL(url)
                        duration_ms = (time.time() - request_start) * 1000
                        self._logger.error(
                            "request.failed",
                            method=method,
                            url=url,
                            host=host,
                            error_type="dns_error",
                            attempts=rp.attempts + 1,
                            duration_ms=round(duration_ms, 2),
                            exc_info=exc
                        )
                        raise DNSResolutionError(
                            message=f"DNS resolution failed after {rp.attempts + 1} attempts",
                            url=url,
                            hostname=parsed_url.host,
                            cause=exc,
                        ) from exc

                    delay_ms = await self._backoff(attempt)
                    log_retry(
                        self._logger,
                        attempt=attempt,
                        max_attempts=rp.attempts,
                        delay_ms=delay_ms,
                        reason="dns_error",
                        method=method,
                        url=url
                    )
                    continue

                # Generic network error fallback
                if attempt == rp.attempts:
                    duration_ms = (time.time() - request_start) * 1000
                    self._logger.error(
                        "request.failed",
                        method=method,
                        url=url,
                        host=host,
                        error_type="network_error",
                        attempts=rp.attempts + 1,
                        duration_ms=round(duration_ms, 2),
                        exc_info=exc
                    )
                    raise NetworkError(
                        message=f"Request failed after {rp.attempts + 1} attempts: {exc}",
                        url=url,
                        cause=exc,
                    ) from exc

                delay_ms = await self._backoff(attempt)
                log_retry(
                    self._logger,
                    attempt=attempt,
                    max_attempts=rp.attempts,
                    delay_ms=delay_ms,
                    reason="network_error",
                    method=method,
                    url=url
                )
                continue

            last_response = resp
            status = resp.status_code

            # Handle rate limiting (429) and service unavailable (503)
            if status in (429, 503) and rp.respect_retry_after:
                retry_delay = retry_after_from_response(resp)
                await resp.aclose()
                if attempt == rp.attempts:
                    duration_ms = (time.time() - request_start) * 1000
                    self._logger.error(
                        "request.failed",
                        method=method,
                        url=url,
                        host=host,
                        error_type="rate_limit",
                        status_code=status,
                        retry_after=retry_delay,
                        attempts=rp.attempts + 1,
                        duration_ms=round(duration_ms, 2)
                    )
                    raise RateLimitError(
                        message=f"Rate limit encountered after {rp.attempts + 1} attempts",
                        url=url,
                        retry_after=retry_delay,
                        response=None,
                        status_code=status,
                    )

                log_retry(
                    self._logger,
                    attempt=attempt,
                    max_attempts=rp.attempts,
                    delay_ms=retry_delay * 1000,
                    reason=f"rate_limit_{status}",
                    method=method,
                    url=url,
                    status_code=status
                )
                if retry_delay > 0:
                    await asyncio.sleep(retry_delay)
                continue

            # Retry on 5xx server errors
            if status >= 500:
                delay_ms = await self._backoff(attempt)
                log_retry(
                    self._logger,
                    attempt=attempt,
                    max_attempts=rp.attempts,
                    delay_ms=delay_ms,
                    reason=f"server_error_{status}",
                    method=method,
                    url=url,
                    status_code=status
                )
                await resp.aclose()
                continue

            # Successful response
            duration_ms = (time.time() - request_start) * 1000
            self._logger.info(
                "request.completed",
                method=method,
                url=url,
                host=host,
                status_code=status,
                redirect_count=len(redirect_chain),
                attempts=attempt + 1,
                duration_ms=round(duration_ms, 2)
            )
            return resp, redirect_chain

        # Exhausted all retries
        raise RetryAttemptsExceeded(
            message=f"Request failed after {rp.attempts + 1} attempts",
            url=url,
            response=last_response,
            attempts=rp.attempts + 1,
            last_status_code=last_response.status_code if last_response else None,
            cause=last_exception,
        )

    async def _backoff(self, attempt: int) -> float:
        """Exponential backoff with jitter. Returns delay in milliseconds."""
        import random

        base = self.settings.retry.base_delay_ms / 1000.0
        delay = base * (attempt + 1)
        jitter = delay * (0.3 * (2 * random.random() - 1))  # +/-30%
        final_delay = max(0.05, delay + jitter)
        await asyncio.sleep(final_delay)
        return final_delay * 1000  # Return milliseconds for logging

    async def _apply_rate_limit(self) -> None:
        """Apply global rate limiting."""
        await self._limiter.wait()

    def _get_host_from_url(self, url: str) -> str:
        """Extract host from URL."""
        return httpx.URL(url).host or ""

    async def _follow_redirects(self, method: str, url: str) -> tuple[httpx.Response, list[str]]:
        """
        Follow redirects manually when follow_redirects is enabled.

        Tracks the redirect chain and detects loops and excessive redirects.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Initial URL to request

        Returns:
            Tuple of (final response, redirect chain)

        Raises:
            TooManyRedirectsError: When redirect count exceeds max_redirects
            RedirectLoopError: When circular redirect is detected
        """
        assert self._client is not None

        redirect_chain: list[str] = []
        current_url = url
        visited_urls: set[str] = {url}

        # If follow_redirects is disabled, just make the request
        if not self.settings.follow_redirects:
            resp = await self._client.request(method, current_url, follow_redirects=False)
            return resp, []

        for redirect_count in range(self.settings.max_redirects + 1):
            # Make request without automatic redirect following
            resp = await self._client.request(method, current_url, follow_redirects=False)

            # Check if this is a redirect status
            if resp.status_code not in (301, 302, 303, 307, 308):
                # Not a redirect, return the response
                return resp, redirect_chain

            # Extract Location header
            location = resp.headers.get("Location")
            if not location:
                # Redirect without Location header, return as-is
                return resp, redirect_chain

            # Close the redirect response
            await resp.aclose()

            # Resolve the redirect URL (handle relative URLs)
            next_url = str(httpx.URL(current_url).join(location))

            # Detect redirect loop
            if next_url in visited_urls:
                self._logger.error(
                    "redirect.loop_detected",
                    from_url=current_url,
                    to_url=next_url,
                    redirect_count=len(redirect_chain),
                    redirect_chain=redirect_chain
                )
                raise RedirectLoopError(
                    message=f"Redirect loop detected at URL: {next_url}",
                    url=url,
                    loop_url=next_url,
                    redirect_chain=redirect_chain + [next_url],
                )

            # Add to redirect chain and visited set
            redirect_chain.append(next_url)
            visited_urls.add(next_url)

            # Check if we've exceeded max redirects
            if redirect_count >= self.settings.max_redirects:
                self._logger.error(
                    "redirect.too_many",
                    redirect_count=len(redirect_chain),
                    max_redirects=self.settings.max_redirects,
                    redirect_chain=redirect_chain
                )
                raise TooManyRedirectsError(
                    message=f"Too many redirects: {len(redirect_chain)} exceeds limit",
                    url=url,
                    max_redirects=self.settings.max_redirects,
                    redirect_chain=redirect_chain,
                )

            # Log the redirect
            log_redirect(
                self._logger,
                from_url=current_url,
                to_url=next_url,
                status_code=resp.status_code,
                redirect_count=len(redirect_chain)
            )

            # Update method for 303 redirects (always use GET)
            if resp.status_code == 303:
                method = "GET"

            # Follow the redirect
            current_url = next_url

        # This should not be reached due to the check inside the loop
        raise TooManyRedirectsError(
            message=f"Too many redirects: {len(redirect_chain)} exceeds limit",
            url=url,
            max_redirects=self.settings.max_redirects,
            redirect_chain=redirect_chain,
        )
