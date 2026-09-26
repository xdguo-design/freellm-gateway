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
T\ÙH[›ÙXÙ\ÈH›İ[™\HÚ]İ][][™ÈHYØXŞH[[YHÛÈ^\İ[™ÈÛY[ÈÙY\ÛÜšÚ[™Ë‚‚”\ÙHH[İ™\È[Ù[Ù[Xİ[ÛˆÈ[Ù[ÛXŞQ[™Ú[™X[™YÈ[˜[Ø\XØ][Ûˆ\È\ØYÙHÛXZ[œË‚‚”\ÙHˆYÈ]SH[™YÜ™\ÜÈ˜XÚÙ[™[\[Y[][ÛœËˆ™]È[[YH™X]\™\È]\İ™H[\[Y[Y[ˆÜÙHY\\œÈÜˆ\İ™X[H›Ú™XİË›İ[ˆHYØXŞH›ŞK‚‚”\ÙHÈ™[[İ™\ÈHYØXŞH[‹\›ØÙ\ÜÈ›İšY\ˆY\\‹˜Z[İ™\‹˜[œÜÜX[[™›ŞH]ÈY\ˆÛÛ\]Xš[]H\İÈ\ÜË‚