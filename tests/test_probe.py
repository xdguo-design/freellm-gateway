import time

import pytest

from freellm_gateway.adapters.base import ProviderError
from freellm_gateway.health import is_eligible
from freellm_gateway.models import HealthStatus, ModelRoute
from freellm_gateway.service import ModelGateway, build_probe_prompt, extract_output_text


class StaticAdapter:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    async def complete(self, payload):
        self.calls.append(payload)
        if self.error:
            raise self.error
        return self.response


def make_gateway(adapter):
    route = ModelRoute(id="r", provider_id="p", remote_model="m", priority=1)
    return ModelGateway([route], {"r": adapter})


@pytest.mark.asyncio
async def test_probe_sends_randomized_arithmetic_with_token_budget():
    adapter = StaticAdapter(response={"choices": [{"message": {"content": "164821"}}]})
    gateway = make_gateway(adapter)

    await gateway.probe("r")

    payload = adapter.calls[0]
    assert payload["max_tokens"] == 64
    content = payload["messages"][0]["content"]
    assert content.startswith("Calculate ")
    assert content.endswith(", and reply with the result only.")
    # prompts are randomized so upstreams cannot serve a cached completion
    await gateway.probe("r")
    assert adapter.calls[0]["messages"][0]["content"] != adapter.calls[1]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_probe_empty_output_raises_and_stays_isolated():
    adapter = StaticAdapter(response={"choices": []})
    gateway = make_gateway(adapter)

    with pytest.raises(ProviderError) as error:
        await gateway.probe("r")

    assert error.value.kind == "empty_output"
    assert gateway.route("r").health == HealthStatus.HEALTHY
    assert gateway.health_states["r"].last_error_kind == "empty_output"
    assert is_eligible(gateway.health_states["r"], time.monotonic())


@pytest.mark.asyncio
async def test_probe_rate_limit_is_recorded_without_cooling_down():
    adapter = StaticAdapter(error=ProviderError("rate_limit", 429, "slow down", retry_after=90))
    gateway = make_gateway(adapter)

    with pytest.raises(ProviderError):
        await gateway.probe("r")

    state = gateway.health_states["r"]
    assert state.status == HealthStatus.HEALTHY
    assert state.last_error_kind == "rate_limit"
    assert state.last_retry_after == 90
    assert is_eligible(state, time.monotonic())


def test_extract_output_text_handles_common_shapes():
    assert extract_output_text({"choices": [{"message": {"content": "hello"}}]}) == "hello"
    assert extract_output_text({"choices": [{"text": "legacy"}]}) == "legacy"
    assert (
        extract_output_text({"choices": [{"message": {"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}}]})
        == "ab"
    )
    assert extract_output_text({"choices": []}) == ""
    assert extract_output_text({}) == ""
