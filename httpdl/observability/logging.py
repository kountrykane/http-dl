"""
Logging adapter for httpdl HTTP download toolkit.

This module provides dependency injection for structured logging while keeping
httpdl decoupled from specific logging implementations (e.g., retnah-data's logging).

Architecture:
- HttpdlLoggerAdapter wraps any LoggerAdapter and provides httpdl-specific helpers
- _logger_factory allows consumers to inject their logger factory
- Default factory uses standard library logging when no custom factory is configured

Usage in httpdl:
    from httpdl.logging import get_httpdl_logger

    logger = get_httpdl_logger(__name__, url="https://www.sec.gov/...", host="www.sec.gov")
    logger.info("request.started")

Usage in consumer applications (configuring the factory):
    from httpdl.logging import configure_logging
    from src.logging import get_custom_logger

    # Configure httpdl to use custom structured logging
    configure_logging(logger_factory=get_custom_logger)

    # Now all httpdl operations will use custom structured logging
    async with DataDownload(settings) as client:
        result = await client.download(url)
"""

from __future__ import annotations

import logging
import time
from logging import Logger, LoggerAdapter
from typing import Any, Callable, Dict, Optional


# Global logger factory (can be injected by embedding applications)
_logger_factory: Optional[Callable[..., LoggerAdapter]] = None


class HttpdlLoggerAdapter:
    """
    Thin wrapper around LoggerAdapter providing httpdl-specific logging helpers.

    This adapter ensures consistent event naming and metadata structure across
    the httpdl library while allowing flexible backend implementations.
    """

    def __init__(self, logger: LoggerAdapter, context: Optional[Dict[str, Any]] = None):
        """
        Initialize the adapter.

        Args:
            logger: Underlying LoggerAdapter (from custom logger or stdlib)
            context: Additional context to bind to all log records
        """
        self._logger = logger
        self._context = context or {}

    def _merge_context(self, **extra: Any) -> Dict[str, Any]:
        """Merge bound context with extra fields."""
        return {**self._context, **extra}

    def debug(self, event: str, **extra: Any) -> None:
        """Log DEBUG-level event."""
        self._logger.debug(event, extra=self._merge_context(**extra))

    def info(self, event: str, **extra: Any) -> None:
        """Log INFO-level event."""
        self._logger.info(event, extra=self._merge_context(**extra))

    def warning(self, event: str, **extra: Any) -> None:
        """Log WARNING-level event."""
        self._logger.warning(event, extra=self._merge_context(**extra))

    def error(self, event: str, exc_info: Optional[BaseException] = None, **extra: Any) -> None:
        """Log ERROR-level event."""
        self._logger.error(event, extra=self._merge_context(**extra), exc_info=exc_info)


def _default_logger_factory(name: str, **context: Any) -> LoggerAdapter:
    """
    Default logger factory using standard library logging.

    Returns a basic LoggerAdapter when no custom factory is configured.
    """
    base_logger: Logger = logging.getLogger(name)
    return logging.LoggerAdapter(base_logger, {"extra": context})


def configure_logging(logger_factory: Callable[..., LoggerAdapter]) -> None:
    """
    Configure httpdl to use a custom logger factory.

    This allows embedding applications to inject their structured logging implementation.

    Args:
        logger_factory: Callable that returns a LoggerAdapter, signature:
                       (name: str, **context) -> LoggerAdapter

    Usage:
        from httpdl.logging import configure_logging
        from src.logging import get_custom_logger

        configure_logging(logger_factory=get_custom_logger)
    """
    global _logger_factory
    _logger_factory = logger_factory


def get_httpdl_logger(
    name: str,
    url: Optional[str] = None,
    host: Optional[str] = None,
    method: Optional[str] = None,
    status_code: Optional[int] = None,
    **extra_context: Any
) -> HttpdlLoggerAdapter:
    """
    Get an httpdl logger with HTTP request context.

    Uses the configured logger factory if set, otherwise falls back to stdlib logging.

    Args:
        name: Logger name (typically __name__)
        url: Request URL
        host: Target host
        method: HTTP method (GET, POST, etc.)
        status_code: HTTP response status code
        **extra_context: Additional context to bind

    Returns:
        HttpdlLoggerAdapter with bound context

    Usage:
        logger = get_httpdl_logger(__name__, url="https://www.sec.gov/...", host="www.sec.gov")
        logger.info("request.started", method="GET")
    """
    # Build context dict
    context: Dict[str, Any] = {**extra_context}

    if url is not None:
        context["url"] = url
    if host is not None:
        context["host"] = host
    if method is not None:
        context["method"] = method
    if status_code is not None:
        context["status_code"] = status_code

    # Use configured factory or default
    factory = _logger_factory or _default_logger_factory
    base_logger = factory(name, **context)

    return HttpdlLoggerAdapter(base_logger, context)


def log_timing(
    logger: HttpdlLoggerAdapter,
    event_prefix: str,
    **context: Any
) -> "TimingContext":
    """
    Context manager for timing HTTP operations.

    Usage:
        with log_timing(logger, "request", method="GET"):
            response = await client.get(url)
        # Automatically logs request.started and request.completed with duration
    """
    return TimingContext(logger, event_prefix, context)


class TimingContext:
    """Context manager for timing and logging HTTP operations."""

    def __init__(self, logger: HttpdlLoggerAdapter, event_prefix: str, context: Dict[str, Any]):
        self.logger = logger
        self.event_prefix = event_prefix
        self.context = context
        self.start_time = 0.0

    def __enter__(self) -> "TimingContext":
        self.start_time = time.time()
        self.logger.info(f"{self.event_prefix}.started", **self.context)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        duration_ms = (time.time() - self.start_time) * 1000

        if exc_type is None:
            self.logger.info(
                f"{self.event_prefix}.completed",
                duration_ms=round(duration_ms, 2),
                **self.context
            )
        else:
            self.logger.error(
                f"{self.event_prefix}.failed",
                duration_ms=round(duration_ms, 2),
                exc_info=exc_val,
                **self.context
            )


def log_exception(
    logger: HttpdlLoggerAdapter,
    exc: BaseException,
    event: str,
    **context: Any
) -> None:
    """
    Log an exception with httpdl context.

    Args:
        logger: Logger instance
        exc: Exception to log
        event: Event name (e.g., "request.failed")
        **context: Additional context

    Usage:
        try:
            response = await client.download(url)
        except DownloadError as exc:
            log_exception(logger, exc, "request.failed", method="GET")
            raise
    """
    error_context = {
        **context,
        "error_type": exc.__class__.__name__,
        "error_message": str(exc),
    }

    logger.error(event, exc_info=exc, **error_context)


def log_retry(
    logger: HttpdlLoggerAdapter,
    attempt: int,
    max_attempts: int,
    delay_ms: float,
    reason: str,
    **context: Any
) -> None:
    """
    Log a retry attempt with backoff details.

    Args:
        logger: Logger instance
        attempt: Current attempt number (0-indexed)
        max_attempts: Maximum retry attempts
        delay_ms: Backoff delay in milliseconds
        reason: Reason for retry (e.g., "timeout", "503_error")
        **context: Additional context

    Usage:
        log_retry(
            logger,
            attempt=2,
            max_attempts=5,
            delay_ms=2000.5,
            reason="timeout",
            status_code=503
        )
    """
    logger.warning(
        "request.retry",
        attempt=attempt,
        max_attempts=max_attempts,
        delay_ms=round(delay_ms, 2),
        reason=reason,
        **context
    )


def log_redirect(
    logger: HttpdlLoggerAdapter,
    from_url: str,
    to_url: str,
    status_code: int,
    redirect_count: int,
    **context: Any
) -> None:
    """
    Log an HTTP redirect.

    Args:
        logger: Logger instance
        from_url: Original URL
        to_url: Redirect target URL
        status_code: HTTP redirect status code (301, 302, 303, 307, 308)
        redirect_count: Number of redirects so far in chain
        **context: Additional context

    Usage:
        log_redirect(
            logger,
            from_url="https://example.com/old",
            to_url="https://example.com/new",
            status_code=301,
            redirect_count=1
        )
    """
    logger.debug(
        "request.redirect",
        from_url=from_url,
        to_url=to_url,
        status_code=status_code,
        redirect_count=redirect_count,
        **context
    )


def log_rate_limit(
    logger: HttpdlLoggerAdapter,
    wait_ms: float,
    tokens_requested: float = 1.0,
    **context: Any
) -> None:
    """
    Log rate limiting wait time.

    Args:
        logger: Logger instance
        wait_ms: Wait duration in milliseconds
        tokens_requested: Number of tokens requested
        **context: Additional context

    Usage:
        log_rate_limit(logger, wait_ms=125.5, tokens_requested=1.0)
    """
    logger.debug(
        "rate_limit.wait",
        wait_ms=round(wait_ms, 2),
        tokens_requested=tokens_requested,
        **context
    )


def log_content_processing(
    logger: HttpdlLoggerAdapter,
    operation: str,
    content_type: Optional[str] = None,
    charset: Optional[str] = None,
    size_bytes: Optional[int] = None,
    kind: Optional[str] = None,
    **context: Any
) -> None:
    """
    Log content processing operations (decompression, decoding, classification).

    Args:
        logger: Logger instance
        operation: Operation name (e.g., "decompress", "decode", "classify")
        content_type: Content-Type header value
        charset: Detected or specified charset
        size_bytes: Content size in bytes
        kind: Classified content kind (json, xml, html, etc.)
        **context: Additional context

    Usage:
        log_content_processing(
            logger,
            operation="decompress",
            content_type="application/json",
            size_bytes=52384,
            compression="gzip"
        )
    """
    logger.debug(
        f"content.{operation}",
        content_type=content_type,
        charset=charset,
        size_bytes=size_bytes,
        kind=kind,
        **context
    )
