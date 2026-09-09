from dataclasses import dataclass, replace

from .models import HealthStatus


@dataclass(frozen=True)
class RoutePolicy:
    failure_threshold: int = 3
    backoff_schedule: tuple[int, ...] = (60, 300, 1800, 7200)
    max_first_token_ms: int | None = None
    max_total_ms: int | None = None

    def cooldown_for(self, consecutive_failures: int) -> int:
        if not self.backoff_schedule:
            return 0
        step = min(max(consecutive_failures, 1), len(self.backoff_schedule)) - 1
        return self.backoff_schedule[step]


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    first_token_ms: int | None = None
    total_ms: int | None = None
    error_kind: str | None = None
    error_retryable: bool = False
    rate_limited: bool = False
    is_quota: bool = False
    is_transient: bool = False
    retry_after: float | None = None
    probe: bool = False


@dataclass(frozen=True)
class HealthState:
    status: HealthStatus = HealthStatus.HEALTHY
    consecutive_failures: int = 0
    cooldown_until: float | None = None
    last_first_token_ms: int | None = None
    last_total_ms: int | None = None
    last_error_kind: str | None = None
    last_error_retryable: bool | None = None
    last_is_quota: bool = False
    last_is_transient: bool = False
    last_retry_after: float | None = None


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
        last_error_retryable=None if result.ok else result.error_retryable,
        last_is_quota=False if result.ok else result.is_quota,
        last_is_transient=False if result.ok else result.is_transient,
        last_retry_after=None if result.ok else result.retry_after,
    )
    if result.ok:
        return replace(
            state,
            status=HealthStatus.SLOW if _is_slow(result, policy) else HealthStatus.HEALTHY,
            consecutive_failures=0,
            cooldown_until=None,
            **common,
        )

    if result.probe:
        # Probe isolation: a manual health probe records diagnostics only. It
        # never benches a route, so a broken probe (dead proxy, local network
        # blip) cannot take production traffic down with it.
        return replace(state, **common)

    failures = state.consecutive_failures + 1
    if result.error_kind == "rate_limit":
        status = HealthStatus.RATE_LIMITED
    elif result.error_kind == "quota_exhausted":
        status = HealthStatus.QUOTA_EXHAUSTED
    elif result.error_retryable or failures >= policy.failure_threshold:
        status = HealthStatus.COOLDOWN
    else:
        status = HealthStatus.FAILED
    cooldown_until = None
    if status in {HealthStatus.RATE_LIMITED, HealthStatus.QUOTA_EXHAUSTED, HealthStatus.COOLDOWN}:
        cooldown = policy.cooldown_for(failures)
        if result.retry_after:
            cooldown = max(cooldown, result.retry_after)
        cooldown_until = now + cooldown
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
