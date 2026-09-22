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
    # Structured model metadata used by capability/cost routing.
    context_window: int | None = None
    max_output_tokens: int | None = None
    input_price_per_million: float | None = None
    output_price_per_million: float | None = None
    pricing_currency: str = "USD"


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


@dataclass(frozen=True)
class KnowledgeBase:
    id: str
    tenant_id: str
    name: str
    description: str | None = None
    status: str = "active"  # active | archived
    embedding_model_id: str | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class Document:
    id: str
    kb_id: str
    title: str
    filename: str | None
    content_type: str
    status: str  # uploaded | parsing | ready | failed
    sha256: str | None = None
    char_count: int = 0
    chunk_count: int = 0
    error_message: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class Chunk:
    id: str
    document_id: str
    kb_id: str
    ordinal: int
    content: str
    content_hash: str
    token_estimate: int = 0
    embedding_json: str | None = None  # JSON list[float]; optional for Hybrid RAG
