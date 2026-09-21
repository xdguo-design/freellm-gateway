from dataclasses import dataclass, field
from enum import Enum


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
    # Phase-1 platform fields (optional, backward compatible)
    version: str = "v1"
    status: str = "running"  # running | stopped | archived


@dataclass(frozen=True)
class Tenant:
    id: str
    code: str
    name: str
    status: str = "active"  # active | suspended


@dataclass(frozen=True)
class Application:
    id: str
    tenant_id: str
    name: str
    status: str = "active"  # active | disabled
    description: str | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class AppCredential:
    id: str
    app_id: str
    key_id: str
    secret_hash: str
    status: str = "active"  # active | revoked
    created_at: str | None = None
    expire_at: str | None = None
    # secret itself is never stored; only hash. Plaintext shown once at creation.


@dataclass(frozen=True)
class AuditEvent:
    request_id: str
    tenant_id: str | None
    app_id: str | None
    endpoint: str
    model: str | None
    route_id: str | None
    status_code: int
    latency_ms: int | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    error_kind: str | None
    created_at: str
    meta_json: str | None = None


@dataclass(frozen=True)
class UsageRecord:
    request_id: str
    tenant_id: str | None
    app_id: str | None
    model: str | None
    route_id: str | None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int
    success: bool
    created_at: str
