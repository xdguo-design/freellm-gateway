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
