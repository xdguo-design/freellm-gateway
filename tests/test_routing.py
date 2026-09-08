from freellm_gateway.models import HealthStatus, ModelRoute
from freellm_gateway.routing import select_candidates


def route(route_id: str, priority: int, **kwargs) -> ModelRoute:
    return ModelRoute(
        id=route_id,
        provider_id=f"provider-{route_id}",
        remote_model=route_id,
        priority=priority,
        **kwargs,
    )


def test_auto_uses_priority_order_and_skips_ineligible_routes():
    routes = [
        route("slow", 1, health=HealthStatus.SLOW),
        route("second", 2),
        route("disabled", 0, enabled=False),
        route("quota", 3, health=HealthStatus.QUOTA_EXHAUSTED),
        route("first", 1),
    ]

    candidates = select_candidates(routes, requested_model="auto", capability="chat")

    assert [item.id for item in candidates] == ["first", "second"]


def test_explicit_model_does_not_fail_over_to_another_model():
    routes = [route("wanted", 1), route("other", 2)]

    candidates = select_candidates(routes, requested_model="wanted", capability="chat")

    assert [item.id for item in candidates] == ["wanted"]


def test_capability_filter_keeps_only_matching_routes():
    routes = [
        route("text", 1, capabilities=frozenset({"chat"})),
        route("image", 2, capabilities=frozenset({"image"})),
    ]

    candidates = select_candidates(routes, requested_model="auto", capability="chat")

    assert [item.id for item in candidates] == ["text"]
