import { useI18n } from "../i18n";
import type { Route } from "../types";

export function RoutingPage({ routes }: { routes: Route[] }) {
  const { t } = useI18n();
  const capabilities = Array.from(new Set(routes.flatMap((route) => route.capabilities))).sort();
  return (
    <div className="stack">
      <section className="card routing-flow">
        <div><b>{t("routing.request")}</b><small>{t("routing.requestDesc")}</small></div><span>→</span>
        <div><b>{t("routing.preflight")}</b><small>{t("routing.preflightDesc")}</small></div><span>→</span>
        <div><b>{t("routing.healthFilter")}</b><small>{t("routing.healthFilterDesc")}</small></div><span>→</span>
        <div><b>{t("routing.priority")}</b><small>{t("routing.priorityDesc")}</small></div><span>→</span>
        <div><b>Provider</b><small>OpenAI / Gemini / Anthropic</small></div>
      </section>
      <section className="card">
        <div className="section-head"><div><h2>{t("routing.title")}</h2><p>{t("routing.desc")}</p></div></div>
        <div className="cap-grid">
          {capabilities.map((capability) => {
            const candidates = routes.filter((route) => route.enabled && route.capabilities.includes(capability)).sort((a, b) => a.priority - b.priority);
            return <article key={capability}><h3>{capability}</h3>{candidates.map((route) => <div className="candidate" key={route.id}><b>#{route.priority}</b><span>{route.remote_model}</span><small>{route.provider_name}</small></div>)}</article>;
          })}
          {!capabilities.length && <p className="empty">{t("routing.empty")}</p>}
        </div>
      </section>
    </div>
  );
}
