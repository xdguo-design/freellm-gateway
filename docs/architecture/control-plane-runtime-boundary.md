# Control Plane / Runtime Boundary

FreeLLM Gateway is being refactored from an in-process model proxy into an AI gateway control plane.

## Ownership

FreeLLM keeps:

- model catalog and model intelligence
- tenant, application, API key, quota and billing policy
- model policy decisions and fallback policy
- normalized usage/cost events and analytics
- admin console and governance APIs

External gateway runtimes own:

- HTTP proxying and streaming
- provider protocol translation
- transport retry and circuit breaking
- upstream connection management
- runtime health checks

## Runtime contract

`freellm_gateway.backends.base.GatewayBackend` is the anti-corruption boundary. Planned implementations are LiteLLM first, Higress second, and APISIX when enterprise gateway requirements justify it.

The control plane emits desired routes and policies; runtime adapters translate that desired state into runtime-specific configuration. Runtime-specific objects must not leak into model catalog, tenant, policy, usage, or billing domains.

## Migration

Phase 0 introduces the boundary without deleting the legacy runtime so existing clients keep working.

Phase 1 moves model selection to `ModelPolicyEngine` and adds tenant/application plus usage domains.

Phase 2 adds LiteLLM and Higress backend implementations. New runtime features must be implemented in those adapters or upstream projects, not in the legacy proxy.

Phase 3 removes the legacy in-process provider adapter, failover, transport health and proxy paths after compatibility tests pass.
