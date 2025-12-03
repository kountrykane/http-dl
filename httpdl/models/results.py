from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional, List, Any


@dataclass
class DataDownloadResult:
    """Result from DataDownload - contains processed/decoded content."""

    url: str
    status_code: int = 200
    headers: Mapping[str, str] = field(default_factory=dict)
    content_type: Optional[str] = None
    kind: str = "unknown"  # "json" | "xml" | "html" | "sgml" | "atom" | "binary" | "archive" | "unknown"
    text: Optional[str] = None  # decoded for text-like kinds
    bytes_: Optional[bytes] = None  # for archive/binary/unknown
    charset: Optional[str] = None
    duration_ms: int = 0
    size_bytes: int = 0
    sniff_note: Optional[str] = None
    redirect_chain: list[str] = field(default_factory=list)  # URLs visited during redirects


@dataclass
class FileDownloadResult:
    """
    Result from FileDownload - contains raw file data or file path.

    Note: This is a temporary implementation. In production, the file_path
    will be replaced with object store references (S3 key, Azure blob path, etc.)
    once the document store/object store SDK provider is decided.
    """

    url: str
    status_code: int = 200
    headers: Mapping[str, str] = field(default_factory=dict)
    content_type: Optional[str] = None      # Raw Content-Type header value
    content_encoding: Optional[str] = None  # Raw Content-Encoding (gzip, deflate, etc.)
    kind: Optional[str] = None              # Optional classification for downstream consumers
    file_path: Optional[Path] = None        # Path where file was saved (if saved to disk)
    bytes_: Optional[bytes] = None          # Raw bytes if not saved to disk
    duration_ms: int = 0
    size_bytes: int = 0                     # Size of raw downloaded bytes
    saved_to_disk: bool = False             # Whether the file was saved to disk
    redirect_chain: list[str] = field(default_factory=list)  # URLs visited during redirects
    checksum: Optional[str] = None          # Computed checksum (if requested)
    checksum_type: Optional[str] = None     # Checksum algorithm used (md5, sha256, sha512)
    resumed: bool = False                   # Whether download was resumed from partial file
    etag: Optional[str] = None              # ETag header value for resume support

@dataclass
class BatchDownloadResult:
    """Result of a batch download operation."""

    successful: List[Any]
    failed: List[tuple[str, Exception]]
    total: int

    @property
    def success_rate(self) -> float:
        """Calculate success rate as a percentage."""
        if self.total == 0:
            return 0.0
        return (len(self.successful) / self.total) * 100