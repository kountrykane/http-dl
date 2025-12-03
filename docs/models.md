# Models Guide

This guide documents the dataclasses under `httpdl/models`, covering both
configuration inputs and result payloads returned by download clients.

## Configuration Models (`config.py`)

### `RetryPolicy`

Controls the retry loop in `BaseDownload._do_request_with_retry`.

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `attempts` | `int` | `5` | Total number of additional attempts after the first request. |
| `base_delay_ms` | `int` | `500` | Base delay (milliseconds) used to compute exponential backoff with ±30 % jitter. |
| `respect_retry_after` | `bool` | `True` | When True, 429/503 responses with `Retry-After` headers will pause for the instructed duration. |

### `Timeouts`

Maps directly to `httpx.Timeout`. Adjust per service as needed.

| Field | Type | Default (seconds) | Notes |
| --- | --- | --- | --- |
| `connect` | `float` | `2.0` | Connection establishment timeout. |
| `read` | `float` | `120.0` | Generous window for large filings. |
| `write` | `float` | `10.0` | Controls upload/write phase when POSTing (unused in current clients). |
| `pool` | `float` | `2.0` | How long to wait for a connection from the pool. Doubles as httpx keepalive expiry. |

### `DownloadSettings`

Primary configuration object passed to `DataDownload` and `FileDownload`.

| Field | Type | Default | Scope |
| --- | --- | --- | --- |
| `user_agent` | `str` | `"edgarSYS j.jansenbravo@gmail.com"` | Per-instance header. Customize for attribution and contact info. |
| `base_url` | `str` | `"https://www.sec.gov"` | Not actively used yet; reserved for future relative URL helpers. |
| `requests_per_second` | `int` | `8` | Process-wide rate cap shared across all clients. |
| `max_concurrency_per_host` | `int` | `6` | Per-host semaphore size. |
| `http2` | `bool` | `False` | Enables HTTP/2 in httpx when target supports it. |
| `follow_redirects` | `bool` | `True` | Enable automatic redirect following for 301, 302, 303, 307, 308 status codes. |
| `max_redirects` | `int` | `20` | Maximum number of redirects to follow before raising `TooManyRedirectsError`. |
| `retry` | `RetryPolicy` | new instance | Injects retry behavior. |
| `timeouts` | `Timeouts` | new instance | Injects timeout behavior. |
| `accept` | `str` | `"*/*"` | Default Accept header. |
| `accept_encoding` | `str` | `"gzip, deflate, br"` | Negotiates transfer compression. |
| `connection` | `str` | `"keep-alive"` | Encourages connection reuse. |
| `max_decompressed_size_mb` | `int` | `200` | Fail-fast guard enforced by `DataDownload`. |

Because `DownloadSettings` uses `default_factory`, each client gets its own copy
of `RetryPolicy` and `Timeouts`, avoiding shared state between modules.

## Result Models (`result.py`)

### `DataDownloadResult`

Represents processed content returned by `DataDownload.download`.

| Field | Type | Description |
| --- | --- | --- |
| `url` | `str` | Final URL after redirects. |
| `status_code` | `int` | HTTP status code (guaranteed 200 for successful downloads). |
| `headers` | `Mapping[str, str]` | Response headers snapshot. |
| `content_type` | `str | None` | Normalized media type. |
| `kind` | `str` | Classification: `"json"`, `"xml"`, `"html"`, `"sgml"`, `"atom"`, `"archive"`, `"binary"`, `"unknown"`. |
| `text` | `str | None` | Decoded text for text-like kinds. |
| `bytes_` | `bytes | None` | Raw payload for binary/unknown kinds. |
| `charset` | `str | None` | Charset detected from headers or sniffing. |
| `duration_ms` | `int` | Total wall-clock duration of the request. |
| `size_bytes` | `int` | Size of the decompressed payload. |
| `sniff_note` | `str | None` | Hints about classification/decoding decisions. |
| `redirect_chain` | `list[str]` | List of URLs visited during redirect following (empty if no redirects). |

`text` and `bytes_` are mutually exclusive. When `kind` is text-like, the
client decodes to `text`; otherwise, the raw bytes are retained in `bytes_`.

### `FileDownloadResult`

Captures metadata for raw downloads performed by `FileDownload`, including streaming, resumable downloads, and checksum validation.

| Field | Type | Description |
| --- | --- | --- |
| `url` | `str` | Final URL after redirects. |
| `status_code` | `int` | HTTP status code (200 when successful). |
| `headers` | `Mapping[str, str]` | Response headers snapshot. |
| `content_type` | `str | None` | Raw `Content-Type` header value. |
| `content_encoding` | `str | None` | Raw `Content-Encoding` header (gzip/deflate/etc.). |
| `kind` | `str | None` | Optional classification for downstream consumers. |
| `file_path` | `Path | None` | Filesystem location when streaming to disk. |
| `bytes_` | `bytes | None` | In-memory payload when not saved to disk. |
| `duration_ms` | `int` | Total download time. |
| `size_bytes` | `int` | Total bytes written or buffered. |
| `saved_to_disk` | `bool` | Indicates whether a file was persisted locally. |
| `redirect_chain` | `list[str]` | List of URLs visited during redirect following. |
| `checksum` | `str | None` | Computed checksum value (if checksum validation was requested). |
| `checksum_type` | `str | None` | Checksum algorithm used (`"md5"`, `"sha256"`, or `"sha512"`). |
| `resumed` | `bool` | Whether the download was resumed from a partial file. |
| `etag` | `str | None` | ETag header value from the response (used for resume validation). |

**New in 0.2.0**: FileDownload now includes all streaming features:
- **Resumable downloads**: Set `resume=True` to automatically resume interrupted downloads using ETag validation and HTTP Range headers.
- **Checksum validation**: Specify `checksum_type` and `expected_checksum` to verify file integrity after download.
- **Progress tracking**: Use `progress_callback` for real-time download progress monitoring.

Future integrations (e.g., S3) can replace `file_path` with object-store
identifiers while keeping the rest of the schema stable.

## Choosing Between Models

- Use `DownloadSettings` (with nested `RetryPolicy` and `Timeouts`) to tune
  client behavior.
- Expect `DataDownloadResult` when consuming processed content and rely on its
  `kind`, `text`, and `sniff_note` fields for downstream parsing.
- Expect `FileDownloadResult` when you need file persistence or raw bytes;
  check `saved_to_disk` to branch between local and in-memory handling.

Referencing this document allows you to reduce surface area in
`httpdl/__init__.py` while still providing a clear contract for library users.
