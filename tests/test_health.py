from freellm_gateway.health import (
    HealthState,
    ProbeResult,
    RoutePolicy,
    is_eligible,
    record_probe,
)
from freellm_gateway.models import HealthStatus


def test_rate_limit_is_skipped_during_cooldown_and_recovers_after_success():
    policy = RoutePolicy(failure_threshold=2, cooldown_seconds=30)
    state = HealthState()

    state = record_probe(
        state, ProbeResult(ok=False, error_kind="rate_limited"), now=100, policy=policy
    )
    assert state.status == HealthStatus.RATE_LIMITED
    assert not is_eligible(state, now=110)

    state = record_probe(
        state, ProbeResult(ok=True, first_token_ms=120, total_ms=300), now=131, policy=policy
    )
    assert state.status == HealthStatus.HEALTHY
    assert is_eligible(state, now=131)


def test_repeated_failures_open_circuit_and_single_slow_probe_does_not_permanently_disable():
    policy = RoutePolicy(failure_threshold=2, cooldown_seconds=10, max_total_ms=500)
    state = HealthState()

    state = record_probe(
        state, ProbeResult(ok=False, error_kind="timeout"), now=1, policy=policy
    )
    assert state.status == HealthStatus.FAILED
    state = record_probe(
        state, ProbeResult(ok=False, error_kind="timeout"), now=2, policy=policy
    )
    assert state.status == HealthStatus.COOLDOWN
    assert state.cooldown_until == 12

    state = record_probe(
        state, ProbeResult(ok=True, first_token_ms=50, total_ms=100), now=13, policy=policy
    )
    assert state.status == HealthStatus.HEALTHY

    state = record_probe(
        state, ProbeResult(ok=True, first_token_ms=50, total_ms=800), now=14, policy=policy
    )
    assert state.status == HealthStatus.SLOW
