"""
SEC Download Package - Async Implementation

This package provides async functionality for downloading SEC documents
with rate limiting, retry logic, and proper content handling.

Two download modes are available:
- DataDownload: Processes and decodes content (text decoding, decompression, classification)
- FileDownload: Downloads raw files without processing (preserves original encoding)

All download operations are now async and must be awaited.
"""

from .download import DataDownload, FileDownload
from .config import DownloadSettings, RetryPolicy, Timeouts
from .models import DataDownloadResult, FileDownloadResult
from .core import BaseDownload
from .exceptions import (
    # Base exceptions
    DownloadError,
    # Validation errors
    ValidationError,
    InvalidURLError,
    InvalidSettingsError,
    PayloadSizeLimitError,
    # Network errors
    NetworkError,
    ConnectionError,
    TimeoutError,
    DNSResolutionError,
    # HTTP errors
    HTTPError,
    ClientError,
    BadRequestError,
    UnauthorizedError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    ClientTimeoutError,
    ServerError,
    InternalServerError,
    BadGatewayError,
    ServiceUnavailableError,
    # Redirect errors
    RedirectError,
    TooManyRedirectsError,
    RedirectLoopError,
    # Content errors
    ContentError,
    DecompressionError,
    EncodingError,
    ContentTypeError,
    # Retry errors
    RetryError,
    RetryAttemptsExceeded,
    RetryBudgetExceeded,
    # Utilities
    retry_after_from_response,
    classify_http_error,
)
from .utils import (
    normalize_content_type,
    extract_charset,
    classify_kind,
    decode_text,
    decompress_transfer,
)

__all__ = [
    # Primary download classes
    "DataDownload",
    "FileDownload",

    # Configuration
    "DownloadSettings",
    "RetryPolicy",
    "Timeouts",

    # Result models
    "DataDownloadResult",
    "FileDownloadResult",

    # Base class (for extending)
    "BaseDownload",

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
    # Utility functions
    "retry_after_from_response",
    "classify_http_error",

    # Content utility functions
    "normalize_content_type",
    "extract_charset",
    "classify_kind",
    "decode_text",
    "decompress_transfer",
]