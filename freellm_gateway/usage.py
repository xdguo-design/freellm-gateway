"""Provider-neutral usage events owned by the FreeLLM control plane."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_tokens: int = 0
    reasoning_tokens: int = 0
    image_tokens: int = 0


@dataclass(frozen=True)
class UsageEvent:
    request_id: str
    tenant_id: str
    application_id: str
    model_id: str
    usage: TokenUsage
    estimated_cost: Decimal = Decimal("0")
    occurred_at: datetime | None = None

    def timestamp(self) -> datetime:
        return self.occurred_at or datetime.now(timezone.utc)
