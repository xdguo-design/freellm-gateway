import os
from secrets import token_urlsafe
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8765
    database: Path = Path("data/gateway.sqlite3")
    api_token: str | None = None
    admin_token: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            host=os.getenv("FREELLM_GATEWAY_HOST", cls.host),
            port=int(os.getenv("FREELLM_GATEWAY_PORT", str(cls.port))),
            database=Path(os.getenv("FREELLM_GATEWAY_DB", str(cls.database))),
            api_token=os.getenv("FREELLM_GATEWAY_API_TOKEN") or token_urlsafe(32),
            admin_token=os.getenv("FREELLM_GATEWAY_ADMIN_TOKEN") or token_urlsafe(32),
        )
