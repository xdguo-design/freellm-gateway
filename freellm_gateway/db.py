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
                    public_url TEXT,
                    public_docs_url TEXT,
                    free_summary TEXT,
                    catalog_status TEXT NOT NULL,
                    version TEXT NOT NULL DEFAULT 'v1',
                    status TEXT NOT NULL DEFAULT 'running'
                );
                CREATE TABLE IF NOT EXISTS tenants (
                    id TEXT PRIMARY KEY,
                    code TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active'
                );
                CREATE TABLE IF NOT EXISTS applications (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    description TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS app_credentials (
                    id TEXT PRIMARY KEY,
                    app_id TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
                    key_id TEXT NOT NULL UNIQUE,
                    secret_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    expire_at TEXT
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    tenant_id TEXT,
                    app_id TEXT,
                    endpoint TEXT NOT NULL,
                    model TEXT,
                    route_id TEXT,
                    status_code INTEGER NOT NULL,
                    latency_ms INTEGER,
                    prompt_tokens INTEGER,
                    completion_tokens INTEGER,
                    total_tokens INTEGER,
                    error_kind TEXT,
                    created_at TEXT NOT NULL,
                    meta_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_audit_request_id ON audit_events(request_id);
                CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_events(created_at);
                CREATE INDEX IF NOT EXISTS idx_audit_app_id ON audit_events(app_id);
                CREATE TABLE IF NOT EXISTS usage_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    tenant_id TEXT,
                    app_id TEXT,
                    model TEXT,
                    route_id TEXT,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    latency_ms INTEGER NOT NULL DEFAULT 0,
                    success INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_usage_created_at ON usage_records(created_at);
                CREATE INDEX IF NOT EXISTS idx_usage_app_id ON usage_records(app_id);
                CREATE INDEX IF NOT EXISTS idx_usage_model ON usage_records(model);
                """
            )
            self._ensure_columns(connection)

    def _ensure_columns(self, connection: sqlite3.Connection) -> None:
        cols = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(routes)").fetchall()
        }
        if "version" not in cols:
            connection.execute(
                "ALTER TABLE routes ADD COLUMN version TEXT NOT NULL DEFAULT 'v1'"
            )
        if "status" not in cols:
            connection.execute(
                "ALTER TABLE routes ADD COLUMN status TEXT NOT NULL DEFAULT 'running'"
            )
