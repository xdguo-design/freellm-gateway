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
  const stats = [
    ["已配置模型", overview?.configured ?? routes.length],
    ["启用模型", overview?.enabled ?? routes.filter((item) => item.enabled).length],
    ["健康模型", overview?.healthy ?? routes.filter((item) => item.health === "healthy").length],
    ["Providers", overview?.providers ?? providers.length],
  ];
  return (
    <div className="stack">
      <section className="stat-grid">
        {stats.map(([label, value]) => <article className="card stat" key={String(label)}><b>{value}</b><span>{label}</span></article>)}
      </section>
      <section className="grid-two">
        <article className="card">
          <div className="section-head"><div><h2>平台状态</h2><p>统一模型接入、路由、用量与配额。</p></div></div>
          <div className="kv-list">
            <div><span>API Base</span><code>{overview?.api_base ?? "/v1"}</code></div>
            <div><span>Chat</span><code>{overview?.chat_url ?? "/v1/chat/completions"}</code></div>
            <div><span>Models</span><code>{overview?.models_url ?? "/v1/models"}</code></div>
            <div><span>能力</span><strong>{overview?.capabilities?.join(" · ") || "—"}</strong></div>
          </div>
        </article>
        <article className="card">
          <div className="section-head"><div><h2>Provider 分布</h2><p>当前接入的模型提供方。</p></div></div>
          <div className="provider-list">
            {providers.length ? providers.map((provider) => (
              <div key={provider.id}><span className="provider-mark">{provider.name.slice(0, 2).toUpperCase()}</span><div><b>{provider.name}</b><small>{provider.protocol} · {provider.base_url}</small></div></div>
            )) : <p className="empty">尚未配置 Provider</p>}
          </div>
        </article>
      </section>
      <section className="card">
        <div className="section-head"><div><h2>最近调用</h2><p>仅展示路由、结果、耗时和 Token，不展示 Prompt 或密钥。</p></div></div>
        <div className="table-wrap"><table><thead><tr><th>模型</th><th>Provider</th><th>租户 / 应用</th><th>结果</th><th>耗时</th><th>Token</th></tr></thead>
          <tbody>{connections.slice(0, 12).map((item, index) => (
            <tr key={item.request_id ?? index}>
              <td><b>{item.requested_model ?? "—"}</b><small>{item.remote_model ?? ""}</small></td>
              <td>{item.provider_id ?? "—"}</td>
              <td>{item.tenant_id ?? "system"}<small>{item.application_id ?? "legacy-global"}</small></td>
              <td><span className={item.status === "success" ? "badge ok" : "badge bad"}>{item.status ?? "unknown"}</span></td>
              <td>{item.elapsed_ms == null ? "—" : `${item.elapsed_ms} ms`}</td>
              <td>{formatCount(item.usage?.total_tokens)}</td>
            </tr>
          ))}{!connections.length && <tr><td colSpan={6} className="empty">暂无调用记录</td></tr>}</tbody>
        </table></div>
      </section>
    </div>
  );
}
