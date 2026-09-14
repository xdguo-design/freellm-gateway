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


class SequenceAdapter:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    async def complete(self, payload):
        self.calls.append(payload)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class StreamAdapter(FakeAdapter):
    def __init__(self, chunks=()):
        super().__init__()
        self.chunks = chunks

    async def stream(self, payload):
        for chunk in self.chunks:
            yield chunk


class SequenceStreamAdapter:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    async def stream(self, payload):
        self.calls.append(payload)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        for chunk in outcome:
            yield chunk


@pytest.mark.asyncio
async def test_auto_demotes_route_after_real_invalid_request_and_promotes_successful_fallback():
    routes = [
        ModelRoute(id="groq", provider_id="groq", remote_model="openai/gpt-oss-120b", priority=1),
        ModelRoute(id="qwen", provider_id="alibaba", remote_model="Qwen/Qwen3.8-27B", priority=2),
    ]
    successful_probe = {"choices": [{"message": {"content": "probe ok"}}]}
    successful_completion = {"id": "qwen-result", "choices": [{"message": {"content": "pong"}}]}
    persisted = []
    gateway = ModelGateway(
        routes,
        {
            "groq": SequenceAdapter(
                successful_probe,
                ProviderError("invalid_request", 400, "unsupported request", retriable=False),
            ),
            "qwen": SequenceAdapter(successful_probe, successful_completion),
        },
        on_route_changed=persisted.append,
    )

    result = await gateway.complete({"model": "auto", "messages": [{"role": "user", "content": "hello"}]})

    assert result["id"] == "qwen-result"
    assert len(gateway.adapters["groq"].calls) == 2
    assert len(gateway.adapters["qwen"].calls) == 2
    assert [(route.id, route.priority) for route in gateway.routes] == [("qwen", 1), ("groq", 2)]
    assert {route.id: route.priority for route in persisted} == {"qwen": 1, "groq": 2}


@pytest.mark.asyncio
async def test_auto_stream_preflight_failure_skips_route_and_promotes_successful_route():
    routes = [
        ModelRoute(id="groq", provider_id="groq", remote_model="openai/gpt-oss-120b", priority=1),
        ModelRoute(id="qwen", provider_id="alibaba", remote_model="Qwen/Qwen3.8-27B", priority=2),
    ]
    persisted = []
    gateway = ModelGateway(
        routes,
        {
            "groq": SequenceStreamAdapter([]),
            "qwen": SequenceStreamAdapter([b"data: probe\n\n"], [b"data: result\n\n"]),
        },
        on_route_changed=persisted.append,
    )

    chunks = [chunk async for chunk in gateway.stream({"model": "auto", "messages": [{"role": "user", "content": "hello"}]})]

    assert chunks == [b"data: result\n\n"]
    assert len(gateway.adapters["groq"].calls) == 1
    assert len(gateway.adapters["qwen"].calls) == 2
    assert [(route.id, route.priority) for route in gateway.routes] == [("qwen", 1), ("groq", 2)]
    assert {route.id: route.priority for route in persisted} == {"qwen": 1, "groq": 2}


@pytest.mark.asyncio
async def test_gateway_fails_over_in_priority_order():
    routes = [
        ModelRoute(id="first", provider_id="p1", remote_model="m1", priority=1),
        ModelRoute(id="second", provider_id="p2", remote_model="m2", priority=2),
    ]
    adapters = {
        "first": FakeAdapter(error=ProviderError("rate_limit", 429)),
        "second": FakeAdapter(response={"id": "fallback", "choices": [{"message": {"content": "ok"}}]}),
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
        "second": FakeAdapter(response={"id": "fallback", "choices": [{"message": {"content": "ok"}}]}),
    }
    gateway = ModelGateway(routes, adapters, policies={"first": RoutePolicy(backoff_schedule=(60, 300))})

    await gateway.complete({"model": "auto", "messages": []})
    await gateway.complete({"model": "auto", "messages": []})

    assert adapters["first"].calls == 1
    assert gateway.route("first").health == HealthStatus.RATE_LIMITED


@pytest.mark.asyncio
async def test_new_route_added_after_start_can_be_selected():
    gateway = ModelGateway([], {})
    adapter = FakeAdapter(response={"id": "new", "choices": [{"message": {"content": "ok"}}]})
    gateway.add_route(ModelRoute(id="new", provider_id="p", remote_model="new", priority=1), adapter)

    result = await gateway.complete({"model": "auto", "messages": []})

    assert result["id"] == "new"


@pytest.mark.asyncio
async def test_authentication_error_disables_route_persists_and_fails_over():
    routes = [
        ModelRoute(id="bad", provider_id="p", remote_model="bad-model", priority=1),
        ModelRoute(id="good", provider_id="p", remote_model="good-model", priority=2),
    ]
    persisted = []
    gateway = ModelGateway(
        routes,
        {
            "bad": FakeAdapter(error=ProviderError("authentication_error", 401, retriable=False)),
            "good": FakeAdapter(response={"id": "fallback", "choices": [{"message": {"content": "ok"}}]}),
        },
        on_route_changed=persisted.append,
    )

    result = await gateway.complete({"model": "auto", "messages": []})

    assert result["id"] == "fallback"
    assert gateway.route("bad").enabled is False
    assert gateway.route("bad").health == HealthStatus.DISABLED
    assert [(route.id, route.enabled, route.health) for route in persisted] == [
        ("bad", False, HealthStatus.DISABLED),
    ]
    assert gateway._candidates("auto", "chat") == [gateway.route("good")]


@pytest.mark.asyncio
async def test_authentication_error_during_probe_disables_route_but_network_error_does_not():
    auth_route = ModelRoute(id="auth", provider_id="p", remote_model="auth-model", priority=1)
    network_route = ModelRoute(id="network", provider_id="p", remote_model="network-model", priority=2)
    persisted = []
    gateway = ModelGateway(
        [auth_route, network_route],
        {
            "auth": FakeAdapter(error=ProviderError("authentication_error", 401, retriable=False)),
            "network": FakeAdapter(error=ProviderError("network_error", 502, retriable=True)),
        },
        on_route_changed=persisted.append,
    )

    with pytest.raises(ProviderError):
        await gateway.probe("auth")
    with pytest.raises(ProviderError):
        await gateway.probe("network")

    assert gateway.route("auth").enabled is False
    assert gateway.route("auth").health == HealthStatus.DISABLED
    assert gateway.route("network").enabled is True
    assert gateway.route("network").health != HealthStatus.DISABLED
    assert [route.id for route in persisted] == ["auth"]


@pytest.mark.asyncio
async def test_gateway_fails_over_when_provider_returns_empty_completion():
    routes = [
        ModelRoute(id="unstable", provider_id="p1", remote_model="unstable", priority=1),
        ModelRoute(id="alibaba", provider_id="p2", remote_model="Qwen/Qwen3.8-27B", priority=2),
    ]
    adapters = {
        "unstable": FakeAdapter(response={"id": "empty", "choices": []}),
        "alibaba": FakeAdapter(response={
            "id": "good", "model": "Qwen/Qwen3.8-27B",
            "choices": [{"message": {"content": "pong"}}],
        }),
    }
    gateway = ModelGateway(routes, adapters)

    result = await gateway.complete({"model": "auto", "messages": []})

    assert result["id"] == "good"
    assert adapters["unstable"].calls == 1
    assert adapters["alibaba"].calls == 1


@pytest.mark.asyncio
async def test_gateway_fails_over_when_provider_returns_empty_stream():
    routes = [
        ModelRoute(id="unstable", provider_id="p1", remote_model="unstable", priority=1),
        ModelRoute(id="alibaba", provider_id="p2", remote_model="Qwen/Qwen3.8-27B", priority=2),
    ]
    gateway = ModelGateway(routes, {
        "unstable": StreamAdapter(),
        "alibaba": StreamAdapter([b"data: pong\n\n"]),
    })

    chunks = [chunk async for chunk in gateway.stream({"model": "auto", "messages": []})]

    assert chunks == [b"data: pong\n\n"]


@pytest.mark.asyncio
async def test_gateway_fails_over_when_provider_raises_protocol_error():
    routes = [
        ModelRoute(id="broken", provider_id="p1", remote_model="broken", priority=1),
        ModelRoute(id="alibaba", provider_id="p2", remote_model="Qwen/Qwen3.8-27B", priority=2),
    ]
    gateway = ModelGateway(routes, {
        "broken": FakeAdapter(error=ValueError("invalid JSON from provider")),
        "alibaba": FakeAdapter(response={"id": "good", "choices": [{"message": {"content": "pong"}}]}),
    })

    result = await gateway.complete({"model": "auto", "messages": []})

    assert result["id"] == "good"


@pytest.mark.asyncio
async def test_gateway_logs_selected_route_and_token_usage():
    logged = []
    route = ModelRoute(id="qwen", provider_id="alibaba", remote_model="Qwen/Qwen3.8-27B", priority=1)
    gateway = ModelGateway(
        [route],
        {"qwen": FakeAdapter(response={
            "id": "good",
            "model": "Qwen/Qwen3.8-27B",
            "choices": [{"message": {"content": "pong"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
        })},
        on_connection_logged=logged.append,
    )

    await gateway.complete({"model": "auto", "messages": [{"role": "user", "content": "hi"}]})

    assert logged[0]["provider_id"] == "alibaba"
    assert logged[0]["remote_model"] == "Qwen/Qwen3.8-27B"
    assert logged[0]["status"] == "success"
    assert logged[0]["usage"] == {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16}
