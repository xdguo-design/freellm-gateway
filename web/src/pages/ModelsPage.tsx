import { useMemo, useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Provider, Route } from "../types";
import { formatCosts } from "../lib/format";

type RouteDraft = {
  id: string;
  provider_id: string;
  remote_model: string;
  display_name: string;
  priority: number;
  capabilities: string;
  reasoning_effort: string;
  input_price_per_million: string;
  output_price_per_million: string;
  pricing_currency: string;
  credential: string;
};

const blankRoute = (): RouteDraft => ({
  id: "",
  provider_id: "",
  remote_model: "",
  display_name: "",
  priority: 1,
  capabilities: "chat",
  reasoning_effort: "",
  input_price_per_million: "",
  output_price_per_million: "",
  pricing_currency: "USD",
  credential: "",
});

export function ModelsPage({
  routes,
  providers,
  onRefresh,
}: {
  routes: Route[];
  providers: Provider[];
  onRefresh: () => Promise<void>;
}) {
  const [draft, setDraft] = useState<RouteDraft>(blankRoute);
  const [editing, setEditing] = useState<string | null>(null);
  const [modelOptions, setModelOptions] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const [providerDraft, setProviderDraft] = useState({ id: "", name: "", protocol: "openai", base_url: "", official_url: "" });

  const ordered = useMemo(() => [...routes].sort((a, b) => a.priority - b.priority), [routes]);

  function edit(route: Route) {
    setEditing(route.id);
    setDraft({
      id: route.id,
      provider_id: route.provider_id,
      remote_model: route.remote_model,
      display_name: route.display_name ?? "",
      priority: route.priority,
      capabilities: route.capabilities.join(","),
      reasoning_effort: route.reasoning_effort ?? "",
      input_price_per_million: route.pricing.input_per_million?.toString() ?? "",
      output_price_per_million: route.pricing.output_per_million?.toString() ?? "",
      pricing_currency: route.pricing.currency || "USD",
      credential: "",
    });
  }

  async function saveRoute(event: FormEvent) {
    event.preventDefault();
    const payload = {
      id: draft.id || `${draft.provider_id}-${draft.remote_model}`.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
      provider_id: draft.provider_id,
      remote_model: draft.remote_model.trim(),
      display_name: draft.display_name.trim() || null,
      priority: Number(draft.priority),
      capabilities: draft.capabilities.split(",").map((item) => item.trim()).filter(Boolean),
      reasoning_effort: draft.reasoning_effort.trim() || null,
      input_price_per_million: draft.input_price_per_million === "" ? null : Number(draft.input_price_per_million),
      output_price_per_million: draft.output_price_per_million === "" ? null : Number(draft.output_price_per_million),
      pricing_currency: draft.pricing_currency.trim().toUpperCase() || "USD",
      ...(draft.credential.trim() ? { credential: draft.credential.trim() } : {}),
    };
    await api(editing ? `/api/admin/routes/${encodeURIComponent(editing)}` : "/api/admin/routes", {
      method: editing ? "PATCH" : "POST",
      body: payload,
    });
    setDraft(blankRoute());
    setEditing(null);
    setMessage("模型路由已保存");
    await onRefresh();
  }

  async function fetchModels() {
    if (!draft.provider_id || !draft.credential.trim()) return;
    const result = await api<{ data: string[] }>(`/api/admin/providers/${encodeURIComponent(draft.provider_id)}/models`, {
      method: "POST",
      body: { credential: draft.credential.trim() },
    });
    setModelOptions(result.data ?? []);
    if (!draft.remote_model && result.data?.[0]) setDraft((current) => ({ ...current, remote_model: result.data[0] }));
  }

  async function mutate(route: Route, action: "probe" | "toggle" | "delete") {
    if (action === "probe") await api(`/api/admin/routes/${encodeURIComponent(route.id)}/probe`, { method: "POST" });
    if (action === "toggle") await api(`/api/admin/routes/${encodeURIComponent(route.id)}`, { method: "PATCH", body: { enabled: !route.enabled } });
    if (action === "delete") await api(`/api/admin/routes/${encodeURIComponent(route.id)}`, { method: "DELETE" });
    await onRefresh();
  }

  async function move(index: number, delta: -1 | 1) {
    const next = index + delta;
    if (next < 0 || next >= ordered.length) return;
    const ids = ordered.map((route) => route.id);
    [ids[index], ids[next]] = [ids[next], ids[index]];
    await api("/api/admin/routes/reorder", { method: "POST", body: { ids } });
    await onRefresh();
  }

  async function saveProvider(event: FormEvent) {
    event.preventDefault();
    await api("/api/admin/providers", { method: "POST", body: providerDraft });
    setProviderDraft({ id: "", name: "", protocol: "openai", base_url: "", official_url: "" });
    await onRefresh();
  }

  return (
    <div className="stack">
      {message && <div className="notice ok">{message}</div>}
      <section className="card">
        <div className="section-head"><div><h2>模型池</h2><p>统一维护 Provider、能力、优先级、价格和健康状态。</p></div><button className="primary" onClick={() => { setEditing(null); setDraft(blankRoute()); }}>添加模型</button></div>
        <div className="table-wrap"><table><thead><tr><th>#</th><th>模型</th><th>Provider</th><th>能力</th><th>价格 / 1M</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>{ordered.map((route, index) => <tr key={route.id}>
            <td>{route.priority}</td>
            <td><b>{route.display_name || route.remote_model}</b><small>{route.remote_model}</small></td>
            <td>{route.provider_name}</td>
            <td>{route.capabilities.map((cap) => <span className="tag" key={cap}>{cap}</span>)}</td>
            <td>{route.pricing.input_per_million == null && route.pricing.output_per_million == null ? "—" : `${route.pricing.currency} ${route.pricing.input_per_million ?? "?"} / ${route.pricing.output_per_million ?? "?"}`}</td>
            <td><span className={`badge ${!route.enabled ? "muted-badge" : route.health === "healthy" ? "ok" : "warn"}`}>{route.enabled ? route.health : "disabled"}</span></td>
            <td><div className="actions">
              <button onClick={() => move(index, -1)}>↑</button><button onClick={() => move(index, 1)}>↓</button>
              <button onClick={() => edit(route)}>编辑</button><button onClick={() => mutate(route, "probe")}>探测</button>
              <button onClick={() => mutate(route, "toggle")}>{route.enabled ? "停用" : "启用"}</button>
              <button className="danger" onClick={() => mutate(route, "delete")}>删除</button>
            </div></td>
          </tr>)}{!ordered.length && <tr><td colSpan={7} className="empty">还没有模型路由。</td></tr>}</tbody>
        </table></div>
      </section>

      <section className="grid-two">
        <form className="card form-card" onSubmit={saveRoute}>
          <div className="section-head"><div><h2>{editing ? "编辑模型" : "添加模型"}</h2><p>价格为空时费用会标记为未计价。</p></div></div>
          <div className="form-grid">
            <label>Provider<select required value={draft.provider_id} onChange={(e) => setDraft({ ...draft, provider_id: e.target.value })}><option value="">请选择</option>{providers.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.protocol}</option>)}</select></label>
            <label>模型<input list="provider-model-options" required value={draft.remote_model} onChange={(e) => setDraft({ ...draft, remote_model: e.target.value })} /><datalist id="provider-model-options">{modelOptions.map((model) => <option value={model} key={model} />)}</datalist></label>
            <label>显示名<input value={draft.display_name} onChange={(e) => setDraft({ ...draft, display_name: e.target.value })} /></label>
            <label>优先级<input type="number" min={1} value={draft.priority} onChange={(e) => setDraft({ ...draft, priority: Number(e.target.value) })} /></label>
            <label>能力（逗号分隔）<input value={draft.capabilities} onChange={(e) => setDraft({ ...draft, capabilities: e.target.value })} /></label>
            <label>Reasoning Effort<input placeholder="medium / high / low" value={draft.reasoning_effort} onChange={(e) => setDraft({ ...draft, reasoning_effort: e.target.value })} /></label>
            <label>输入价 / 1M<input type="number" min="0" step="0.000001" value={draft.input_price_per_million} onChange={(e) => setDraft({ ...draft, input_price_per_million: e.target.value })} /></label>
            <label>输出价 / 1M<input type="number" min="0" step="0.000001" value={draft.output_price_per_million} onChange={(e) => setDraft({ ...draft, output_price_per_million: e.target.value })} /></label>
            <label>币种<input value={draft.pricing_currency} maxLength={8} onChange={(e) => setDraft({ ...draft, pricing_currency: e.target.value })} /></label>
            <label>API Key（仅本次保存/发现）<input type="password" value={draft.credential} onChange={(e) => setDraft({ ...draft, credential: e.target.value })} /></label>
          </div>
          <div className="form-actions"><button type="button" onClick={fetchModels}>验证并获取模型</button><button className="primary" type="submit">保存模型</button></div>
        </form>

        <form className="card form-card" onSubmit={saveProvider}>
          <div className="section-head"><div><h2>添加 Provider</h2><p>协议和 Base URL 统一在 Provider 层管理。</p></div></div>
          <div className="form-grid one">
            <label>Provider ID<input required value={providerDraft.id} onChange={(e) => setProviderDraft({ ...providerDraft, id: e.target.value })} /></label>
            <label>名称<input required value={providerDraft.name} onChange={(e) => setProviderDraft({ ...providerDraft, name: e.target.value })} /></label>
            <label>协议<select value={providerDraft.protocol} onChange={(e) => setProviderDraft({ ...providerDraft, protocol: e.target.value })}><option value="openai">OpenAI Compatible</option><option value="gemini">Gemini Native</option><option value="anthropic">Anthropic Native</option></select></label>
            <label>Base URL<input required placeholder="https://api.example.com/v1" value={providerDraft.base_url} onChange={(e) => setProviderDraft({ ...providerDraft, base_url: e.target.value })} /></label>
            <label>官网<input required placeholder="https://example.com" value={providerDraft.official_url} onChange={(e) => setProviderDraft({ ...providerDraft, official_url: e.target.value })} /></label>
          </div>
          <div className="form-actions"><button className="primary" type="submit">保存 Provider</button></div>
        </form>
      </section>
    </div>
  );
}
