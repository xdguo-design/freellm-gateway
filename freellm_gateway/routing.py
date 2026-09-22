from .models import HealthStatus, ModelRoute

INELIGIBLE = {
    HealthStatus.FAILED,
    HealthStatus.RATE_LIMITED,
    HealthStatus.QUOTA_EXHAUSTED,
    HealthStatus.COOLDOWN,
    HealthStatus.DISABLED,
}


def select_candidates(
    routes: list[ModelRoute],
    requested_model: str,
    capability: str,
) -> list[ModelRoute]:
    candidates = [
        route
        for route in routes
        if route.enabled
        and route.health not in INELIGIBLE
        and capability in route.capabilities
        and (
            requested_model == "auto"
            or route.id == requested_model
            or route.remote_model == requested_model
            or (route.display_name is not None and route.display_name == requested_model)
        )
    ]
    return sorted(candidates, key=lambda route: (route.priority, route.id))
