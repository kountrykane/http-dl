# TODO: make sure our exports line up with what tests expect.

from .clients import (
    DataDownload, 
    FileDownload, 
    BaseDownload, 
    BatchDownload, 
    DownloadQueue
)
from .models import (
    DataDownloadResult, 
    FileDownloadResult,
    DownloadSettings, 
    RetryPolicy, 
    Timeouts
)
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
from .observability.metrics import (
    MetricsCollector,
    MetricsSnapshot,
    RequestMetrics,
    get_metrics_collector,
    format_snapshot,
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
