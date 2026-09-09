import pytest

from freellm_gateway.health import RoutePolicy
from freellm_gateway.models import HealthStatus, ModelRoute
from freellm_gateway.service import ModelGateway, ProviderError


class FakeAdapter:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = 0

    async def complete(self, payload):
        self.calls += 1
        if self.error:
            raise self.error
        return self.response


@pytest.mark.asyncio
async def test_gateway_fails_over_in_priority_order():
    routes = [
        ModelRoute(id="first", provider_id="p1", remote_model="m1", priority=1),
        ModelRoute(id="second", provider_id="p2", remote_model="m2", priority=2),
    ]
    adapters = {
        "first": FakeAdapter(error=ProviderError("rate_limit", 429)),
        "second": FakeAdapter(response={"id": "fallback", "choices": []}),
    }
    gateway = ModelGateway(routes, adapters)

    result = await gateway.complete({"model": "auto", "messages": []})

    assert result["id"] == "fallback"
    assert adapters["first"].calls == 1
    assert adapters["second"].calls == 1


@pytest.mark.asyncio
async def test_gateway_returns_503_error_when_all_candidates_fail():
    routes = [ModelRoute(id="only", provider_id="p1", remote_model="m1", priority=1)]
    gateway = ModelGateway(
        routes,
        {"only": FakeAdapter(error=ProviderError("provider_5xx", 500))},
    )

    with pytest.raises(ProviderError) as error:
        await gateway.complete({"model": "auto", "messages": []})

    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_gateway_marks_failed_route_and_skips_it_on_next_request():
    routes = [
        ModelRoute(id="first", provider_id="p1", remote_model="m1", priority=1),
        ModelRoute(id="second", provider_id="p2", remote_model="m2", priority=2),
    ]
    adapters = {
        "first": FakeAdapter(error=ProviderError("rate_limit", 429)),
        "second": FakeAdapter(response={"id": "fallback", "choices": []}),
    }
    gateway = ModelGateway(routes, adapters, policies={"first": RoutePolicy(backoff_schedule=(60, 300))})

    await gateway.complete({"model": "auto", "messages": []})
    await gateway.complete({"model": "auto", "messages": []})

    assert adapters["first"].calls == 1
    assert gateway.route("first").health == HealthStatus.RATE_LIMITED


@pytest.mark.asyncio
async def test_new_route_added_after_start_can_be_selected():
    gateway = ModelGateway([], {})
    adapter = FakeAdapter(response={"id": "new", "choices": []})
    gateway.add_route(ModelRoute(id="new", provider_id="p", remote_model="new", priority=1), adapter)

    result = await gateway.complete({"model": "auto", "messages": []})

    assert result["id"] == "new"
