from .api import create_app
from .config import Settings
from .db import Database
from .repository import Repository
from .runtime import build_gateway
from .secrets import SecretStore


def build_default_app():
    settings = Settings.from_env()
    repository = Repository(Database(settings.database))
    repository.initialize()
    try:
        secrets = SecretStore()
        gateway = build_gateway(repository, secrets)
    except RuntimeError:
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
    )


app = build_default_app()
