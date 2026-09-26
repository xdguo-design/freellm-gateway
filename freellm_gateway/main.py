from .api import create_app
from .config import Settings
from .db import Database
from .repository import Repository
from .runtime import build_gateway
from .secrets import secret_store_from_env


def build_default_app():
    settings = Settings.from_env()
    repository = Repository(Database(settings.database))
    repository.initialize()
    explicit_secret_store = bool(
        __import__("os").getenv("FREELLM_GATEWAY_SECRETS_FILE")
        or __import__("os").getenv("FREELLM_GATEWAY_SECRET_KEY")
    )
    try:
        secrets = secret_store_from_env()
        gateway = build_gateway(repository, secrets)
    except RuntimeError:
        if explicit_secret_store:
            raise
        secrets = None
        gateway = None
    return create_app(
        gateway=gateway,
        repository=repository,
        secrets=secrets,
        api_token=settings.api_token,
        admin_token=settings.admin_token,
        catalog_output=settings.catalog_output,
        site_repo=settings.site_repo,
        catalog_source=settings.catalog_source,
    )


app = build_default_app()
