from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from .adapters.base import ProviderError
from .models import ExecutionPolicy, ExecutionStrategy, ModelGroupMember
from .service import ModelGateway


@dataclass(frozen=True)
class ModelExecutionResult:
    route_id: str
    position: int
    status: str
    latency_ms: int
    response: dict[str, Any] | None = None
    error_kind: str | None = None
    error_detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "route_id": self.route_id,
            "position": self.position,
            "status": self.status,
            "latency_ms": self.latency_ms,
        }
        if self.response is not None:
            data["response"] = self.response
        if self.error_kind is not None:
            data["error_kind"] = self.error_kind
        if self.error_detail:
            data["error_detail"] = self.error_detail
        return data


@dataclass(frozen=True)
class GroupExecutionResult:
    strategy: ExecutionStrategy
    status: str
    results: tuple[ModelExecutionResult, ...]

    @property
    def success_count(self) -> int:
        return sum(result.status == "succeeded" for result in self.results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy.value,
            "status": self.status,
            "success_count": self.success_count,
            "results": [result.to_dict() for result in self.results],
        }


class MultiModelExecutor:
    """Execute one request against a configured model group.

    The executor intentionally works on route IDs rather than provider/model names.
    This keeps orchestration separate from provider protocol handling and reuses the
    existing ModelGateway health, capability and adapter logic.
    """

    def __init__(self, gateway: ModelGateway):
        self.gateway = gateway

    async def execute(
        self,
        policy: ExecutionPolicy,
        members: list[ModelGroupMember],
        payload: dict[str, Any],
    ) -> GroupExecutionResult:
        enabled = sorted(
            (member for member in members if member.enabled),
            key=lambda member: (member.position, member.route_id),
        )
        if not enabled:
            raise ValueError("model group has no enabled members")
        if policy.timeout_ms <= 0:
            raise ValueError("execution policy timeout_ms must be positive")
        if policy.max_concurrency <= 0:
            raise ValueError("execution policy max_concurrency must be positive")

        request = dict(payload)
        request.pop("model", None)
        request.pop("stream", None)

        if policy.strategy is ExecutionStrategy.SINGLE:
            result = await self._invoke(enabled[0], request, policy.timeout_ms)
            status = "succeeded" if result.status == "succeeded" else "failed"
            return GroupExecutionResult(policy.strategy, status, (result,))

        if policy.strategy is ExecutionStrategy.FALLBACK:
            attempts: list[ModelExecutionResult] = []
            for member in enabled:
                result = await self._invoke(member, request, policy.timeout_ms)
                attempts.append(result)
                if result.status == "succeeded":
                    return GroupExecutionResult(
                        policy.strategy,
                        "succeeded",
                        tuple(attempts),
                    )
            return GroupExecutionResult(policy.strategy, "failed", tuple(attempts))

        if policy.strategy is ExecutionStrategy.PARALLEL:
            semaphore = asyncio.Semaphore(policy.max_concurrency)

            async def invoke(member: ModelGroupMember) -> ModelExecutionResult:
                async with semaphore:
                    return await self._invoke(member, request, policy.timeout_ms)

            results = tuple(await asyncio.gather(*(invoke(member) for member in enabled)))
            succeeded = sum(result.status == "succeeded" for result in results)
            if succeeded == len(results):
                status = "succeeded"
            elif succeeded:
                status = "partial"
            else:
                status = "failed"
            return GroupExecutionResult(policy.strategy, status, results)

        raise ValueError(f"unsupported execution strategy: {policy.strategy}")

    async def _invoke(
        self,
        member: ModelGroupMember,
        payload: dict[str, Any],
        timeout_ms: int,
    ) -> ModelExecutionResult:
        started = time.monotonic()
        request = {**payload, "model": member.route_id}
        try:
            response = await asyncio.wait_for(
                self.gateway.complete_route(member.route_id, request),
                timeout=timeout_ms / 1000,
            )
            return ModelExecutionResult(
                route_id=member.route_id,
                position=member.position,
                status="succeeded",
                latency_ms=int((time.monotonic() - started) * 1000),
                response=response,
            )
        except asyncio.TimeoutError:
            return ModelExecutionResult(
                route_id=member.route_id,
                position=member.position,
                status="failed",
                latency_ms=int((time.monotonic() - started) * 1000),
                error_kind="timeout",
                error_detail=f"model execution exceeded {timeout_ms} ms",
            )
        except ProviderError as error:
            return ModelExecutionResult(
                route_id=member.route_id,
                position=member.position,
                status="failed",
                latency_ms=int((time.monotonic() - started) * 1000),
                error_kind=error.kind,
                error_detail=str(error),
            )
