import json

from .db import Database
from .models import HealthStatus, ModelRoute, Provider


class Repository:
    def __init__(self, database: Database):
        self.database = database

    def initialize(self) -> None:
        self.database.initialize()

    def save_provider(self, provider: Provider) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO providers(id, name, protocol, base_url, official_url)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name,
                     protocol=excluded.protocol, base_url=excluded.base_url,
                     official_url=excluded.official_url""",
                (provider.id, provider.name, provider.protocol, provider.base_url, provider.official_url),
            )

    def list_providers(self) -> list[Provider]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT * FROM providers ORDER BY name, id").fetchall()
        return [Provider(row["id"], row["name"], row["protocol"], row["base_url"], row["official_url"]) for row in rows]

    def save_route(self, route: ModelRoute) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO routes(
                   id, provider_id, remote_model, priority, capabilities, enabled,
                   health, display_name, credential_ref, endpoint, public_url,
                   public_docs_url, free_summary, catalog_status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET provider_id=excluded.provider_id,
                     remote_model=excluded.remote_model, priority=excluded.priority,
                     capabilities=excluded.capabilities, enabled=excluded.enabled,
                     health=excluded.health, display_name=excluded.display_name,
                     credential_ref=excluded.credential_ref, endpoint=excluded.endpoint,
                     public_url=excluded.public_url, public_docs_url=excluded.public_docs_url,
                     free_summary=excluded.free_summary, catalog_status=excluded.catalog_status""",
                (
                    route.id, route.provider_id, route.remote_model, route.priority,
                    json.dumps(sorted(route.capabilities)), int(route.enabled), route.health.value,
                    route.display_name, route.credential_ref, route.endpoint, route.public_url,
                    route.public_docs_url, route.free_summary, route.catalog_status,
                ),
            )

    def list_routes(self) -> list[ModelRoute]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT * FROM routes ORDER BY priority, id").fetchall()
        return [
            ModelRoute(
                id=row["id"], provider_id=row["provider_id"], remote_model=row["remote_model"],
                priority=row["priority"], capabilities=frozenset(json.loads(row["capabilities"])),
                enabled=bool(row["enabled"]), health=HealthStatus(row["health"]),
                display_name=row["display_name"], credential_ref=row["credential_ref"],
                endpoint=row["endpoint"], public_url=row["public_url"],
                public_docs_url=row["public_docs_url"], free_summary=row["free_summary"],
                catalog_status=row["catalog_status"],
            )
            for row in rows
        ]
