import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone

from .db import Database
from .models import Application, HealthStatus, ModelRoute, Provider, QuotaPolicy, Tenant, UsageRecord


_APP_KEY_PREFIX = "flm-app."
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_LENGTH = 32


def _hash_app_secret(secret: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        secret.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_LENGTH,
    )


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
                   health, display_name, credential_ref, endpoint, reasoning_effort,
                   public_url, public_docs_url, free_summary, catalog_status,
                   input_price_per_million, output_price_per_million, pricing_currency)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET provider_id=excluded.provider_id,
                     remote_model=excluded.remote_model, priority=excluded.priority,
                     capabilities=excluded.capabilities, enabled=excluded.enabled,
                     health=excluded.health, display_name=excluded.display_name,
                     credential_ref=excluded.credential_ref, endpoint=excluded.endpoint,
                     reasoning_effort=excluded.reasoning_effort, public_url=excluded.public_url,
                     public_docs_url=excluded.public_docs_url,
                     free_summary=excluded.free_summary, catalog_status=excluded.catalog_status,
                     input_price_per_million=excluded.input_price_per_million,
                     output_price_per_million=excluded.output_price_per_million,
                     pricing_currency=excluded.pricing_currency""",
                (
                    route.id, route.provider_id, route.remote_model, route.priority,
                    json.dumps(sorted(route.capabilities)), int(route.enabled), route.health.value,
                    route.display_name, route.credential_ref, route.endpoint, route.reasoning_effort, route.public_url,
                    route.public_docs_url, route.free_summary, route.catalog_status,
                    route.input_price_per_million, route.output_price_per_million, route.pricing_currency,
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
                endpoint=row["endpoint"], reasoning_effort=row["reasoning_effort"], public_url=row["public_url"],
                public_docs_url=row["public_docs_url"], free_summary=row["free_summary"],
                catalog_status=row["catalog_status"],
                input_price_per_million=row["input_price_per_million"],
                output_price_per_million=row["output_price_per_million"],
                pricing_currency=row["pricing_currency"] or "USD",
            )
            for row in rows
        ]

    def delete_route(self, route_id: str) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute("DELETE FROM routes WHERE id = ?", (route_id,))
        return cursor.rowcount > 0

    def create_tenant(self, tenant_id: str, name: str) -> Tenant:
        created_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO tenants(id, name, enabled, created_at)
                   VALUES (?, ?, 1, ?)""",
                (tenant_id, name, created_at),
            )
        return Tenant(tenant_id, name, True, created_at)

    def list_tenants(self) -> list[Tenant]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT id, name, enabled, created_at FROM tenants ORDER BY name, id"
            ).fetchall()
        return [
            Tenant(row["id"], row["name"], bool(row["enabled"]), row["created_at"])
            for row in rows
        ]

    def create_application(self, application_id: str, tenant_id: str, name: str) -> tuple[Application, str]:
        created_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        secret = secrets.token_urlsafe(32)
        token = f"{_APP_KEY_PREFIX}{application_id}.{secret}"
        salt = secrets.token_bytes(16)
        digest = _hash_app_secret(secret, salt).hex()
        key_prefix = f"{_APP_KEY_PREFIX}{application_id}.{secret[:6]}"
        with self.database.connect() as connection:
            tenant = connection.execute(
                "SELECT id, enabled FROM tenants WHERE id = ?",
                (tenant_id,),
            ).fetchone()
            if tenant is None:
                raise KeyError(tenant_id)
            if not bool(tenant["enabled"]):
                raise ValueError("tenant_disabled")
            connection.execute(
                """INSERT INTO applications(
                   id, tenant_id, name, key_prefix, key_salt, key_hash, enabled, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
                (
                    application_id,
                    tenant_id,
                    name,
                    key_prefix,
                    salt.hex(),
                    digest,
                    created_at,
                ),
            )
        return Application(application_id, tenant_id, name, key_prefix, True, created_at), token

    def list_applications(self, tenant_id: str | None = None) -> list[Application]:
        query = """SELECT id, tenant_id, name, key_prefix, enabled, created_at
                   FROM applications"""
        params: tuple[str, ...] = ()
        if tenant_id is not None:
            query += " WHERE tenant_id = ?"
            params = (tenant_id,)
        query += " ORDER BY tenant_id, name, id"
        with self.database.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            Application(
                row["id"], row["tenant_id"], row["name"], row["key_prefix"],
                bool(row["enabled"]), row["created_at"],
            )
            for row in rows
        ]

    def verify_application_key(self, token: str) -> Application | None:
        if not isinstance(token, str) or not token.startswith(_APP_KEY_PREFIX):
            return None
        remainder = token[len(_APP_KEY_PREFIX):]
        application_id, separator, secret = remainder.partition(".")
        if not separator or not application_id or not secret:
            return None
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT a.id, a.tenant_id, a.name, a.key_prefix, a.key_salt,
                          a.key_hash, a.enabled, a.created_at, t.enabled AS tenant_enabled
                   FROM applications a
                   JOIN tenants t ON t.id = a.tenant_id
                   WHERE a.id = ?""",
                (application_id,),
            ).fetchone()
        if row is None or not bool(row["enabled"]) or not bool(row["tenant_enabled"]):
            return None
        try:
            actual = _hash_app_secret(secret, bytes.fromhex(row["key_salt"])).hex()
        except (TypeError, ValueError):
            return None
        if not hmac.compare_digest(actual, row["key_hash"]):
            return None
        return Application(
            row["id"], row["tenant_id"], row["name"], row["key_prefix"],
            True, row["created_at"],
        )

    def save_usage_record(self, record: UsageRecord) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO usage_records(
                   request_id, tenant_id, application_id, provider_id, remote_model,
                   prompt_tokens, completion_tokens, total_tokens, elapsed_ms,
                   stream, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.request_id,
                    record.tenant_id,
                    record.application_id,
                    record.provider_id,
                    record.remote_model,
                    record.prompt_tokens,
                    record.completion_tokens,
                    record.total_tokens,
                    record.elapsed_ms,
                    int(record.stream),
                    record.status,
                    record.created_at,
                ),
            )

    def save_usage_from_connection(self, entry: dict) -> UsageRecord | None:
        usage = entry.get("usage")
        if not isinstance(usage, dict):
            return None
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        total_tokens = usage.get("total_tokens")
        if not any(isinstance(value, int) for value in (prompt_tokens, completion_tokens, total_tokens)):
            return None
        prompt = prompt_tokens if isinstance(prompt_tokens, int) else 0
        completion = completion_tokens if isinstance(completion_tokens, int) else 0
        total = total_tokens if isinstance(total_tokens, int) else prompt + completion
        record = UsageRecord(
            request_id=str(entry.get("request_id") or ""),
            tenant_id=str(entry.get("tenant_id") or "system"),
            application_id=str(entry.get("application_id") or "legacy-global"),
            provider_id=entry.get("provider_id") if isinstance(entry.get("provider_id"), str) else None,
            remote_model=entry.get("remote_model") if isinstance(entry.get("remote_model"), str) else None,
            prompt_tokens=max(0, prompt),
            completion_tokens=max(0, completion),
            total_tokens=max(0, total),
            elapsed_ms=max(0, int(entry.get("elapsed_ms") or 0)),
            stream=bool(entry.get("stream")),
            status=str(entry.get("status") or "unknown"),
            created_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        )
        self.save_usage_record(record)
        return record

    def usage_summary(
        self,
        days: int = 7,
        *,
        tenant_id: str | None = None,
        application_id: str | None = None,
        provider_id: str | None = None,
        remote_model: str | None = None,
    ) -> dict:
        days = max(1, min(int(days), 365))
        where, params = self._usage_where(
            days,
            tenant_id=tenant_id,
            application_id=application_id,
            provider_id=provider_id,
            remote_model=remote_model,
        )
        with self.database.connect() as connection:
            totals = connection.execute(
                f"""SELECT
                     COUNT(*) AS calls,
                     COALESCE(SUM(u.prompt_tokens), 0) AS prompt_tokens,
                     COALESCE(SUM(u.completion_tokens), 0) AS completion_tokens,
                     COALESCE(SUM(u.total_tokens), 0) AS total_tokens,
                     COALESCE(AVG(u.elapsed_ms), 0) AS avg_latency_ms
                   FROM usage_records u
                   WHERE {where}""",
                params,
            ).fetchone()
            by_tenant = connection.execute(
                f"""SELECT
                     u.tenant_id,
                     COALESCE(t.name, u.tenant_id, 'unknown') AS tenant_name,
                     COUNT(*) AS calls,
                     COALESCE(SUM(u.prompt_tokens), 0) AS prompt_tokens,
                     COALESCE(SUM(u.completion_tokens), 0) AS completion_tokens,
                     COALESCE(SUM(u.total_tokens), 0) AS total_tokens
                   FROM usage_records u
                   LEFT JOIN tenants t ON t.id = u.tenant_id
                   WHERE {where}
                   GROUP BY u.tenant_id, tenant_name
                   ORDER BY total_tokens DESC, calls DESC
                   LIMIT 50""",
                params,
            ).fetchall()
            by_application = connection.execute(
                f"""SELECT
                     u.tenant_id,
                     u.application_id,
                     COALESCE(a.name, u.application_id, 'unknown') AS application_name,
                     COUNT(*) AS calls,
                     COALESCE(SUM(u.prompt_tokens), 0) AS prompt_tokens,
                     COALESCE(SUM(u.completion_tokens), 0) AS completion_tokens,
                     COALESCE(SUM(u.total_tokens), 0) AS total_tokens
                   FROM usage_records u
                   LEFT JOIN applications a ON a.id = u.application_id
                   WHERE {where}
                   GROUP BY u.tenant_id, u.application_id, application_name
                   ORDER BY total_tokens DESC, calls DESC
                   LIMIT 100""",
                params,
            ).fetchall()
            by_provider = connection.execute(
                f"""SELECT
                     COALESCE(u.provider_id, 'unknown') AS provider_id,
                     COALESCE(p.name, u.provider_id, 'unknown') AS provider_name,
                     COUNT(*) AS calls,
                     COALESCE(SUM(u.prompt_tokens), 0) AS prompt_tokens,
                     COALESCE(SUM(u.completion_tokens), 0) AS completion_tokens,
                     COALESCE(SUM(u.total_tokens), 0) AS total_tokens,
                     COALESCE(AVG(u.elapsed_ms), 0) AS avg_latency_ms
                   FROM usage_records u
                   LEFT JOIN providers p ON p.id = u.provider_id
                   WHERE {where}
                   GROUP BY u.provider_id, provider_name
                   ORDER BY total_tokens DESC, calls DESC
                   LIMIT 50""",
                params,
            ).fetchall()
            by_model = connection.execute(
                f"""SELECT
                     COALESCE(u.remote_model, 'unknown') AS remote_model,
                     COALESCE(u.provider_id, 'unknown') AS provider_id,
                     COUNT(*) AS calls,
                     COALESCE(SUM(u.prompt_tokens), 0) AS prompt_tokens,
                     COALESCE(SUM(u.completion_tokens), 0) AS completion_tokens,
                     COALESCE(SUM(u.total_tokens), 0) AS total_tokens,
                     COALESCE(AVG(u.elapsed_ms), 0) AS avg_latency_ms
                   FROM usage_records u
                   WHERE {where}
                   GROUP BY u.provider_id, u.remote_model
                   ORDER BY total_tokens DESC, calls DESC
                   LIMIT 100""",
                params,
            ).fetchall()
            by_day = connection.execute(
                f"""SELECT
                     date(u.created_at) AS day,
                     COUNT(*) AS calls,
                     COALESCE(SUM(u.prompt_tokens), 0) AS prompt_tokens,
                     COALESCE(SUM(u.completion_tokens), 0) AS completion_tokens,
                     COALESCE(SUM(u.total_tokens), 0) AS total_tokens
                   FROM usage_records u
                   WHERE {where}
                   GROUP BY date(u.created_at)
                   ORDER BY day""",
                params,
            ).fetchall()
            filter_options = self._usage_filter_options(connection, days)
        active_filters = {
            key: value
            for key, value in {
                "tenant_id": tenant_id,
                "application_id": application_id,
                "provider_id": provider_id,
                "remote_model": remote_model,
            }.items()
            if value
        }
        return {
            "days": days,
            "filters": active_filters,
            "filter_options": filter_options,
            "calls": int(totals["calls"] or 0),
            "prompt_tokens": int(totals["prompt_tokens"] or 0),
            "completion_tokens": int(totals["completion_tokens"] or 0),
            "total_tokens": int(totals["total_tokens"] or 0),
            "avg_latency_ms": round(float(totals["avg_latency_ms"] or 0), 1),
            "by_tenant": [self._usage_group_row(row, "tenant_id", "tenant_name") for row in by_tenant],
            "by_application": [
                {
                    **self._usage_group_row(row, "application_id", "application_name"),
                    "tenant_id": row["tenant_id"],
                }
                for row in by_application
            ],
            "by_provider": [
                {
                    **self._usage_group_row(row, "provider_id", "provider_name"),
                    "avg_latency_ms": round(float(row["avg_latency_ms"] or 0), 1),
                }
                for row in by_provider
            ],
            "by_model": [
                {
                    "remote_model": row["remote_model"],
                    "provider_id": row["provider_id"],
                    "calls": int(row["calls"]),
                    "prompt_tokens": int(row["prompt_tokens"]),
                    "completion_tokens": int(row["completion_tokens"]),
                    "total_tokens": int(row["total_tokens"]),
                    "avg_latency_ms": round(float(row["avg_latency_ms"] or 0), 1),
                }
                for row in by_model
            ],
            "by_day": [
                {
                    "day": row["day"],
                    "calls": int(row["calls"]),
                    "prompt_tokens": int(row["prompt_tokens"]),
                    "completion_tokens": int(row["completion_tokens"]),
                    "total_tokens": int(row["total_tokens"]),
                }
                for row in by_day
            ],
        }

    @staticmethod
    def _usage_group_row(row, id_field: str, name_field: str) -> dict:
        return {
            id_field: row[id_field],
            name_field: row[name_field],
            "calls": int(row["calls"]),
            "prompt_tokens": int(row["prompt_tokens"]),
            "completion_tokens": int(row["completion_tokens"]),
            "total_tokens": int(row["total_tokens"]),
        }

    @staticmethod
    def _usage_where(
        days: int,
        *,
        tenant_id: str | None,
        application_id: str | None,
        provider_id: str | None,
        remote_model: str | None,
    ) -> tuple[str, tuple]:
        clauses = ["datetime(u.created_at) >= datetime('now', ?)"]
        params: list[object] = [f"-{days} days"]
        for column, value in (
            ("u.tenant_id", tenant_id),
            ("u.application_id", application_id),
            ("u.provider_id", provider_id),
            ("u.remote_model", remote_model),
        ):
            if value:
                clauses.append(f"{column} = ?")
                params.append(value)
        return " AND ".join(clauses), tuple(params)

    @staticmethod
    def _usage_filter_options(connection, days: int) -> dict:
        window = f"-{days} days"
        tenants = connection.execute(
            """SELECT DISTINCT u.tenant_id AS id, COALESCE(t.name, u.tenant_id) AS name
               FROM usage_records u
               LEFT JOIN tenants t ON t.id = u.tenant_id
               WHERE datetime(u.created_at) >= datetime('now', ?)
               ORDER BY name, id""",
            (window,),
        ).fetchall()
        applications = connection.execute(
            """SELECT DISTINCT u.application_id AS id, u.tenant_id,
                              COALESCE(a.name, u.application_id) AS name
               FROM usage_records u
               LEFT JOIN applications a ON a.id = u.application_id
               WHERE datetime(u.created_at) >= datetime('now', ?)
               ORDER BY u.tenant_id, name, id""",
            (window,),
        ).fetchall()
        providers = connection.execute(
            """SELECT DISTINCT u.provider_id AS id, COALESCE(p.name, u.provider_id) AS name
               FROM usage_records u
               LEFT JOIN providers p ON p.id = u.provider_id
               WHERE datetime(u.created_at) >= datetime('now', ?)
                 AND u.provider_id IS NOT NULL
               ORDER BY name, id""",
            (window,),
        ).fetchall()
        models = connection.execute(
            """SELECT DISTINCT u.remote_model AS id, u.provider_id
               FROM usage_records u
               WHERE datetime(u.created_at) >= datetime('now', ?)
                 AND u.remote_model IS NOT NULL
               ORDER BY u.remote_model, u.provider_id""",
            (window,),
        ).fetchall()
        return {
            "tenants": [{"id": row["id"], "name": row["name"]} for row in tenants],
            "applications": [
                {"id": row["id"], "tenant_id": row["tenant_id"], "name": row["name"]}
                for row in applications
            ],
            "providers": [{"id": row["id"], "name": row["name"]} for row in providers],
            "models": [
                {"id": row["id"], "provider_id": row["provider_id"]}
                for row in models
            ],
        }
