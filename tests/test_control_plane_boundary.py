from decimal import Decimal

from freellm_gateway.backends.base import GatewayBackend
from freellm_gateway.models import ModelRoute
from freellm_gateway.policy import ModelPolicyEngine
from freellm_gateway.usage import TokenUsage, UsageEvent


def test_policy_engine_returns_plan_without_executing_runtime():
    routes = [
        ModelRoute("slow", "p1", "m1", priority=20, capabilities=frozenset({"chat"})),
        ModelRoute("fast", "p2", "m2", priority=10, capabilities=frozenset({"chat"})),
        ModelRoute("image", "p3", "m3", priority=1, capabilities=frozenset({"image_generation"})),
    ]
    decision = ModelPolicyEngine().decide(routes, "auto", "chat")
    assert decision.route_ids == ("fast", "slow")


def test_usage_event_supports_extened_token_dimensions():
    event = UsageEvent(
        request_id="req-1",
        tenant_id="tenant-a",
        application_id="app-a",
        model_id="model-a",
        usage=TokenUsage(input_tokens=10, output_tokens=5, cache_tokens=2, reasoning_tokens=3, image_tokens=1),
        estimated_cost=Decimal("0.01"),
    )
    assert event.usage.reasoning_tokens == 3
    assert event.estimated_cost == Decimal("0.01")


def test_gateway_backend_is_an_interface():
    assert GatewayBackend.__abstractmethods__ == {
        "create_route", "update_route", "delete_route", "apply_policy", "query_usage", "health"
    }
