from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ProviderConfig:
    id: str
    name: str
    base_url: str
    api_key_env: str = ""
    enabled: bool = True
    priority: int = 100
    timeout_s: float = 60.0
    max_retries: int = 2
    headers: dict[str, str] = field(default_factory=dict)
    models: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)


@dataclass
class ModelRoute:
    model: str
    provider_id: str
    upstream_model: str = ""
    enabled: bool = True
    weight: int = 100


@dataclass
class HealthSnapshot:
    provider_id: str
    ok: bool
    latency_ms: float = 0.0
    error: str = ""
    checked_at: float = 0.0


@dataclass
class Tenant:
    id: str
    name: str
    created_at: float = 0.0
    status: str = "active"  # active | disabled


@dataclass
class Application:
    id: str
    tenant_id: str
    name: str
    description: str = ""
    created_at: float = 0.0
    status: str = "active"  # active | disabled


@dataclass
class AppCredential:
    id: str
    app_id: str
    tenant_id: str
    name: str
    key_prefix: str
    key_hash: str
    created_at: float = 0.0
    revoked_at: Optional[float] = None
    last_used_at: Optional[float] = None
    # plaintext only returned once at creation; never persisted
    plaintext_key: Optional[str] = None


@dataclass
class AuditEvent:
    id: str
    request_id: str
    tenant_id: str
    app_id: str
    route: str
    method: str
    model: str = ""
    provider_id: str = ""
    status_code: int = 0
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    error_type: str = ""
    error_message: str = ""
    created_at: float = 0.0
    meta_json: str = "{}"


@dataclass
class UsageRecord:
    id: str
    tenant_id: str
    app_id: str
    model: str
    provider_id: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    request_count: int = 1
    success_count: int = 0
    error_count: int = 0
    day: str = ""  # YYYY-MM-DD
    created_at: float = 0.0


@dataclass
class KnowledgeBase:
    id: str
    tenant_id: str
    name: str
    description: str = ""
    created_at: float = 0.0
    status: str = "active"  # active | disabled
    doc_count: int = 0
    chunk_count: int = 0


@dataclass
class Document:
    id: str
    kb_id: str
    tenant_id: str
    title: str
    source: str = ""  # filename or url
    content_type: str = "text/plain"
    status: str = "ready"  # pending | ready | error
    error_message: str = ""
    char_count: int = 0
    chunk_count: int = 0
    created_at: float = 0.0
    updated_at: float = 0.0


@dataclass
class Chunk:
    id: str
    doc_id: str
    kb_id: str
    tenant_id: str
    ordinal: int
    text: str
    token_estimate: int = 0
    created_at: float = 0.0
    # JSON list[float]; optional for Hybrid RAG
    embedding_json: str = ""
