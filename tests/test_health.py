from freellm_gateway.health import (
    HealthState,
    ProbeResult,
    RoutePolicy,
    effective_status,
    is_eligible,
    record_probe,
)
from freellm_gateway.models import HealthStatus


def test_rate_limit_is_skipped_during_backoff_and_recovers_after_success():
    policy = RoutePolicy(failure_threshold=2, backoff_schedule=(30, 300))
    state = HealthState()

    state = record_probe(
        state,
        ProbeResult(ok=False, error_kind="rate_limit", error_retryable=True, rate_limited=True),
        now=100,
        policy=policy,
    )
    assert state.status == HealthStatus.RATE_LIMITED
    assert state.cooldown_until == 130
    assert not is_eligible(state, now=110)
    assert state.last_error_kind == "rate_limit"
    assert state.last_error_retryable is True
    assert state.last_is_quota is False

    state = record_probe(
        state, ProbeResult(ok=True, first_token_ms=120, total_ms=300), now=131, policy=policy
    )
    assert state.status == HealthStatus.HEALTHY
    assert is_eligible(state, now=131)
    assert state.consecutive_failures == 0


def test_backoff_escalates_with_consecutive_failures_and_caps():
    policy = RoutePolicy(failure_threshold=99)
    state = HealthState()

    state = record_probe(state, ProbeResult(ok=False, error_kind="timeout", error_retryable=True), now=0, policy=policy)
    assert state.status == HealthStatus.COOLDOWN
    assert state.cooldown_until == 60

    state = record_probe(state, ProbeResult(ok=False, error_kind="timeout", error_retryable=True), now=1, policy=policy)
    assert state.cooldown_until == 1 + 300

    state = record_probe(state, ProbeResult(ok=False, error_kind="timeout", error_retryable=True), now=2, policy=policy)
    assert state.cooldown_until == 2 + 1800

    state = record_probe(state, ProbeResult(ok=False, error_kind="timeout", error_retryable=True), now=3, policy=policy)
    assert state.cooldown_until == 3 + 7200  # capped at the last step

    state = record_probe(state, ProbeResult(ok=False, error_kind="timeout", error_retryable=True), now=4, policy=policy)
    assert state.cooldown_until == 4 + 7200  # stays at the cap


def test_non_retryable_failures_bench_route_without_cooldown():
    state = record_probe(
        state=HealthState(),
        result=ProbeResult(ok=False, error_kind="authentication_error", error_retryable=False),
        now=10,
        policy=RoutePolicy(),
    )
    assert state.status == HealthStatus.FAILED
    assert state.cooldown_until is None
    assert not is_eligible(state, now=100000)
    assert state.last_error_retryable is False


def test_quota_failure_sets_quota_status_and_flags():
    state = record_probe(
        state=HealthState(),
        result=ProbeResult(ok=False, error_kind="quota_exhausted", is_quota=True, retry_after=45),
        now=0,
        policy=RoutePolicy(),
    )
    assert state.status == HealthStatus.QUOTA_EXHAUSTED
    assert state.last_is_quota is True
    assert state.last_retry_after == 45
    # the server retry-after wins when it is longer than the backoff step
    assert state.cooldown_until == 60


def test_retry_after_extends_backoff_when_longer_than_schedule():
    state = record_probe(
        state=HealthState(),
        result=ProbeResult(ok=False, error_kind="rate_limit", retry_after=900),
        now=0,
        policy=RoutePolicy(),
    )
    assert state.cooldown_until == 900


def test_probe_failures_are_isolated_and_never_bench_the_route():
    policy = RoutePolicy()
    state = HealthState()

    failed = record_probe(
        state,
        ProbeResult(ok=False, error_kind="timeout", error_retryable=True, probe=True),
        now=100,
        policy=policy,
    )
    assert failed.status == HealthStatus.HEALTHY
    assert failed.consecutive_failures == 0
    assert failed.cooldown_until is None
    assert failed.last_error_kind == "timeout"
    assert is_eligible(failed, now=100)

    # repeated probe failures keep the route eligible
    twice = record_probe(failed, ProbeResult(ok=False, error_kind="rate_limit", probe=True), now=200, policy=policy)
    assert twice.status == HealthStatus.HEALTHY
    assert is_eligible(twice, now=200)
    assert twice.last_error_kind == "rate_limit"


def test_probe_success_clears_a_benched_route():
    state = record_probe(
        state=HealthState(),
        result=ProbeResult(ok=False, error_kind="authentication_error"),
        now=0,
        policy=RoutePolicy(),
    )
    assert state.status == HealthStatus.FAILED

    revived = record_probe(
        state,
        ProbeResult(ok=True, first_token_ms=90, total_ms=210, probe=True),
        now=50,
        policy=RoutePolicy(),
    )
    assert revived.status == HealthStatus.HEALTHY
    assert revived.cooldown_until is None
    assert is_eligible(revived, now=50)


def test_cooldown_revsives_to_healthy_via_effective_status():
    state = record_probe(
        state=HealthState(),
        result=ProbeResult(ok=False, error_kind="rate_limit"),
        now=0,
        policy=RoutePolicy(),
    )
    assert state.status == HealthStatus.RATE_LIMITED
    assert effective_status(state, now=10) == HealthStatus.RATE_LIMITED
    assert effective_status(state, now=60) == HealthStatus.HEALTHY
