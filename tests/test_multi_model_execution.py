import asyncio

import pytest

from freellm_gateway.adapters.base import ProviderError
from freellm_gateway.execution import MultiModelExecutor
from freellm_gateway.models import (
    ExecutionPolicy,
    ExecutionStrategy,
    ModelGroupMember,
    ModelRoute,
)
from freellm_gateway.service import ModelGateway


class Adapter:
    def __init__(self, answer: str, fail: bool = False, delay: float = 0):
        self.answer = answer
        self.fail = fail
        self.delay = delay
        self.calls = 0

    async def complete(self, payload):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise ProviderError("upstream_failed", 503, self.answer, retriable=True)
        return {
            "model": payload["model"],
            "choices": [{"message": {"role": "assistant", "content": self.answer}}],
        }


def make_gateway():
    routes = [
        ModelRoute(id="route-a", provider_id="p1", remote_model="model-a", priority=1),
        ModelRoute(id="route-b", provider_id="p2", remote_model="model-b", priority=2),
        ModelRoute(id="route-c", provider_id="p3", remote_model="model-c", priority=3),
    ]
    adapters = {
        "route-a": Adapter("answer-a"),
        "route-b": Adapter("answer-b"),
        "route-c": Adapter("answer-c"),
    }
    return ModelGateway(routes, adapters), adapters


def members():
    return [
        ModelGroupMember(group_id="group-1", route_id="route-a", position=1),
        ModelGroupMember(group_id="group-1", route_id="route-b", position=2),
        ModelGroupMember(group_id="group-1", route_id="route-c", position=3),
    ]


@pytest.mark.asyncio
async def test_single_executes_only_first_group_member():
    gateway, adapters = make_gateway()
    policy = ExecutionPolicy(
        id="policy-1",
        tenant_id="default",
        name="single",
        strategy=ExecutionStrategy.SINGLE,
    )

    result = await MultiModelExecutor(gateway).execute(
        policy,
        members(),
        {"messages": [{"role": "user", "content": "hello"}]},
    )

    assert result.status == "succeeded"
    assert [item.route_id for item in result.results] == ["route-a"]
    assert adapters["route-a"].calls == 1
    assert adapters["route-b"].calls == 0
    assert adapters["route-c"].calls == 0


@pytest.mark.asyncio
async def test_fallback_stops_after_first_success():
    gateway, adapters = make_gateway()
    adapters["route-a"].fail = True
    policy = ExecutionPolicy(
        id="policy-1",
        tenant_id="default",
        name="fallback",
        strategy=ExecutionStrategy.FALLBACK,
    )

    result = await MultiModelExecutor(gateway).execute(
        policy,
        members(),
        {"messages": [{"role": "user", "content": "hello"}]},
    )

    assert result.status == "succeeded"
    assert [item.status for item in result.results] == ["failed", "succeeded"]
    assert [item.route_id for item in result.results] == ["route-a", "route-b"]
    assert adapters["route-c"].calls == 0


@pytest.mark.asyncio
async def test_parallel_returns_each_model_answer():
    gateway, adapters = make_gateway()
    adapters["route-a"].delay = 0.02
    adapters["route-b"].delay = 0.01
    policy = ExecutionPolicy(
        id="policy-1",
        tenant_id="default",
        name="parallel",
        strategy=ExecutionStrategy.PARALLEL,
        max_concurrency=2,
    )

    result = await MultiModelExecutor(gateway).execute(
        policy,
        members(),
        {"messages": [{"role": "user", "content": "hello"}]},
    )

    assert result.status == "succeeded"
    assert result.success_count == 3
    assert [item.route_id for item in result.results] == [
        "route-a",
        "route-b",
        "route-c",
    ]
    assert all(adapter.calls == 1 for adapter in adapters.values())


@pytest.mark.asyncio
async def test_parallel_reports_partial_when_one_model_fails():
    gateway, adapters = make_gateway()
    adapters["route-b"].fail = True
    policy = ExecutionPolicy(
        id="policy-1",
        tenant_id="default",
        name="parallel",
        strategy=ExecutionStrategy.PARALLEL,
    )

    result = await MultiModelExecutor(gateway).execute(
        policy,
        members(),
        {"messages": [{"role": "user", "content": "hello"}]},
    )

    assert result.status == "partial"
    assert result.success_count == 2
    failed = next(item for item in result.results if item.route_id == "route-b")
    assert failed.error_kind == "upstream_failed"
