import os
import sys
from secrets import token_urlsafe
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8765
    database: Path = Path("data/gateway.sqlite3")
    catalog_output: Path = Path("data/catalog-export.json")
    site_repo: Path | None = None
    api_token: str | None = None
    admin_token: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        api_token = os.getenv("FREELLM_GATEWAY_API_TOKEN")
        admin_token = os.getenv("FREELLM_GATEWAY_ADMIN_TOKEN")
        if not api_token:
            api_token = token_urlsafe(32)
            print(f"FREELLM_GATEWAY_API_TOKEN={api_token}", file=sys.stderr)
        if not admin_token:
            admin_token = token_urlsafe(32)
            print(f"FREELLM_GATEWAY_ADMIN_TOKEN={admin_token}", file=sys.stderr)
        return cls(
            host=os.getenv("FREELLM_GATEWAY_HOST", cls.host),
            port=int(os.getenv("FREELLM_GATEWAY_PORT", str(cls.port))),
            database=Path(os.getenv("FREELLM_GATEWAY_DB", str(cls.database))),
            catalog_output=Path(os.getenv("FREELLM_GATEWAY_CATALOG_OUTPUT", str(cls.catalog_output))),
            site_repo=Path(os.environ["FREELLM_GATEWAY_SITE_REPO"]) if os.getenv("FREELLM_GATEWAY_SITE_REPO") else None,
            api_token=api_token,
            admin_token=admin_token,
        )
