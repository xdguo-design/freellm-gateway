import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone
from threading import Lock

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
        self._quota_lock = Lock()
        self._quota_reservations: dict[str, dict] = {}

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

    def save_quota_policy(
        self,
        scope_type: str,
        scope_id: str,
        *,
        token_limit: int | None = None,
        cost_limit_micros: int | None = None,
        currency: str = "USD",
        warning_threshold_percent: float = 80.0,
    ) -> QuotaPolicy:
        if scope_type not in {"tenant", "application"}:
            raise ValueError("scope_type")
        if token_limit is not None and token_limit < 0:
            raise ValueError("token_limit")
        if cost_limit_micros is not None and cost_limit_micros < 0:
            raise ValueError("cost_limit_micros")
        currency = currency.strip().upper()
        if not currency or len(currency) > 8:
            raise ValueError("currency")
        if not 0 <= float(warning_threshold_percent) <= 100:
            raise ValueError("warning_threshold_percent")
        warning_threshold_percent = float(warning_threshold_percent)
        updated_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        with self.database.connect() as connection:
            if scope_type == "tenant":
                target = connection.execute(
                    "SELECT 1 FROM tenants WHERE id = ?",
                    (scope_id,),
                ).fetchone()
            else:
                target = connection.execute(
                    "SELECT 1 FROM applications WHERE id = ?",
                    (scope_id,),
                ).fetchone()
            if target is None:
                raise KeyError(scope_id)
            connection.execute(
                """INSERT INTO quota_policies(
                   scope_type, scope_id, token_limit, cost_limit_micros, currency,
                   warning_threshold_percent, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(scope_type, scope_id) DO UPDATE SET
                     token_limit=excluded.token_limit,
                     cost_limit_micros=excluded.cost_limit_micros,
                     currency=excluded.currency,
                     warning_threshold_percent=excluded.warning_threshold_percent,
                     updated_at=excluded.updated_at""",
                (
                    scope_type, scope_id, token_limit, cost_limit_micros, currency,
                    warning_threshold_percent, updated_at,
                ),
            )
        return QuotaPolicy(
            scope_type,
            scope_id,
            token_limit,
            cost_limit_micros,
            currency,
            warning_threshold_percent,
            updated_at,
        )

    def list_quota_policies(self) -> list[QuotaPolicy]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT scope_type, scope_id, token_limit, cost_limit_micros,
                          currency, warning_threshold_percent, updated_at
                   FROM quota_policies
                   ORDER BY scope_type, scope_id"""
            ).fetchall()
        return [
            QuotaPolicy(
                row["scope_type"],
                row["scope_id"],
                row["token_limit"],
                row["cost_limit_micros"],
                row["currency"],
                float(row["warning_threshold_percent"]),
                row["updated_at"],
            )
            for row in rows
        ]

    def quota_policy(self, scope_type: str, scope_id: str) -> QuotaPolicy | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT scope_type, scope_id, token_limit, cost_limit_micros,
                          currency, warning_threshold_percent, updated_at
                   FROM quota_policies
                   WHERE scope_type = ? AND scope_id = ?""",
                (scope_type, scope_id),
            ).fetchone()
        if row is None:
            return None
        return QuotaPolicy(
            row["scope_type"],
            row["scope_id"],
            row["token_limit"],
            row["cost_limit_micros"],
            row["currency"],
            float(row["warning_threshold_percent"]),
            row["updated_at"],
        )

    def reserve_quota(
        self,
        tenant_id: str,
        application_id: str,
        *,
        projected_tokens: int = 0,
        projected_costs: dict[str, int] | None = None,
        token_projection_complete: bool = True,
        cost_projection_complete: bool = False,
    ) -> dict:
        projected_tokens = max(0, int(projected_tokens))
        projected_costs = {
            str(currency).upper(): max(0, int(micros))
            for currency, micros in (projected_costs or {}).items()
        }
        with self._quota_lock:
            with self.database.connect() as connection:
                statuses = self._quota_statuses(connection)

            scopes = [
                ("tenant", tenant_id, statuses["tenant"].get(tenant_id)),
                ("application", application_id, statuses["application"].get(application_id)),
            ]
            warnings = []
            checks = []
            violation = None

            for scope_type, scope_id, status in scopes:
                if status is None:
                    continue
                pending_tokens, pending_costs = self._pending_quota_usage(scope_type, scope_id)
                used_tokens = int(status["used_tokens"]) + pending_tokens
                token_limit = status["token_limit"]
                token_after = used_tokens + projected_tokens
                threshold = float(status["warning_threshold_percent"])

                if token_limit is not None:
                    token_limit = int(token_limit)
                    token_percent = 100.0 if token_limit == 0 else token_after * 100 / token_limit
                    if not token_projection_complete:
                        violation = {
                            "code": "quota_output_limit_required",
                            "scope_type": scope_type,
                            "scope_id": scope_id,
                            "resource": "tokens",
                            "used": used_tokens,
                            "projected": projected_tokens,
                            "limit": token_limit,
                            "remaining": max(0, token_limit - used_tokens),
                            "period_end": statuses["period"]["end"],
                            "required_field": "max_tokens or max_completion_tokens",
                        }
                    elif used_tokens >= token_limit or token_after > token_limit:
                        violation = {
                            "code": "quota_exceeded",
                            "scope_type": scope_type,
                            "scope_id": scope_id,
                            "resource": "tokens",
                            "used": used_tokens,
                            "projected": projected_tokens,
                            "limit": token_limit,
                            "remaining": max(0, token_limit - used_tokens),
                            "period_end": statuses["period"]["end"],
                        }
                    elif token_percent >= threshold:
                        warnings.append({
                            "scope_type": scope_type,
                            "scope_id": scope_id,
                            "resource": "tokens",
                            "utilization_percent": round(token_percent, 2),
                            "threshold_percent": threshold,
                            "remaining_after_request": max(0, token_limit - token_after),
                        })

                currency = status["currency"]
                used_cost = int(status["used_cost_micros"]) + pending_costs.get(currency, 0)
                cost_limit = status["cost_limit_micros"]
                projected_cost = projected_costs.get(currency)
                cost_after = used_cost + (projected_cost or 0)
                if cost_limit is not None:
                    cost_limit = int(cost_limit)
                    if not cost_projection_complete:
                        candidate = {
                            "code": "quota_cost_projection_unavailable",
                            "scope_type": scope_type,
                            "scope_id": scope_id,
                            "resource": "cost",
                            "currency": currency,
                            "used_micros": used_cost,
                            "projected_micros": projected_cost,
                            "limit_micros": cost_limit,
                            "remaining_micros": max(0, cost_limit - used_cost),
                            "period_end": statuses["period"]["end"],
                            "projection_complete": False,
                        }
                        if violation is None:
                            violation = candidate
                    elif used_cost >= cost_limit or (
                        projected_cost is not None
                        and cost_after > cost_limit
                    ):
                        candidate = {
                            "code": "quota_exceeded",
                            "scope_type": scope_type,
                            "scope_id": scope_id,
                            "resource": "cost",
                            "currency": currency,
                            "used_micros": used_cost,
                            "projected_micros": projected_cost,
                            "limit_micros": cost_limit,
                            "remaining_micros": max(0, cost_limit - used_cost),
                            "period_end": statuses["period"]["end"],
                            "projection_complete": cost_projection_complete,
                        }
                        if violation is None:
                            violation = candidate
                    elif cost_projection_complete and projected_cost is not None:
                        cost_percent = 100.0 if cost_limit == 0 else cost_after * 100 / cost_limit
                        if cost_percent >= threshold:
                            warnings.append({
                                "scope_type": scope_type,
                                "scope_id": scope_id,
                                "resource": "cost",
                                "currency": currency,
                                "utilization_percent": round(cost_percent, 2),
                                "threshold_percent": threshold,
                                "remaining_after_request_micros": max(0, cost_limit - cost_after),
                            })

                checks.append({
                    "scope_type": scope_type,
                    "scope_id": scope_id,
                    "warning_threshold_percent": threshold,
                    "projected_tokens": projected_tokens,
                    "projected_costs": projected_costs,
                    "token_projection_complete": token_projection_complete,
                    "cost_projection_complete": cost_projection_complete,
                })

            if violation is not None:
                return {
                    "allowed": False,
                    "reservation_id": None,
                    "violation": violation,
                    "warnings": warnings,
                    "checks": checks,
                    "period": statuses["period"],
                }

            reservation_id = None
            if checks:
                reservation_id = secrets.token_hex(12)
                self._quota_reservations[reservation_id] = {
                    "tenant_id": tenant_id,
                    "application_id": application_id,
                    "projected_tokens": projected_tokens,
                    "projected_costs": (
                        projected_costs if cost_projection_complete else {}
                    ),
                }
            return {
                "allowed": True,
                "reservation_id": reservation_id,
                "violation": None,
                "warnings": warnings,
                "checks": checks,
                "period": statuses["period"],
            }

    def release_quota_reservation(self, reservation_id: str | None) -> None:
        if not reservation_id:
            return
        with self._quota_lock:
            self._quota_reservations.pop(reservation_id, None)

    def _pending_quota_usage(self, scope_type: str, scope_id: str) -> tuple[int, dict[str, int]]:
        tokens = 0
        costs: dict[str, int] = {}
        for reservation in self._quota_reservations.values():
            matches = (
                reservation["tenant_id"] == scope_id
                if scope_type == "tenant"
                else reservation["application_id"] == scope_id
            )
            if not matches:
                continue
            tokens += int(reservation["projected_tokens"])
            for currency, micros in reservation["projected_costs"].items():
                costs[currency] = costs.get(currency, 0) + int(micros)
        return tokens, costs

    def save_usage_record(self, record: UsageRecord) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO usage_records(
                   request_id, tenant_id, application_id, route_id, provider_id,
                   remote_model, prompt_tokens, completion_tokens, total_tokens,
                   elapsed_ms, stream, status, estimated_cost_micros,
                   cost_currency, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.request_id,
                    record.tenant_id,
                    record.application_id,
                    record.route_id,
                    record.provider_id,
                    record.remote_model,
                    record.prompt_tokens,
                    record.completion_tokens,
                    record.total_tokens,
                    record.elapsed_ms,
                    int(record.stream),
                    record.status,
                    record.estimated_cost_micros,
                    record.cost_currency,
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
        route_id = entry.get("route_id") if isinstance(entry.get("route_id"), str) else None
        estimated_cost_micros, cost_currency = self._estimate_usage_cost(
            route_id,
            max(0, prompt),
            max(0, completion),
        )
        record = UsageRecord(
            request_id=str(entry.get("request_id") or ""),
            tenant_id=str(entry.get("tenant_id") or "system"),
            application_id=str(entry.get("application_id") or "legacy-global"),
            route_id=route_id,
            provider_id=entry.get("provider_id") if isinstance(entry.get("provider_id"), str) else None,
            remote_model=entry.get("remote_model") if isinstance(entry.get("remote_model"), str) else None,
            prompt_tokens=max(0, prompt),
            completion_tokens=max(0, completion),
            total_tokens=max(0, total),
            elapsed_ms=max(0, int(entry.get("elapsed_ms") or 0)),
            stream=bool(entry.get("stream")),
            status=str(entry.get("status") or "unknown"),
            estimated_cost_micros=estimated_cost_micros,
            cost_currency=cost_currency,
            created_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        )
        self.save_usage_record(record)
        return record

    def _estimate_usage_cost(
        self,
        route_id: str | None,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> tuple[int | None, str | None]:
        if route_id is None:
            return None, None
        with self.database.connect() as connection:
            route = connection.execute(
                """SELECT input_price_per_million, output_price_per_million,
                          pricing_currency
                   FROM routes
                   WHERE id = ?""",
                (route_id,),
            ).fetchone()
        if route is None:
            return None, None
        input_price = route["input_price_per_million"]
        output_price = route["output_price_per_million"]
        if prompt_tokens > 0 and input_price is None:
            return None, None
        if completion_tokens > 0 and output_price is None:
            return None, None
        micros = round(
            prompt_tokens * float(input_price or 0)
            + completion_tokens * float(output_price or 0)
        )
        return max(0, micros), (route["pricing_currency"] or "USD").upper()

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
                     COALESCE(AVG(u.elapsed_ms), 0) AS avg_latency_ms,
                     SUM(CASE WHEN u.estimated_cost_micros IS NOT NULL THEN 1 ELSE 0 END) AS priced_calls,
                     SUM(CASE WHEN u.estimated_cost_micros IS NULL THEN 1 ELSE 0 END) AS unpriced_calls
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
            costs = self._cost_breakdown(connection, where, params)
            tenant_costs = self._cost_breakdown(connection, where, params, "u.tenant_id")
            application_costs = self._cost_breakdown(connection, where, params, "u.application_id")
            provider_costs = self._cost_breakdown(connection, where, params, "u.provider_id")
            model_costs = self._cost_breakdown(
                connection, where, params, "u.provider_id || '::' || u.remote_model"
            )
            day_costs = self._cost_breakdown(connection, where, params, "date(u.created_at)")
            quota_status = self._quota_statuses(connection)
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
        tenant_rows = [
            {
                **self._usage_group_row(row, "tenant_id", "tenant_name"),
                **tenant_costs.get(row["tenant_id"], self._empty_cost_summary()),
                "quota": quota_status["tenant"].get(row["tenant_id"]),
            }
            for row in by_tenant
        ]
        application_rows = [
            {
                **self._usage_group_row(row, "application_id", "application_name"),
                "tenant_id": row["tenant_id"],
                **application_costs.get(row["application_id"], self._empty_cost_summary()),
                "quota": quota_status["application"].get(row["application_id"]),
            }
            for row in by_application
        ]
        provider_rows = [
            {
                **self._usage_group_row(row, "provider_id", "provider_name"),
                "avg_latency_ms": round(float(row["avg_latency_ms"] or 0), 1),
                **provider_costs.get(row["provider_id"], self._empty_cost_summary()),
            }
            for row in by_provider
        ]
        model_rows = [
            {
                "remote_model": row["remote_model"],
                "provider_id": row["provider_id"],
                "calls": int(row["calls"]),
                "prompt_tokens": int(row["prompt_tokens"]),
                "completion_tokens": int(row["completion_tokens"]),
                "total_tokens": int(row["total_tokens"]),
                "avg_latency_ms": round(float(row["avg_latency_ms"] or 0), 1),
                **model_costs.get(
                    f"{row['provider_id']}::{row['remote_model']}",
                    self._empty_cost_summary(),
                ),
            }
            for row in by_model
        ]
        day_rows = [
            {
                "day": row["day"],
                "calls": int(row["calls"]),
                "prompt_tokens": int(row["prompt_tokens"]),
                "completion_tokens": int(row["completion_tokens"]),
                "total_tokens": int(row["total_tokens"]),
                **day_costs.get(row["day"], self._empty_cost_summary()),
            }
            for row in by_day
        ]
        if not provider_id and not remote_model:
            tenant_names = {
                item["id"]: item["name"]
                for item in filter_options.get("tenants", [])
            }
            application_options = {
                item["id"]: item
                for item in filter_options.get("applications", [])
            }
            tenant_ids = {row["tenant_id"] for row in tenant_rows}
            for scope_id, quota in quota_status["tenant"].items():
                if scope_id in tenant_ids:
                    continue
                if tenant_id and scope_id != tenant_id:
                    continue
                tenant_rows.append({
                    "tenant_id": scope_id,
                    "tenant_name": tenant_names.get(scope_id, scope_id),
                    "calls": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    **self._empty_cost_summary(),
                    "quota": quota,
                })
            application_ids = {row["application_id"] for row in application_rows}
            for scope_id, quota in quota_status["application"].items():
                if scope_id in application_ids:
                    continue
                option = application_options.get(scope_id, {})
                if application_id and scope_id != application_id:
                    continue
                if tenant_id and option.get("tenant_id") != tenant_id:
                    continue
                application_rows.append({
                    "application_id": scope_id,
                    "application_name": option.get("name", scope_id),
                    "tenant_id": option.get("tenant_id", "unknown"),
                    "calls": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    **self._empty_cost_summary(),
                    "quota": quota,
                })
            tenant_rows.sort(key=lambda row: (-row["total_tokens"], row["tenant_id"]))
            application_rows.sort(
                key=lambda row: (-row["total_tokens"], row["application_id"])
            )

        selected_quota = None
        if application_id:
            selected_quota = quota_status["application"].get(application_id)
        elif tenant_id:
            selected_quota = quota_status["tenant"].get(tenant_id)

        return {
            "days": days,
            "filters": active_filters,
            "filter_options": filter_options,
            "calls": int(totals["calls"] or 0),
            "prompt_tokens": int(totals["prompt_tokens"] or 0),
            "completion_tokens": int(totals["completion_tokens"] or 0),
            "total_tokens": int(totals["total_tokens"] or 0),
            "avg_latency_ms": round(float(totals["avg_latency_ms"] or 0), 1),
            "priced_calls": int(totals["priced_calls"] or 0),
            "unpriced_calls": int(totals["unpriced_calls"] or 0),
            **costs,
            "quota_period": quota_status["period"],
            "selected_quota": selected_quota,
            "by_tenant": tenant_rows,
            "by_application": application_rows,
            "by_provider": provider_rows,
            "by_model": model_rows,
            "by_day": day_rows,
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
    def _empty_cost_summary() -> dict:
        return {
            "estimated_costs": [],
            "priced_calls": 0,
            "unpriced_calls": 0,
        }

    @staticmethod
    def _cost_breakdown(connection, where: str, params: tuple, group_expression: str | None = None):
        group_select = f"{group_expression} AS group_key, " if group_expression else ""
        group_by = f"GROUP BY group_key, u.cost_currency" if group_expression else "GROUP BY u.cost_currency"
        rows = connection.execute(
            f"""SELECT
                 {group_select}
                 u.cost_currency,
                 COALESCE(SUM(u.estimated_cost_micros), 0) AS cost_micros,
                 SUM(CASE WHEN u.estimated_cost_micros IS NOT NULL THEN 1 ELSE 0 END) AS priced_calls,
                 SUM(CASE WHEN u.estimated_cost_micros IS NULL THEN 1 ELSE 0 END) AS unpriced_calls
               FROM usage_records u
               WHERE {where}
               {group_by}""",
            params,
        ).fetchall()

        def build(items) -> dict:
            costs = [
                {
                    "currency": row["cost_currency"],
                    "micros": int(row["cost_micros"] or 0),
                    "amount": round(int(row["cost_micros"] or 0) / 1_000_000, 6),
                }
                for row in items
                if row["cost_currency"] is not None and int(row["priced_calls"] or 0) > 0
            ]
            return {
                "estimated_costs": costs,
                "priced_calls": sum(int(row["priced_calls"] or 0) for row in items),
                "unpriced_calls": sum(int(row["unpriced_calls"] or 0) for row in items),
            }

        if group_expression is None:
            return build(rows)
        grouped: dict[str, list] = {}
        for row in rows:
            key = row["group_key"]
            if key is None:
                key = "unknown"
            grouped.setdefault(str(key), []).append(row)
        return {key: build(items) for key, items in grouped.items()}

    def _quota_statuses(self, connection) -> dict:
        now = datetime.now(timezone.utc)
        period_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        if now.month == 12:
            period_end = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            period_end = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
        start = period_start.isoformat(timespec="seconds")
        end = period_end.isoformat(timespec="seconds")

        policies = connection.execute(
            """SELECT scope_type, scope_id, token_limit, cost_limit_micros,
                      currency, warning_threshold_percent, updated_at
               FROM quota_policies"""
        ).fetchall()
        token_rows = connection.execute(
            """SELECT tenant_id, application_id, COALESCE(SUM(total_tokens), 0) AS used_tokens
               FROM usage_records
               WHERE datetime(created_at) >= datetime(?)
                 AND datetime(created_at) < datetime(?)
               GROUP BY tenant_id, application_id""",
            (start, end),
        ).fetchall()
        cost_rows = connection.execute(
            """SELECT tenant_id, application_id, cost_currency,
                      COALESCE(SUM(estimated_cost_micros), 0) AS used_cost_micros,
                      SUM(CASE WHEN estimated_cost_micros IS NOT NULL THEN 1 ELSE 0 END) AS priced_calls,
                      SUM(CASE WHEN estimated_cost_micros IS NULL THEN 1 ELSE 0 END) AS unpriced_calls
               FROM usage_records
               WHERE datetime(created_at) >= datetime(?)
                 AND datetime(created_at) < datetime(?)
               GROUP BY tenant_id, application_id, cost_currency""",
            (start, end),
        ).fetchall()

        tenant_tokens: dict[str, int] = {}
        app_tokens: dict[str, int] = {}
        for row in token_rows:
            tenant_tokens[row["tenant_id"]] = tenant_tokens.get(row["tenant_id"], 0) + int(row["used_tokens"] or 0)
            app_tokens[row["application_id"]] = app_tokens.get(row["application_id"], 0) + int(row["used_tokens"] or 0)

        tenant_costs: dict[str, dict[str, int]] = {}
        app_costs: dict[str, dict[str, int]] = {}
        tenant_unpriced: dict[str, int] = {}
        app_unpriced: dict[str, int] = {}
        tenant_priced_by_currency: dict[str, dict[str, int]] = {}
        app_priced_by_currency: dict[str, dict[str, int]] = {}
        for row in cost_rows:
            currency = row["cost_currency"]
            if currency is not None:
                tenant_costs.setdefault(row["tenant_id"], {})[currency] = (
                    tenant_costs.setdefault(row["tenant_id"], {}).get(currency, 0)
                    + int(row["used_cost_micros"] or 0)
                )
                app_costs.setdefault(row["application_id"], {})[currency] = (
                    app_costs.setdefault(row["application_id"], {}).get(currency, 0)
                    + int(row["used_cost_micros"] or 0)
                )
                tenant_priced_by_currency.setdefault(row["tenant_id"], {})[currency] = (
                    tenant_priced_by_currency.setdefault(row["tenant_id"], {}).get(currency, 0)
                    + int(row["priced_calls"] or 0)
                )
                app_priced_by_currency.setdefault(row["application_id"], {})[currency] = (
                    app_priced_by_currency.setdefault(row["application_id"], {}).get(currency, 0)
                    + int(row["priced_calls"] or 0)
                )
            unpriced = int(row["unpriced_calls"] or 0)
            tenant_unpriced[row["tenant_id"]] = tenant_unpriced.get(row["tenant_id"], 0) + unpriced
            app_unpriced[row["application_id"]] = app_unpriced.get(row["application_id"], 0) + unpriced

        result = {
            "period": {"type": "calendar_month", "start": start, "end": end},
            "tenant": {},
            "application": {},
        }
        for policy in policies:
            scope_type = policy["scope_type"]
            scope_id = policy["scope_id"]
            currency = policy["currency"] or "USD"
            if scope_type == "tenant":
                used_tokens = tenant_tokens.get(scope_id, 0)
                used_cost = tenant_costs.get(scope_id, {}).get(currency, 0)
                unpriced_calls = tenant_unpriced.get(scope_id, 0)
                priced_by_currency = tenant_priced_by_currency.get(scope_id, {})
            else:
                used_tokens = app_tokens.get(scope_id, 0)
                used_cost = app_costs.get(scope_id, {}).get(currency, 0)
                unpriced_calls = app_unpriced.get(scope_id, 0)
                priced_by_currency = app_priced_by_currency.get(scope_id, {})
            other_currency_calls = sum(
                count for cost_currency, count in priced_by_currency.items()
                if cost_currency != currency
            )
            token_limit = policy["token_limit"]
            cost_limit = policy["cost_limit_micros"]
            token_remaining = None if token_limit is None else max(0, int(token_limit) - used_tokens)
            cost_remaining = None if cost_limit is None else max(0, int(cost_limit) - used_cost)
            result[scope_type][scope_id] = {
                "configured": True,
                "scope_type": scope_type,
                "scope_id": scope_id,
                "currency": currency,
                "warning_threshold_percent": float(policy["warning_threshold_percent"]),
                "token_limit": token_limit,
                "used_tokens": used_tokens,
                "remaining_tokens": token_remaining,
                "token_utilization_percent": (
                    None if token_limit in (None, 0)
                    else round(used_tokens * 100 / int(token_limit), 2)
                ),
                "cost_limit_micros": cost_limit,
                "cost_limit": None if cost_limit is None else round(int(cost_limit) / 1_000_000, 6),
                "used_cost_micros": used_cost,
                "used_cost": round(used_cost / 1_000_000, 6),
                "remaining_cost_micros": cost_remaining,
                "remaining_cost": None if cost_remaining is None else round(cost_remaining / 1_000_000, 6),
                "cost_utilization_percent": (
                    None if cost_limit in (None, 0)
                    else round(used_cost * 100 / int(cost_limit), 2)
                ),
                "unpriced_calls": unpriced_calls,
                "other_currency_calls": other_currency_calls,
                "cost_complete": unpriced_calls == 0 and other_currency_calls == 0,
                "token_warning": (
                    token_limit is not None
                    and (
                        100.0 if int(token_limit) == 0
                        else used_tokens * 100 / int(token_limit)
                    ) >= float(policy["warning_threshold_percent"])
                ),
                "cost_warning": (
                    cost_limit is not None
                    and (
                        100.0 if int(cost_limit) == 0
                        else used_cost * 100 / int(cost_limit)
                    ) >= float(policy["warning_threshold_percent"])
                ),
                "token_exceeded": token_limit is not None and used_tokens >= int(token_limit),
                "cost_exceeded": cost_limit is not None and used_cost >= int(cost_limit),
            }
        return result

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
        tenants = connection.execute(
            """SELECT id, name
               FROM tenants
               WHERE enabled = 1
               ORDER BY name, id"""
        ).fetchall()
        applications = connection.execute(
            """SELECT id, tenant_id, name
               FROM applications
               WHERE enabled = 1
               ORDER BY tenant_id, name, id"""
        ).fetchall()
        providers = connection.execute(
            """SELECT id, name
               FROM providers
               ORDER BY name, id"""
        ).fetchall()
        models = connection.execute(
            """SELECT DISTINCT remote_model AS id, provider_id
               FROM routes
               WHERE enabled = 1
               ORDER BY remote_model, provider_id"""
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
