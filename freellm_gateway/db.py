import sqlite3
from pathlib import Path


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS providers (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    protocol TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    official_url TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS routes (
                    id TEXT PRIMARY KEY,
                    provider_id TEXT NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
                    remote_model TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    capabilities TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    health TEXT NOT NULL,
                    display_name TEXT,
                    credential_ref TEXT,
                    endpoint TEXT,
                    reasoning_effort TEXT,
                    public_url TEXT,
                    public_docs_url TEXT,
                    free_summary TEXT,
                    catalog_status TEXT NOT NULL,
                    input_price_per_million REAL,
                    output_price_per_million REAL,
                    pricing_currency TEXT NOT NULL DEFAULT 'USD'
                );
                CREATE TABLE IF NOT EXISTS tenants (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS applications (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    key_prefix TEXT NOT NULL,
                    key_salt TEXT NOT NULL,
                    key_hash TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_applications_tenant ON applications(tenant_id);
                CREATE TABLE IF NOT EXISTS quota_policies (
                    scope_type TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    token_limit INTEGER,
                    cost_limit_micros INTEGER,
                    currency TEXT NOT NULL DEFAULT 'USD',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(scope_type, scope_id)
                );
                CREATE TABLE IF NOT EXISTS usage_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL DEFAULT 'system',
                    application_id TEXT NOT NULL DEFAULT 'legacy-global',
                    route_id TEXT,
                    provider_id TEXT,
                    remote_model TEXT,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    elapsed_ms INTEGER NOT NULL DEFAULT 0,
                    stream INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    estimated_cost_micros INTEGER,
                    cost_currency TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_usage_created_at ON usage_records(created_at);
                CREATE INDEX IF NOT EXISTS idx_usage_model ON usage_records(remote_model);
                CREATE INDEX IF NOT EXISTS idx_usage_provider ON usage_records(provider_id);
                """
            )
            route_columns = {row["name"] for row in connection.execute("PRAGMA table_info(routes)")}
            route_additions = {
                "reasoning_effort": "TEXT",
                "input_price_per_million": "REAL",
                "output_price_per_million": "REAL",
                "pricing_currency": "TEXT NOT NULL DEFAULT 'USD'",
            }
            for name, ddl in route_additions.items():
                if name not in route_columns:
                    connection.execute(f"ALTER TABLE routes ADD COLUMN {name} {ddl}")

            usage_columns = {row["name"] for row in connection.execute("PRAGMA table_info(usage_records)")}
            if "tenant_id" not in usage_columns:
                connection.execute(
                    "ALTER TABLE usage_records ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'system'"
                )
            if "application_id" not in usage_columns:
                connection.execute(
                    "ALTER TABLE usage_records ADD COLUMN application_id TEXT NOT NULL DEFAULT 'legacy-global'"
                )
            usage_columns = {row["name"] for row in connection.execute("PRAGMA table_info(usage_records)")}
            usage_additions = {
                "route_id": "TEXT",
                "estimated_cost_micros": "INTEGER",
                "cost_currency": "TEXT",
            }
            for name, ddl in usage_additions.items():
                if name not in usage_columns:
                    connection.execute(f"ALTER TABLE usage_records ADD COLUMN {name} {ddl}")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_usage_tenant ON usage_records(tenant_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_usage_application ON usage_records(application_id)"
            )
