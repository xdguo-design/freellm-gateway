import type { Route } from "../types";

export function RoutingPage({ routes }: { routes: Route[] }) {
  const capabilities = Array.from(new Set(routes.flatMap((route) => route.capabilities))).sort();
  return (
    <div className="stack">
      <section className="card routing-flow">
        <div><b>Request</b><small>model / capability</small></div><span>→</span>
        <div><b>Quota Preflight</b><small>Tenant + Application</small></div><span>→</span>
        <div><b>Health Filter</b><small>enabled / cooldown</small></div><span>→</span>
        <div><b>Priority Router</b><small>failover candidates</small></div><span>→</span>
        <div><b>Provider</b><small>OpenAI / Gemini / Anthropic</small></div>
      </section>
      <section className="card">
        <div className="section-head"><div><h2>能力路由</h2><p>候选按健康状态与优先级排序。</p></div></div>
        <div className="cap-grid">
          {capabilities.map((capability) => {
            const candidates = routes.filter((route) => route.enabled && route.capabilities.includes(capability)).sort((a, b) => a.priority - b.priority);
            return <article key={capability}><h3>{capability}</h3>{candidates.map((route) => <div className="candidate" key={route.id}><b>#{route.priority}</b><span>{route.remote_model}</span><small>{route.provider_name}</small></div>)}</article>;
          })}
          {!capabilities.length && <p className="empty">还没有可路由能力。</p>}
        </div>
      </section>
    </div>
  );
}
