from freellm_gateway.model_registry import ModelRegistry
from freellm_gateway.models import ModelRoute


def route(route_id: str, priority: int, **kwargs) -> ModelRoute:
    return ModelRoute(
        id=route_id,
        provider_id=kwargs.pop("provider_id", "provider"),
        remote_model=kwargs.pop("remote_model", route_id),
        priority=priority,
        **kwargs,
    )


def test_registry_orders_routes_and_filters_capabilities():
    registry = ModelRegistry(
        [
            route("text", 2, capabilities=frozenset({"chat"})),
            route(
                "vision",
                1,
                capabilities=frozenset({"chat", "vision", "tools"}),
                context_window=128000,
            ),
        ]
    )

    assert [item.id for item in registry.list()] == ["vision", "text"]
    assert [item.id for item in registry.find(required_capabilities={"vision"})] == ["vision"]
    assert [item.id for item in registry.find(required_capabilities={"function_calling"})] == ["vision"]
    assert [item.id for item in registry.find(min_context_window=100000)] == ["vision"]


def test_registry_profile_exposes_limits_pricing_and_normalized_capability_flags():
    registry = ModelRegistry(
        [
            route(
                "model",
                1,
                capabilities=frozenset({"chat", "stream", "json"}),
                context_window=32000,
                max_output_tokens=4096,
                input_price_per_million=0.1,
                output_price_per_million=0.4,
                pricing_currency="USD",
            )
        ]
    )

    profile = registry.profile("model")
    payload = profile.to_dict()

    assert profile.supports("streaming")
    assert profile.supports("json_mode")
    assert payload["limits"] == {"context_window": 32000, "max_output_tokens": 4096}
    assert payload["pricing"]["input_per_million"] == 0.1


def test_registry_stays_mutable_without_exposing_internal_mapping():
    registry = ModelRegistry([route("one", 1)])

    registry.register(route("two", 2))
    registry.replace(route("two", 3, capabilities=frozenset({"chat", "vision"})))
    registry.remove("one")

    assert [item.id for item in registry.list()] == ["two"]
    assert registry.profile("two").supports("vision")
