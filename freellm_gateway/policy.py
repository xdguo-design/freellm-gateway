"""Business model-policy decisions.

This module intentionally does not proxy requests. It produces an ordered plan
that an external gateway runtime can enforce.
"""

from dataclasses import dataclass
from typing import Iterable

from .models import ModelRoute


@dataclass(frozen=True)
class PolicyDecision:
    requested_model: str
    capability: str
    route_ids: tuple[str, ...]
    reason: str


class ModelPolicyEngine:
    def decide(self, routes: Iterable[ModelRoute], requested_model: str, capability: str) -> PolicyDecision:
        candidates = [
            route for route in routes
            if route.enabled
            and capability in route.capabilities
            and (requested_model == "auto" or route.id == requested_model)
        ]
        candidates.sort(key=lambda route: (route.priority, route.id))
        return PolicyDecision(
            requested_model=requested_model,
            capability=capability,
            route_ids=tuple(route.id for route in candidates),
            reason="ordered by FreeLLM business priority and capability",
        )
