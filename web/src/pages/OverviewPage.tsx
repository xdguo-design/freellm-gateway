import { useI18n } from "../i18n";
import type { ConnectionRecord, Overview, Provider, Route } from "../types";
import { formatCount } from "../lib/format";

export function OverviewPage({
  overview,
  routes,
  providers,
  connections,
}: {
  overview: Overview | null;
  routes: Route[];
  providers: Provider[];
  connections: ConnectionRecord[];
}) {
  const { t, status } = useI18n();
  const stats = [
    [t("overview.configured"), overview?.configured ?? routes.length],
    [t("overview.enabled"), overview?.enabled ?? routes.filter((item) => item.enabled).length],
    [t("overview.healthy"), overview?.healthy ?? routes.filter((item) => item.health === "healthy").length],
    ["Providers", overview?.providers ?? providers.length],
  ];
  return (
    <div className="stack">
      <section className="stat-grid">
        {stats.map(([label, value]) => <article className="card stat" key={String(label)}><b>{value}</b><span>{label}</span></article>)}
      </section>
      <section className="grid-two">
        <article className="card">
          <div className="section-head"><div><h2>{t("overview.platformTitle")}</h2><p>{t("overview.platformDesc")}</p></div></div>
          <div className="kv-list">
            <div><span>API Base</span><code>{overview?.api_base ?? "/v1"}</code></div>
            <div><span>Chat</span><code>{overview?.chat_url ?? "/v1/chat/completions"}</code></div>
            <div><span>Models</span><code>{overview?.models_url ?? "/v1/models"}</code></div>
            <div><span>{t("overview.capabilities")}</span><strong>{overview?.capabilities?.join(" · ") || "—"}</strong></div>
          </div>
        </article>
        <article className="card">
          <div className="section-head"><div><h2>{t("overview.providersTitle")}</h2><p>{t("overview.providersDesc")}</p></div></div>
          <div className="provider-list">
            {providers.length ? providers.map((provider) => (
              <div key={provider.id}><span className="provider-mark">{provider.name.slice(0, 2).toUpperCase()}</span><div><b>{provider.name}</b><small>{provider.protocol} · {provider.base_url}</small></div></div>
            )) : <p className="empty">{t("overview.noProviders")}</p>}
          </div>
        </article>
      </section>
      <section className="card">
        <div className="section-head"><div><h2>{t("overview.recentTitle")}</h2><p>{t("overview.recentDesc")}</p></div></div>
        <div className="table-wrap"><table><thead><tr><th>{t("common.model")}</th><th>Provider</th><th>{t("overview.tenantApp")}</th><th>{t("common.result")}</th><th>{t("common.latency")}</th><th>Token</th></tr></thead>
          <tbody>{connections.slice(0, 12).map((item, index) => (
            <tr key={item.request_id ?? index}>
              <td><b>{item.requested_model ?? "—"}</b><small>{item.remote_model ?? ""}</small></td>
              <td>{item.provider_id ?? "—"}</td>
              <td>{item.tenant_id ?? "system"}<small>{item.application_id ?? "legacy-global"}</small></td>
              <td><span className={item.status === "success" ? "badge ok" : "badge bad"}>{status(item.status)}</span></td>
              <td>{item.elapsed_ms == null ? "—" : `${item.elapsed_ms} ms`}</td>
              <td>{formatCount(item.usage?.total_tokens)}</td>
            </tr>
          ))}{!connections.length && <tr><td colSpan={6} className="empty">{t("overview.noCalls")}</td></tr>}</tbody>
        </table></div>
      </section>
    </div>
  );
}
