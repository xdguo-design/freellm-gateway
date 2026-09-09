import pytest

from freellm_gateway.failures import classify_failure, parse_retry_after


@pytest.mark.parametrize(
    ("kwargs", "expected_type", "expected_retryable"),
    [
        ({"status_code": 401}, "authentication_error", False),
        ({"status_code": 401, "message": "Invalid API key"}, "authentication_error", False),
        ({"status_code": 403}, "permission_error", False),
        ({"status_code": 403, "message": "you do not have permission"}, "permission_error", False),
        ({"message": "unauthorized access"}, "authentication_error", False),
        ({"status_code": 408}, "timeout", True),
        ({"status_code": 504, "message": "gateway timed out"}, "timeout", True),
        ({"message": "connection etimedout after 30s"}, "timeout", True),
        ({"status_code": 429, "message": "Too Many Requests"}, "rate_limit", True),
        ({"status_code": 429, "message": "quota exceeded for model"}, "quota_exhausted", False),
        ({"status_code": 429, "message": "insufficient balance"}, "quota_exhausted", False),
        ({"status_code": 402, "message": "credits exhausted"}, "quota_exhausted", False),
        ({"status_code": 500}, "provider_5xx", True),
        ({"status_code": 503, "message": "upstream unavailable"}, "provider_5xx", True),
        ({"status_code": 400, "message": "malformed request"}, "invalid_request", False),
        ({"message": "unsupported parameter: max_tokens"}, "invalid_request", False),
        ({"status_code": 404, "message": "model not found"}, "model_unavailable", False),
        ({"message": "connection reset by peer (econnreset)"}, "network_error", True),
        ({"message": "fetch failed"}, "network_error", True),
        ({"status_code": 418}, "unknown", False),
    ],
)
def test_classify_failure_maps_status_and_message_to_taxonomy(kwargs, expected_type, expected_retryable):
    failure = classify_failure(**kwargs)

    assert failure.type == expected_type
    assert failure.retryable is expected_retryable


def test_classify_failure_keeps_status_code_message_and_retry_after():
    failure = classify_failure(status_code=429, message="slow down", retry_after=12.5)

    assert failure.status_code == 429
    assert failure.message == "slow down"
    assert failure.retry_after == 12.5


def test_message_beats_missing_status_for_rate_limit_and_auth():
    assert classify_failure(message="rate limit exceeded, retry after a moment").type == "rate_limit"
    assert classify_failure(code="invalid_api_key").type == "authentication_error"


def test_parse_retry_after_accepts_seconds_and_http_date():
    assert parse_retry_after("30") == 30.0
    assert parse_retry_after("1.5") == 1.5
    assert parse_retry_after("Wed, 21 Oct 2026 07:28:00 GMT", now=1761030000.0) is not None
    assert parse_retry_after("not a date") is None
    assert parse_retry_after(None) is None
    assert parse_retry_after("") is None
