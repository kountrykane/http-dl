from .results import (
    FileDownloadResult,
    DataDownloadResult,
    BatchDownloadResult
)

from .config import (
    DownloadSettings,
    RetryPolicy,
    Timeouts
)

__all__ = [
    # Result Models
    "FileDownloadResult",
    "DataDownloadResult",
    "BatchDownloadResult",

    # Config Models
    "DownloadSettings",
    "RetryPolicy",
    "Timeouts",
]