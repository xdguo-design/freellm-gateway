"""Classify provider failures into a fixed taxonomy.

Ported from OmniRoute's ``failureClassification.ts`` so every layer (health
recording, routing decisions, admin UI) agrees on what went wrong and whether
it can recover on its own. The taxonomy:

    authentication_error  rate_limit        timeout        provider_5xx
    permission_error      quota_exhausted   network_error  invalid_request
    model_unavailable     unknown

Plus ``empty_output`` — a probe-specific outcome for HTTP 200 responses that
carry no text content.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

FAILURE_TYPES = frozenset(
    {
        "authentication_error",
        "permission_error",
        "rate_limit",
        "quota_exhausted",
        "timeout",
        "network_error",
        "provider_5xx",
        "invalid_request",
        "model_unavailable",
        "unknown",
        "empty_output",
    }
)

RETRYABLE_TYPES = frozenset({"rate_limit", "timeout", "network_error", "provider_5xx"})

_AUTH_RE = re.compile(r"invalid.{0,16}(?:key|token)|unauthori[sz]ed|api key|api_key")
_PERMISSION_RE = re.compile(r"permission|forbidden")
_TIMEOUT_RE = re.compile(r"timeout|timed out|etimedout")
_RATE_LIMIT_RE = re.compile(r"rate.?limit|too many requests|retry.?after")
_QUOTA_RE = re.compile(
    r"quota|insufficient balance|credits? exhausted|balance is \$?0|billing cap|额度|余额不足|欠费"
)
_INVALID_REQUEST_RE = re.compile(r"invalid request|malformed|unsupported parameter|unsupported value")
_MODEL_UNAVAILABLE_RE = re.compile(r"model unavailable|model not found|unknown model|does not exist")
_NETWORK_RE = re.compile(r"network|econnreset|econnrefused|enotfound|fetch failed|socket|connection")


@dataclass(frozen=True)
class Failure:
    type: str
    retryable: bool
    status_code: int | None = None
    retry_after: float | None = None
    message: str = ""


def parse_retry_after(value: str | None, now: float | None = None) -> float | None:
    """Parse a Retry-After header (seconds or HTTP-date) into delay seconds."""
    if not value:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    try:
        seconds = float(trimmed)
    except ValueError:
        pass
    else:
        return max(0.0, seconds)
    try:
        target = parsedate_to_datetime(trimmed)
    except (TypeError, ValueError):
        return None
    if target is None:
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    current = datetime.fromtimestamp(now, tz=timezone.utc) if now is not None else datetime.now(timezone.utc)
    return max(0.0, (target - current).total_seconds())


def classify_failure(
    status_code: int | None = None,
    code: str | None = None,
    message: str | None = None,
    retry_after: float | None = None,
) -> Failure:
    normalized = f"{code or ''} {message or ''}".lower().strip()
    failure_type = _classify(status_code, normalized)
    return Failure(
        type=failure_type,
        retryable=failure_type in RETRYABLE_TYPES,
        status_code=status_code,
        retry_after=retry_after,
        message=(message or "").strip() or (code or ""),
    )


def _classify(status_code: int | None, normalized: str) -> str:
    if status_code in {401, 403} or _AUTH_RE.search(normalized):
        if status_code == 403 or _PERMISSION_RE.search(normalized):
            return "permission_error"
        return "authentication_error"
    if status_code in {408, 504} or _TIMEOUT_RE.search(normalized):
        return "timeout"
    if status_code in {429, 402} or _RATE_LIMIT_RE.search(normalized):
        if _QUOTA_RE.search(normalized):
            return "quota_exhausted"
        return "rate_limit"
    if status_code is not None and status_code >= 500:
        return "provider_5xx"
    if status_code == 400 or _INVALID_REQUEST_RE.search(normalized):
        return "invalid_request"
    if status_code == 404 or _MODEL_UNAVAILABLE_RE.search(normalized):
        return "model_unavailable"
    if _NETWORK_RE.search(normalized):
        return "network_error"
    return "unknown"
