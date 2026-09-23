import json
from datetime import datetime, timezone

from .db import Database
from .models import HealthStatus, ModelRoute, Provider, UsageRecord


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
                   public_url, public_docs_url, free_summary, catalog_status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET provider_id=excluded.provider_id,
                     remote_model=excluded.remote_model, priority=excluded.priority,
                     capabilities=excluded.capabilities, enabled=excluded.enabled,
                     health=excluded.health, display_name=excluded.display_name,
                     credential_ref=excluded.credential_ref, endpoint=excluded.endpoint,
                     reasoning_effort=excluded.reasoning_effort, public_url=excluded.public_url,
                     public_docs_url=excluded.public_docs_url,
                     free_summary=excluded.free_summary, catalog_status=excluded.catalog_status""",
                (
                    route.id, route.provider_id, route.remote_model, route.priority,
                    json.dumps(sorted(route.capabilities)), int(route.enabled), route.health.value,
                    route.display_name, route.credential_ref, route.endpoint, route.reasoning_effort, route.public_url,
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
                endpoint=row["endpoint"], reasoning_effort=row["reasoning_effort"], public_url=row["public_url"],
                public_docs_url=row["public_docs_url"], free_summary=row["free_summary"],
                catalog_status=row["catalog_status"],
            )
            for row in rows
        ]

    def delete_route(self, route_id: str) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute("DELETE FROM routes WHERE id = ?", (route_id,))
        return cursor.rowcount > 0


    def save_usage_record(self, record: UsageRecord) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO usage_records(
                   request_id, provider_id, remote_model, prompt_tokens,
                   completion_tokens, total_tokens, elapsed_ms, stream, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.request_id,
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

    def usage_summary(self, days: int = 7) -> dict:
        days = max(1, min(int(days), 365))
        window = f"-{days} days"
        with self.database.connect() as connection:
            totals = connection.execute(
                """SELECT
                     COUNT(*) AS calls,
                     COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                     COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                     COALESCE(SUM(total_tokens), 0) AS total_tokens,
                     COALESCE(AVG(elapsed_ms), 0) AS avg_latency_ms
                   FROM usage_records
                   WHERE datetime(created_at) >= datetime('now', ?)""",
                (window,),
            ).fetchone()
            by_model = connection.execute(
                """SELECT
                     COALESCE(remote_model, 'unknown') AS remote_model,
                     COALESCE(provider_id, 'unknown') AS provider_id,
                     COUNT(*) AS calls,
                     COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                     COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                     COALESCE(SUM(total_tokens), 0) AS total_tokens,
                     COALESCE(AVG(elapsed_ms), 0) AS avg_latency_ms
                   FROM usage_records
                   WHERE datetime(created_at) >= datetime('now', ?)
                   GROUP BY provider_id, remote_model
                   ORDER BY total_tokens DESC, calls DESC
                   LIMIT 50""",
                (window,),
            ).fetchall()
            by_day = connection.execute(
                """SELECT
                     date(created_at) AS day,
                     COUNT(*) AS calls,
                     COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                     COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                     COALESCE(SUM(total_tokens), 0) AS total_tokens
                   FROM usage_records
                   WHERE datetime(created_at) >= datetime('now', ?)
                   GROUP BY date(created_at)
                   ORDER BY day""",
                (window,),
            ).fetchall()
        return {
            "days": days,
            "calls": int(totals["calls"] or 0),
            "prompt_tokens": int(totals["prompt_tokens"] or 0),
            "completion_tokens": int(totals["completion_tokens"] or 0),
            "total_tokens": int(totals["total_tokens"] or 0),
            "avg_latency_ms": round(float(totals["avg_latency_ms"] or 0), 1),
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
