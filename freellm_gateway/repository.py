import hashlib
import json
import secrets
from datetime import datetime, timezone

from .db import Database
from .models import (
    AppCredential,
    Application,
    AuditEvent,
    Chunk,
    Document,
    HealthStatus,
    KnowledgeBase,
    ModelRoute,
    Provider,
    Tenant,
    UsageRecord,
)

DEFAULT_TENANT_ID = "default"
DEFAULT_TENANT_CODE = "default"
DEFAULT_TENANT_NAME = "Default Tenant"


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


class Repository:
    def __init__(self, database: Database):
        self.database = database

    def initialize(self) -> None:
        self.database.initialize()
        self.ensure_default_tenant()

    def ensure_default_tenant(self) -> Tenant:
        existing = self.get_tenant(DEFAULT_TENANT_ID)
        if existing:
            return existing
        tenant = Tenant(id=DEFAULT_TENANT_ID, code=DEFAULT_TENANT_CODE, name=DEFAULT_TENANT_NAME, status="active")
        self.save_tenant(tenant)
        return tenant

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
                   public_docs_url, free_summary, catalog_status, version, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET provider_id=excluded.provider_id,
                     remote_model=excluded.remote_model, priority=excluded.priority,
                     capabilities=excluded.capabilities, enabled=excluded.enabled,
                     health=excluded.health, display_name=excluded.display_name,
                     credential_ref=excluded.credential_ref, endpoint=excluded.endpoint,
                     public_url=excluded.public_url, public_docs_url=excluded.public_docs_url,
                     free_summary=excluded.free_summary, catalog_status=excluded.catalog_status,
                     version=excluded.version, status=excluded.status""",
                (route.id, route.provider_id, route.remote_model, route.priority,
                 json.dumps(sorted(route.capabilities)), int(route.enabled), route.health.value,
                 route.display_name, route.credential_ref, route.endpoint, route.public_url,
                 route.public_docs_url, route.free_summary, route.catalog_status, route.version, route.status),
            )

    def list_routes(self) -> list[ModelRoute]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT * FROM routes ORDER BY priority, id").fetchall()
        return [self._row_to_route(row) for row in rows]

    def delete_route(self, route_id: str) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute("DELETE FROM routes WHERE id = ?", (route_id,))
        return cursor.rowcount > 0

    def _row_to_route(self, row) -> ModelRoute:
        keys = row.keys()
        version = row["version"] if "version" in keys else "v1"
        status = row["status"] if "status" in keys else "running"
        return ModelRoute(
            id=row["id"], provider_id=row["provider_id"], remote_model=row["remote_model"],
            priority=row["priority"], capabilities=frozenset(json.loads(row["capabilities"])),
            enabled=bool(row["enabled"]), health=HealthStatus(row["health"]),
            display_name=row["display_name"], credential_ref=row["credential_ref"],
            endpoint=row["endpoint"], public_url=row["public_url"],
            public_docs_url=row["public_docs_url"], free_summary=row["free_summary"],
            catalog_status=row["catalog_status"], version=version or "v1", status=status or "running",
        )

    def save_tenant(self, tenant: Tenant) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO tenants(id, code, name, status) VALUES (?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET code=excluded.code, name=excluded.name, status=excluded.status""",
                (tenant.id, tenant.code, tenant.name, tenant.status),
            )

    def get_tenant(self, tenant_id: str) -> Tenant | None:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
        if row is None:
            return None
        return Tenant(id=row["id"], code=row["code"], name=row["name"], status=row["status"])

    def list_tenants(self) -> list[Tenant]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT * FROM tenants ORDER BY code").fetchall()
        return [Tenant(id=row["id"], code=row["code"], name=row["name"], status=row["status"]) for row in rows]

    def save_application(self, app: Application) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO applications(id, tenant_id, name, status, description, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET tenant_id=excluded.tenant_id, name=excluded.name,
                     status=excluded.status, description=excluded.description""",
                (app.id, app.tenant_id, app.name, app.status, app.description, app.created_at or _utcnow()),
            )

    def get_application(self, app_id: str) -> Application | None:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
        if row is None:
            return None
        return Application(id=row["id"], tenant_id=row["tenant_id"], name=row["name"],
                           status=row["status"], description=row["description"], created_at=row["created_at"])

    def list_applications(self, tenant_id: str | None = None) -> list[Application]:
        with self.database.connect() as connection:
            if tenant_id:
                rows = connection.execute("SELECT * FROM applications WHERE tenant_id = ? ORDER BY created_at DESC", (tenant_id,)).fetchall()
            else:
                rows = connection.execute("SELECT * FROM applications ORDER BY created_at DESC").fetchall()
        return [Application(id=row["id"], tenant_id=row["tenant_id"], name=row["name"],
                            status=row["status"], description=row["description"], created_at=row["created_at"]) for row in rows]

    def delete_application(self, app_id: str) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute("DELETE FROM applications WHERE id = ?", (app_id,))
        return cursor.rowcount > 0

    def create_app_credential(self, app_id: str, key_id: str | None = None) -> tuple[AppCredential, str]:
        key_id = key_id or f"flk_{secrets.token_urlsafe(12)}"
        plaintext = secrets.token_urlsafe(32)
        secret_hash = _hash_secret(plaintext)
        now = _utcnow()
        cred = AppCredential(id=secrets.token_urlsafe(12), app_id=app_id, key_id=key_id,
                             secret_hash=secret_hash, status="active", created_at=now)
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO app_credentials(id, app_id, key_id, secret_hash, status, created_at, expire_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (cred.id, cred.app_id, cred.key_id, cred.secret_hash, cred.status, cred.created_at, cred.expire_at),
            )
        return cred, plaintext

    def list_app_credentials(self, app_id: str) -> list[AppCredential]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT * FROM app_credentials WHERE app_id = ? ORDER BY created_at DESC", (app_id,)).fetchall()
        return [AppCredential(id=row["id"], app_id=row["app_id"], key_id=row["key_id"], secret_hash=row["secret_hash"],
                              status=row["status"], created_at=row["created_at"], expire_at=row["expire_at"]) for row in rows]

    def revoke_app_credential(self, credential_id: str) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute("UPDATE app_credentials SET status = 'revoked' WHERE id = ?", (credential_id,))
        return cursor.rowcount > 0

    def find_credential_by_key_id(self, key_id: str) -> AppCredential | None:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM app_credentials WHERE key_id = ? AND status = 'active'", (key_id,)).fetchone()
        if row is None:
            return None
        return AppCredential(id=row["id"], app_id=row["app_id"], key_id=row["key_id"], secret_hash=row["secret_hash"],
                             status=row["status"], created_at=row["created_at"], expire_at=row["expire_at"])

    def verify_app_secret(self, key_id: str, secret: str) -> AppCredential | None:
        cred = self.find_credential_by_key_id(key_id)
        if cred is None or cred.secret_hash != _hash_secret(secret):
            return None
        return cred

    def save_audit_event(self, event: AuditEvent) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO audit_events(
                   request_id, tenant_id, app_id, endpoint, model, route_id,
                   status_code, latency_ms, prompt_tokens, completion_tokens,
                   total_tokens, error_kind, created_at, meta_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (event.request_id, event.tenant_id, event.app_id, event.endpoint, event.model, event.route_id,
                 event.status_code, event.latency_ms, event.prompt_tokens, event.completion_tokens,
                 event.total_tokens, event.error_kind, event.created_at, event.meta_json),
            )

    def list_audit_events(self, limit: int = 50, offset: int = 0, request_id: str | None = None, app_id: str | None = None) -> list[AuditEvent]:
        clauses, params = [], []
        if request_id:
            clauses.append("request_id = ?"); params.append(request_id)
        if app_id:
            clauses.append("app_id = ?"); params.append(app_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.extend([limit, offset])
        with self.database.connect() as connection:
            rows = connection.execute(f"SELECT * FROM audit_events{where} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?", params).fetchall()
        return [AuditEvent(request_id=row["request_id"], tenant_id=row["tenant_id"], app_id=row["app_id"], endpoint=row["endpoint"],
                           model=row["model"], route_id=row["route_id"], status_code=row["status_code"], latency_ms=row["latency_ms"],
                           prompt_tokens=row["prompt_tokens"], completion_tokens=row["completion_tokens"], total_tokens=row["total_tokens"],
                           error_kind=row["error_kind"], created_at=row["created_at"], meta_json=row["meta_json"]) for row in rows]

    def count_audit_events(self) -> int:
        with self.database.connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS c FROM audit_events").fetchone()
        return int(row["c"])

    def save_usage_record(self, record: UsageRecord) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO usage_records(
                   request_id, tenant_id, app_id, model, route_id,
                   prompt_tokens, completion_tokens, total_tokens, latency_ms, success, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (record.request_id, record.tenant_id, record.app_id, record.model, record.route_id,
                 record.prompt_tokens, record.completion_tokens, record.total_tokens,
                 record.latency_ms, int(record.success), record.created_at),
            )

    def usage_summary(self, days: int = 7) -> dict:
        with self.database.connect() as connection:
            total_row = connection.execute(
                """SELECT COUNT(*) AS calls, COALESCE(SUM(total_tokens), 0) AS tokens,
                     COALESCE(SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END), 0) AS success_calls,
                     COALESCE(AVG(latency_ms), 0) AS avg_latency
                   FROM usage_records WHERE created_at >= datetime('now', ?)""", (f"-{days} days",)).fetchone()
            by_model = connection.execute(
                """SELECT model, COUNT(*) AS calls, COALESCE(SUM(total_tokens), 0) AS tokens,
                     COALESCE(AVG(latency_ms), 0) AS avg_latency
                   FROM usage_records WHERE created_at >= datetime('now', ?)
                   GROUP BY model ORDER BY calls DESC LIMIT 20""", (f"-{days} days",)).fetchall()
            by_day = connection.execute(
                """SELECT date(created_at) AS day, COUNT(*) AS calls, COALESCE(SUM(total_tokens), 0) AS tokens
                   FROM usage_records WHERE created_at >= datetime('now', ?)
                   GROUP BY date(created_at) ORDER BY day""", (f"-{days} days",)).fetchall()
        calls = int(total_row["calls"] or 0)
        success = int(total_row["success_calls"] or 0)
        return {
            "days": days, "total_calls": calls, "success_calls": success,
            "success_rate": round(success / calls * 100, 1) if calls else 0.0,
            "total_tokens": int(total_row["tokens"] or 0),
            "avg_latency_ms": round(float(total_row["avg_latency"] or 0), 1),
            "by_model": [{"model": row["model"] or "unknown", "calls": int(row["calls"]),
                          "tokens": int(row["tokens"]), "avg_latency_ms": round(float(row["avg_latency"]), 1)} for row in by_model],
            "by_day": [{"day": row["day"], "calls": int(row["calls"]), "tokens": int(row["tokens"])} for row in by_day],
        }

    def save_knowledge_base(self, kb: KnowledgeBase) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO knowledge_bases(id, tenant_id, name, description, status, embedding_model_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name, description=excluded.description,
                     status=excluded.status, embedding_model_id=excluded.embedding_model_id""",
                (kb.id, kb.tenant_id, kb.name, kb.description, kb.status, kb.embedding_model_id, kb.created_at or _utcnow()),
            )

    def get_knowledge_base(self, kb_id: str) -> KnowledgeBase | None:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM knowledge_bases WHERE id = ?", (kb_id,)).fetchone()
        if row is None:
            return None
        return KnowledgeBase(id=row["id"], tenant_id=row["tenant_id"], name=row["name"], description=row["description"],
                             status=row["status"], embedding_model_id=row["embedding_model_id"], created_at=row["created_at"])

    def list_knowledge_bases(self, tenant_id: str | None = None) -> list[KnowledgeBase]:
        with self.database.connect() as connection:
            if tenant_id:
                rows = connection.execute("SELECT * FROM knowledge_bases WHERE tenant_id = ? ORDER BY created_at DESC", (tenant_id,)).fetchall()
            else:
                rows = connection.execute("SELECT * FROM knowledge_bases ORDER BY created_at DESC").fetchall()
        return [KnowledgeBase(id=row["id"], tenant_id=row["tenant_id"], name=row["name"], description=row["description"],
                              status=row["status"], embedding_model_id=row["embedding_model_id"], created_at=row["created_at"]) for row in rows]

    def delete_knowledge_base(self, kb_id: str) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute("DELETE FROM knowledge_bases WHERE id = ?", (kb_id,))
        return cursor.rowcount > 0

    def save_document(self, doc: Document) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO documents(id, kb_id, title, filename, content_type, status, sha256,
                   char_count, chunk_count, error_message, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET title=excluded.title, filename=excluded.filename,
                     content_type=excluded.content_type, status=excluded.status, sha256=excluded.sha256,
                     char_count=excluded.char_count, chunk_count=excluded.chunk_count,
                     error_message=excluded.error_message, updated_at=excluded.updated_at""",
                (doc.id, doc.kb_id, doc.title, doc.filename, doc.content_type, doc.status, doc.sha256,
                 doc.char_count, doc.chunk_count, doc.error_message, doc.created_at or _utcnow(), doc.updated_at or _utcnow()),
            )

    def save_document_blob(self, document_id: str, text_content: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO document_blobs(document_id, text_content) VALUES (?, ?)
                   ON CONFLICT(document_id) DO UPDATE SET text_content=excluded.text_content""",
                (document_id, text_content),
            )

    def get_document_blob(self, document_id: str) -> str | None:
        with self.database.connect() as connection:
            row = connection.execute("SELECT text_content FROM document_blobs WHERE document_id = ?", (document_id,)).fetchone()
        return row["text_content"] if row else None

    def get_document(self, document_id: str) -> Document | None:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_document(row)

    def list_documents(self, kb_id: str) -> list[Document]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT * FROM documents WHERE kb_id = ? ORDER BY created_at DESC", (kb_id,)).fetchall()
        return [self._row_to_document(row) for row in rows]

    def delete_document(self, document_id: str) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        return cursor.rowcount > 0

    def _row_to_document(self, row) -> Document:
        return Document(id=row["id"], kb_id=row["kb_id"], title=row["title"], filename=row["filename"],
                        content_type=row["content_type"], status=row["status"], sha256=row["sha256"],
                        char_count=row["char_count"], chunk_count=row["chunk_count"],
                        error_message=row["error_message"], created_at=row["created_at"], updated_at=row["updated_at"])

    def replace_chunks(self, document_id: str, kb_id: str, chunks: list[Chunk]) -> None:
        with self.database.connect() as connection:
            connection.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
            for ch in chunks:
                connection.execute(
                    """INSERT INTO chunks(id, document_id, kb_id, ordinal, content, content_hash, token_estimate, embedding_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (ch.id, ch.document_id, ch.kb_id, ch.ordinal, ch.content, ch.content_hash, ch.token_estimate, getattr(ch, "embedding_json", None)),
                )

    def list_chunks_for_kb(self, kb_id: str) -> list[Chunk]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT * FROM chunks WHERE kb_id = ? ORDER BY document_id, ordinal", (kb_id,)).fetchall()
        return [Chunk(id=row["id"], document_id=row["document_id"], kb_id=row["kb_id"], ordinal=row["ordinal"],
                      content=row["content"], content_hash=row["content_hash"], token_estimate=row["token_estimate"],
                      embedding_json=row["embedding_json"] if "embedding_json" in row.keys() else None) for row in rows]

    def get_chunks_by_ids(self, chunk_ids: list[str]) -> list[Chunk]:
        if not chunk_ids:
            return []
        placeholders = ",".join("?" * len(chunk_ids))
        with self.database.connect() as connection:
            rows = connection.execute(f"SELECT * FROM chunks WHERE id IN ({placeholders})", chunk_ids).fetchall()
        by_id = {row["id"]: Chunk(id=row["id"], document_id=row["document_id"], kb_id=row["kb_id"], ordinal=row["ordinal"],
                                   content=row["content"], content_hash=row["content_hash"], token_estimate=row["token_estimate"],
                                   embedding_json=row["embedding_json"] if "embedding_json" in row.keys() else None) for row in rows}
        return [by_id[i] for i in chunk_ids if i in by_id]

    def count_documents(self, kb_id: str | None = None) -> int:
        with self.database.connect() as connection:
            if kb_id:
                row = connection.execute("SELECT COUNT(*) AS c FROM documents WHERE kb_id = ?", (kb_id,)).fetchone()
            else:
                row = connection.execute("SELECT COUNT(*) AS c FROM documents").fetchone()
        return int(row["c"])
