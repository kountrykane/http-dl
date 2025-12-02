"""
HTTP-DL - Production-Ready HTTP Client

An async HTTP client with enterprise features:
- Multi-process rate limiting (Redis, multiprocessing, or in-memory)
- HTTP/2 support enabled by default
- Comprehensive metrics and monitoring
- Batch download utilities with concurrency control
- Automatic retries with exponential backoff
- Structured exception hierarchy

Two download modes available:
- DataDownload: Processes and decodes content (text decoding, decompression, classification)
- FileDownload: Downloads raw files without processing (preserves original encoding)

All download operations are async and must be awaited.
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
from .metrics import (
    MetricsCollector,
    MetricsSnapshot,
    RequestMetrics,
    get_metrics_collector,
    format_snapshot,
)
from .concurrency import (
    download_batch,
    download_files_batch,
    map_concurrent,
    retry_failed,
    DownloadQueue,
    BatchResult,
)

from .streaming import (
    StreamingDownload, 
    download_with_retry, 
    StreamingResult,
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

    # Metrics and monitoring
    "MetricsCollector",
    "MetricsSnapshot",
    "RequestMetrics",
    "get_metrics_collector",
    "format_snapshot",

    # Concurrency utilities
    "download_batch",
    "download_files_batch",
    "map_concurrent",
    "retry_failed",
    "DownloadQueue",
    "BatchResult",

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

    # Streaming Methods
    "StreamingDownload", 
    "download_with_retry", 
    "StreamingResult",
]
