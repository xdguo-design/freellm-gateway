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
                CREATE TABLE IF NOT EXISTS knowledge_bases (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    embedding_model_id TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    kb_id TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    filename TEXT,
                    content_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    sha256 TEXT,
                    char_count INTEGER NOT NULL DEFAULT 0,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_documents_kb ON documents(kb_id);
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    kb_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    token_estimate INTEGER NOT NULL DEFAULT 0,
                    embedding_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_chunks_kb ON chunks(kb_id);
                CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
                CREATE TABLE IF NOT EXISTS document_blobs (
                    document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
                    text_content TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS execution_policies (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    timeout_ms INTEGER NOT NULL DEFAULT 60000,
                    max_concurrency INTEGER NOT NULL DEFAULT 4,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_execution_policies_tenant ON execution_policies(tenant_id);
                CREATE TABLE IF NOT EXISTS model_groups (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    policy_id TEXT NOT NULL REFERENCES execution_policies(id),
                    description TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_model_groups_tenant ON model_groups(tenant_id);
                CREATE TABLE IF NOT EXISTS model_group_members (
                    group_id TEXT NOT NULL REFERENCES model_groups(id) ON DELETE CASCADE,
                    route_id TEXT NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY(group_id, route_id)
                );
                CREATE INDEX IF NOT EXISTS idx_model_group_members_group ON model_group_members(group_id, position);
                CREATE TABLE IF NOT EXISTS model_runs (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                    app_id TEXT,
                    group_id TEXT NOT NULL REFERENCES model_groups(id) ON DELETE CASCADE,
                    strategy TEXT NOT NULL,
                    status TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    results_json TEXT,
                    error_message TEXT,
                    started_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_model_runs_group ON model_runs(group_id, started_at);
                CREATE INDEX IF NOT EXISTS idx_model_runs_tenant ON model_runs(tenant_id, started_at);
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
        # chunks.embedding_json for Hybrid RAG (existing DBs)
        try:
            chunk_cols = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(chunks)").fetchall()
            }
            if chunk_cols and "embedding_json" not in chunk_cols:
                connection.execute("ALTER TABLE chunks ADD COLUMN embedding_json TEXT")
        except Exception:
            pass
