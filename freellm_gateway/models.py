from dataclasses import dataclass, field
from enum import Enum


SUPPORTED_PROVIDER_PROTOCOLS = frozenset({"openai", "anthropic", "gemini"})


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    SLOW = "slow"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"
    QUOTA_EXHAUSTED = "quota_exhausted"
    COOLDOWN = "cooldown"
    DISABLED = "disabled"


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    protocol: str
    base_url: str
    official_url: str


@dataclass(frozen=True)
class ModelRoute:
    id: str
    provider_id: str
    remote_model: str
    priority: int
    capabilities: frozenset[str] = field(default_factory=lambda: frozenset({"chat"}))
    enabled: bool = True
    health: HealthStatus = HealthStatus.HEALTHY
    display_name: str | None = None
    credential_ref: str | None = None
    endpoint: str | None = None
    public_url: str | None = None
    public_docs_url: str | None = None
    free_summary: str | None = None
    catalog_status: str = "draft"
    reasoning_effort: str | None = None
    input_price_per_million: float | None = None
    output_price_per_million: float | None = None
    pricing_currency: str = "USD"



@dataclass(frozen=True)
class Tenant:
    id: str
    name: str
    enabled: bool = True
    created_at: str | None = None


@dataclass(frozen=True)
class Application:
    id: str
    tenant_id: str
    name: str
    key_prefix: str
    enabled: bool = True
    created_at: str | None = None


@dataclass(frozen=True)
class RequestIdentity:
    tenant_id: str
    application_id: str
    auth_type: str


@dataclass(frozen=True)
class QuotaPolicy:
    scope_type: str
    scope_id: str
    token_limit: int | None = None
    cost_limit_micros: int | None = None
    currency: str = "USD"
    warning_threshold_percent: float = 80.0
    updated_at: str | None = None


@dataclass(frozen=True)
class UsageRecord:
    request_id: str
    tenant_id: str
    application_id: str
    route_id: str | None
    provider_id: str | None
    remote_model: str | None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    elapsed_ms: int
    stream: bool
    status: str
    estimated_cost_micros: int | None
    cost_currency: str | None
    created_at: str
