from dataclasses import dataclass, replace

from .models import HealthStatus


@dataclass(frozen=True)
class RoutePolicy:
    failure_threshold: int = 3
    cooldown_seconds: int = 60
    max_first_token_ms: int | None = None
    max_total_ms: int | None = None


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    first_token_ms: int | None = None
    total_ms: int | None = None
    error_kind: str | None = None


@dataclass(frozen=True)
class HealthState:
    status: HealthStatus = HealthStatus.HEALTHY
    consecutive_failures: int = 0
    cooldown_until: float | None = None
    last_first_token_ms: int | None = None
    last_total_ms: int | None = None
    last_error_kind: str | None = None


def _is_slow(result: ProbeResult, policy: RoutePolicy) -> bool:
    return bool(
        (policy.max_first_token_ms is not None
         and result.first_token_ms is not None
         and result.first_token_ms > policy.max_first_token_ms)
        or (policy.max_total_ms is not None
            and result.total_ms is not None
            and result.total_ms > policy.max_total_ms)
    )


def record_probe(
    state: HealthState, result: ProbeResult, now: float, policy: RoutePolicy
) -> HealthState:
    common = dict(
        last_first_token_ms=result.first_token_ms,
        last_total_ms=result.total_ms,
        last_error_kind=result.error_kind,
    )
    if result.ok:
        return replace(
            state,
            status=HealthStatus.SLOW if _is_slow(result, policy) else HealthStatus.HEALTHY,
            consecutive_failures=0,
            cooldown_until=None,
            **common,
        )

    failures = state.consecutive_failures + 1
    if result.error_kind == "rate_limited":
        status = HealthStatus.RATE_LIMITED
    elif result.error_kind == "quota_exhausted":
        status = HealthStatus.QUOTA_EXHAUSTED
    elif failures >= policy.failure_threshold:
        status = HealthStatus.COOLDOWN
    else:
        status = HealthStatus.FAILED
    cooldown_until = (
        now + policy.cooldown_seconds
        if status in {HealthStatus.RATE_LIMITED, HealthStatus.QUOTA_EXHAUSTED, HealthStatus.COOLDOWN}
        else None
    )
    return replace(
        state,
        status=status,
        consecutive_failures=failures,
        cooldown_until=cooldown_until,
        **common,
    )


def is_eligible(state: HealthState, now: float) -> bool:
    if state.status in {HealthStatus.DISABLED, HealthStatus.SLOW, HealthStatus.FAILED}:
        return False
    if state.status in {
        HealthStatus.RATE_LIMITED,
        HealthStatus.QUOTA_EXHAUSTED,
        HealthStatus.COOLDOWN,
    }:
        return state.cooldown_until is not None and now >= state.cooldown_until
    return state.status == HealthStatus.HEALTHY


def effective_status(state: HealthState, now: float) -> HealthStatus:
    if state.status in {
        HealthStatus.RATE_LIMITED,
        HealthStatus.QUOTA_EXHAUSTED,
        HealthStatus.COOLDOWN,
    } and state.cooldown_until is not None and now >= state.cooldown_until:
        return HealthStatus.HEALTHY
    return state.status
