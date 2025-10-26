"""
Comprehensive exception hierarchy for the SEC download package.

This module provides a structured exception system that covers all failure modes
in the download library, enabling precise error handling and rich debugging context.

Exception Hierarchy:
    DownloadError (base)
    ├── ValidationError
    │   ├── InvalidURLError
    │   ├── InvalidSettingsError
    │   └── PayloadSizeLimitError
    ├── NetworkError
    │   ├── ConnectionError
    │   ├── TimeoutError
    │   └── DNSResolutionError
    ├── HTTPError
    │   ├── ClientError (4xx)
    │   │   ├── BadRequestError (400)
    │   │   ├── UnauthorizedError (401)
    │   │   ├── ForbiddenError (403)
    │   │   ├── NotFoundError (404)
    │   │   ├── RateLimitError (429)
    │   │   └── ClientTimeoutError (408)
    │   └── ServerError (5xx)
    │       ├── InternalServerError (500)
    │       ├── BadGatewayError (502)
    │       └── ServiceUnavailableError (503)
    ├── ContentError
    │   ├── DecompressionError
    │   ├── EncodingError
    │   └── ContentTypeError
    └── RetryError
        ├── RetryAttemptsExceeded
        └── RetryBudgetExceeded

Usage:
    from sec.download.exceptions import NotFoundError, RateLimitError

    try:
        result = await client.download(url)
    except NotFoundError as e:
        logger.warning(f"Document not found: {e.url}")
    except RateLimitError as e:
        await asyncio.sleep(e.retry_after)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional, Dict, Any

import httpx

__all__ = [
    # Base exceptions
    "DownloadError",
    # Validation errors
    "ValidationError",
    "InvalidURLError",
    "InvalidSettingsError",
    "PayloadSizeLimitError",
    # Network errors
    "NetworkError",
    "ConnectionError",
    "TimeoutError",
    "DNSResolutionError",
    # HTTP errors
    "HTTPError",
    "ClientError",
    "BadRequestError",
    "UnauthorizedError",
    "ForbiddenError",
    "NotFoundError",
    "RateLimitError",
    "ClientTimeoutError",
    "ServerError",
    "InternalServerError",
    "BadGatewayError",
    "ServiceUnavailableError",
    # Redirect errors
    "RedirectError",
    "TooManyRedirectsError",
    "RedirectLoopError",
    # Content errors
    "ContentError",
    "DecompressionError",
    "EncodingError",
    "ContentTypeError",
    # Retry errors
    "RetryError",
    "RetryAttemptsExceeded",
    "RetryBudgetExceeded",
    # Utilities
    "retry_after_from_response",
    "classify_http_error",
]

DEFAULT_RETRY_AFTER_SECONDS = 601


# ============================================================================
# Base Exception
# ============================================================================


@dataclass(slots=True)
class DownloadError(Exception):
    """
    Base exception for all download-related failures.

    Provides rich context including URL, response, and causal exception chain.
    All download exceptions inherit from this class.
    """

    message: str
    url: Optional[str] = None
    response: Optional[httpx.Response] = None
    cause: Optional[BaseException] = None
    context: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)
        if self.cause is not None:
            self.__cause__ = self.cause

    def __str__(self) -> str:
        parts = [self.message]
        if self.url:
            parts.append(f"url={self.url}")
        if self.context:
            ctx_str = ", ".join(f"{k}={v}" for k, v in self.context.items())
            parts.append(f"context=({ctx_str})")
        return " | ".join(parts)


# ============================================================================
# Validation Errors
# ============================================================================


@dataclass(slots=True)
class ValidationError(DownloadError):
    """Base class for input validation failures."""
    pass


@dataclass(slots=True)
class InvalidURLError(ValidationError):
    """Raised when URL format is invalid or empty."""

    def __post_init__(self) -> None:
        if not self.message:
            self.message = f"Invalid or empty URL: {self.url!r}"
        DownloadError.__post_init__(self)


@dataclass(slots=True)
class InvalidSettingsError(ValidationError):
    """Raised when DownloadSettings contains invalid configuration."""

    setting_name: Optional[str] = None
    setting_value: Optional[Any] = None

    def __post_init__(self) -> None:
        if not self.message and self.setting_name:
            self.message = f"Invalid setting {self.setting_name}={self.setting_value!r}"
        DownloadError.__post_init__(self)


@dataclass(slots=True)
class PayloadSizeLimitError(ValidationError):
    """
    Raised when decompressed payload exceeds safety limits.

    Guards against decompression bombs and unexpectedly large responses.
    """

    actual_size: int = 0
    max_size: int = 0

    def __post_init__(self) -> None:
        if not self.message:
            self.message = (
                f"Payload size {self.actual_size:,} bytes exceeds "
                f"limit of {self.max_size:,} bytes"
            )
        DownloadError.__post_init__(self)


# ============================================================================
# Network Errors
# ============================================================================


@dataclass(slots=True)
class NetworkError(DownloadError):
    """Base class for network-level failures (connection, DNS, timeouts)."""
    pass


@dataclass(slots=True)
class ConnectionError(NetworkError):
    """
    Raised when TCP connection cannot be established.

    Common causes: host unreachable, connection refused, network down.
    """

    host: Optional[str] = None
    port: Optional[int] = None

    def __post_init__(self) -> None:
        if not self.message:
            self.message = f"Failed to connect to {self.host}:{self.port}"
        DownloadError.__post_init__(self)


@dataclass(slots=True)
class TimeoutError(NetworkError):
    """
    Raised when request exceeds configured timeout.

    Includes separate tracking for connect, read, write, and pool timeouts.
    """

    timeout_type: Optional[str] = None  # "connect", "read", "write", "pool"
    timeout_seconds: Optional[float] = None

    def __post_init__(self) -> None:
        if not self.message:
            self.message = (
                f"Request timed out ({self.timeout_type}: {self.timeout_seconds}s)"
            )
        DownloadError.__post_init__(self)


@dataclass(slots=True)
class DNSResolutionError(NetworkError):
    """Raised when hostname cannot be resolved to IP address."""

    hostname: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.message:
            self.message = f"DNS resolution failed for {self.hostname}"
        DownloadError.__post_init__(self)


# ============================================================================
# HTTP Errors
# ============================================================================


@dataclass(slots=True)
class HTTPError(DownloadError):
    """
    Base class for HTTP status code errors (4xx, 5xx).

    Captures status code, response body excerpt, and headers for debugging.
    """

    status_code: int = 0
    response_excerpt: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.message:
            excerpt = f": {self.response_excerpt!r}" if self.response_excerpt else ""
            self.message = f"HTTP {self.status_code}{excerpt}"
        DownloadError.__post_init__(self)


# --- Client Errors (4xx) ---


@dataclass(slots=True)
class ClientError(HTTPError):
    """Base class for client errors (4xx status codes)."""
    pass


@dataclass(slots=True)
class BadRequestError(ClientError):
    """Raised for HTTP 400 Bad Request."""
    status_code: int = 400


@dataclass(slots=True)
class UnauthorizedError(ClientError):
    """Raised for HTTP 401 Unauthorized (authentication required)."""
    status_code: int = 401
    www_authenticate: Optional[str] = None


@dataclass(slots=True)
class ForbiddenError(ClientError):
    """
    Raised for HTTP 403 Forbidden.

    Often indicates invalid User-Agent or missing required headers for SEC.
    """
    status_code: int = 403


@dataclass(slots=True)
class NotFoundError(ClientError):
    """Raised for HTTP 404 Not Found."""
    status_code: int = 404


@dataclass(slots=True)
class ClientTimeoutError(ClientError):
    """Raised for HTTP 408 Request Timeout."""
    status_code: int = 408


@dataclass(slots=True)
class RateLimitError(ClientError):
    """
    Raised when server rate limits the client (HTTP 429).

    Includes retry_after delay parsed from Retry-After header.
    Defaults to SEC guidance (601 seconds) if header is absent.
    """

    status_code: int = 429
    retry_after: float = DEFAULT_RETRY_AFTER_SECONDS

    def __post_init__(self) -> None:
        if not self.message:
            self.message = (
                f"Rate limit exceeded (HTTP {self.status_code}). "
                f"Retry after {self.retry_after}s"
            )
        DownloadError.__post_init__(self)


# --- Server Errors (5xx) ---


@dataclass(slots=True)
class ServerError(HTTPError):
    """Base class for server errors (5xx status codes)."""
    pass


@dataclass(slots=True)
class InternalServerError(ServerError):
    """Raised for HTTP 500 Internal Server Error."""
    status_code: int = 500


@dataclass(slots=True)
class BadGatewayError(ServerError):
    """Raised for HTTP 502 Bad Gateway."""
    status_code: int = 502


@dataclass(slots=True)
class ServiceUnavailableError(ServerError):
    """
    Raised for HTTP 503 Service Unavailable.

    Server is temporarily unable to handle requests (maintenance, overload).
    May include Retry-After header.
    """

    status_code: int = 503
    retry_after: Optional[float] = None

    def __post_init__(self) -> None:
        if not self.message:
            retry_msg = f", retry after {self.retry_after}s" if self.retry_after else ""
            self.message = f"Service unavailable (HTTP {self.status_code}){retry_msg}"
        DownloadError.__post_init__(self)


# ============================================================================
# Redirect Errors
# ============================================================================


@dataclass(slots=True)
class RedirectError(DownloadError):
    """Base class for redirect-related failures."""

    redirect_chain: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TooManyRedirectsError(RedirectError):
    """
    Raised when redirect count exceeds max_redirects limit.

    Guards against excessive redirect chains that may indicate
    misconfigured servers or redirect loops.
    """

    max_redirects: int = 0

    def __post_init__(self) -> None:
        if not self.message:
            chain_len = len(self.redirect_chain)
            self.message = (
                f"Too many redirects: {chain_len} redirects exceeds "
                f"limit of {self.max_redirects}"
            )
        DownloadError.__post_init__(self)


@dataclass(slots=True)
class RedirectLoopError(RedirectError):
    """
    Raised when a circular redirect is detected.

    Occurs when a URL in the redirect chain is visited more than once,
    indicating an infinite redirect loop.
    """

    loop_url: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.message:
            self.message = f"Redirect loop detected at URL: {self.loop_url}"
        DownloadError.__post_init__(self)


# ============================================================================
# Content Processing Errors
# ============================================================================


@dataclass(slots=True)
class ContentError(DownloadError):
    """Base class for content processing failures (decompression, encoding)."""
    pass


@dataclass(slots=True)
class DecompressionError(ContentError):
    """
    Raised when transfer or content encoding decompression fails.

    Covers gzip, deflate, brotli decompression failures.
    """

    encoding: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.message:
            enc = f" ({self.encoding})" if self.encoding else ""
            self.message = f"Decompression failed{enc}"
        DownloadError.__post_init__(self)


@dataclass(slots=True)
class EncodingError(ContentError):
    """
    Raised when text decoding fails with specified charset.

    Indicates charset mismatch or corrupted text data.
    """

    charset: Optional[str] = None
    tried_charsets: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.message:
            tried = f", tried={self.tried_charsets}" if self.tried_charsets else ""
            self.message = f"Text decoding failed with charset={self.charset}{tried}"
        DownloadError.__post_init__(self)


@dataclass(slots=True)
class ContentTypeError(ContentError):
    """
    Raised when content type is unexpected or cannot be classified.

    Useful for strict validation when specific content types are required.
    """

    expected: Optional[str] = None
    actual: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.message:
            self.message = (
                f"Content type mismatch: expected {self.expected!r}, "
                f"got {self.actual!r}"
            )
        DownloadError.__post_init__(self)


# ============================================================================
# Retry Errors
# ============================================================================


@dataclass(slots=True)
class RetryError(DownloadError):
    """Base class for retry mechanism failures."""
    pass


@dataclass(slots=True)
class RetryAttemptsExceeded(RetryError):
    """
    Raised when maximum retry attempts exhausted without success.

    Includes attempt count and last response/error for debugging.
    """

    attempts: int = 0
    last_status_code: Optional[int] = None

    def __post_init__(self) -> None:
        if not self.message:
            status = f", last status={self.last_status_code}" if self.last_status_code else ""
            self.message = f"Retry attempts exhausted ({self.attempts} attempts{status})"
        DownloadError.__post_init__(self)


@dataclass(slots=True)
class RetryBudgetExceeded(RetryError):
    """
    Raised when cumulative retry delay exceeds acceptable threshold.

    Guards against indefinite retry loops that respect Retry-After headers.
    """

    total_delay_seconds: float = 0.0
    max_delay_seconds: float = 0.0

    def __post_init__(self) -> None:
        if not self.message:
            self.message = (
                f"Retry budget exceeded: {self.total_delay_seconds:.1f}s "
                f"/ {self.max_delay_seconds:.1f}s"
            )
        DownloadError.__post_init__(self)


# ============================================================================
# Utility Functions
# ============================================================================


def retry_after_from_response(response: Optional[httpx.Response]) -> float:
    """
    Best-effort extraction of Retry-After header value in seconds.

    Supports both delta-seconds (integer) and HTTP-date formats.
    Defaults to SEC guidance (601 seconds) if header is absent or malformed.

    Args:
        response: httpx Response object or None

    Returns:
        Retry delay in seconds (minimum 0.0)

    Examples:
        >>> retry_after_from_response(response_with_header("120"))
        120.0
        >>> retry_after_from_response(response_with_header("Wed, 21 Oct 2025 07:28:00 GMT"))
        3600.0  # example future time
        >>> retry_after_from_response(None)
        601.0
    """
    if response is None:
        return DEFAULT_RETRY_AFTER_SECONDS

    header = response.headers.get("Retry-After")
    if not header:
        return DEFAULT_RETRY_AFTER_SECONDS

    header = header.strip()

    # Try integer seconds first
    if header.isdigit():
        try:
            value = float(header)
        except ValueError:
            return DEFAULT_RETRY_AFTER_SECONDS
        return max(value, 0.0)

    # Try HTTP-date format
    try:
        retry_dt = parsedate_to_datetime(header)
    except (TypeError, ValueError):
        return DEFAULT_RETRY_AFTER_SECONDS

    if retry_dt is None:
        return DEFAULT_RETRY_AFTER_SECONDS

    if retry_dt.tzinfo is None:
        retry_dt = retry_dt.replace(tzinfo=timezone.utc)

    delta = (retry_dt - datetime.now(timezone.utc)).total_seconds()
    return max(delta, 0.0)


def classify_http_error(
    status_code: int,
    url: str,
    response: Optional[httpx.Response] = None,
    excerpt: Optional[str] = None,
) -> HTTPError:
    """
    Factory function to create appropriate HTTPError subclass for status code.

    Maps HTTP status codes to specific exception types for granular handling.

    Args:
        status_code: HTTP response status code
        url: Request URL
        response: Optional httpx.Response for additional context
        excerpt: Optional response body excerpt for debugging

    Returns:
        Specific HTTPError subclass instance

    Examples:
        >>> classify_http_error(404, "https://example.com/missing")
        NotFoundError(status_code=404, url='https://example.com/missing')
        >>> classify_http_error(429, "https://api.sec.gov/...", response)
        RateLimitError(status_code=429, retry_after=120.0, ...)
    """
    # Map status codes to exception classes
    error_map: Dict[int, type[HTTPError]] = {
        400: BadRequestError,
        401: UnauthorizedError,
        403: ForbiddenError,
        404: NotFoundError,
        408: ClientTimeoutError,
        429: RateLimitError,
        500: InternalServerError,
        502: BadGatewayError,
        503: ServiceUnavailableError,
    }

    # Get specific error class or fall back to generic
    if status_code in error_map:
        error_class = error_map[status_code]
    elif 400 <= status_code < 500:
        error_class = ClientError
    elif 500 <= status_code < 600:
        error_class = ServerError
    else:
        error_class = HTTPError

    # Build error with appropriate context
    kwargs: Dict[str, Any] = {
        "message": "",
        "url": url,
        "response": response,
        "status_code": status_code,
        "response_excerpt": excerpt,
    }

    # Add special handling for rate limit errors
    if status_code == 429 and response is not None:
        kwargs["retry_after"] = retry_after_from_response(response)

    # Add special handling for 503 errors
    if status_code == 503 and response is not None:
        retry_after = retry_after_from_response(response)
        if retry_after != DEFAULT_RETRY_AFTER_SECONDS:
            kwargs["retry_after"] = retry_after

    return error_class(**kwargs)
