import { useEffect, useMemo, useState, type FormEvent } from "react";
import { api } from "../api/client";
import {
  CATALOG_DRAFT_KEY,
  CUSTOM_PROVIDER_ID,
  atomGitPreset,
  connectionKey,
  type ProviderDraft,
} from "../features/models/connection";
import { formatCount } from "../lib/format";
import type { ConnectionRecord, Provider, Route } from "../types";

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
  public_url: string;
  public_docs_url: string;
  free_summary: string;
  catalog_status: "draft" | "published";
};

type MultiConnection = {
  key: string;
  provider: ProviderDraft;
  credential: string;
  models: string[];
  selected_models: string[];
  status: "idle" | "validating" | "validated" | "error";
  error: string;
};

const blankProvider = (): ProviderDraft => ({
  id: "",
  name: "",
  protocol: "openai",
  base_url: "",
  official_url: "",
});

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
  public_url: "",
  public_docs_url: "",
  free_summary: "",
  catalog_status: "draft",
});

function providerPayload(provider: ProviderDraft) {
  return {
    id: provider.id.trim(),
    name: provider.name.trim(),
    protocol: provider.protocol,
    base_url: provider.base_url.trim(),
    official_url: provider.official_url.trim(),
  };
}

function ProviderFields({
  value,
  onChange,
  prefix,
}: {
  value: ProviderDraft;
  onChange: (value: ProviderDraft) => void;
  prefix: string;
}) {
  return (
    <div className="provider-fields" data-testid={prefix}>
      <label>Provider ID<input required value={value.id} onChange={(event) => onChange({ ...value, id: event.target.value })} /></label>
      <label>名称<input required value={value.name} onChange={(event) => onChange({ ...value, name: event.target.value })} /></label>
      <label>协议<select value={value.protocol} onChange={(event) => onChange({ ...value, protocol: event.target.value })}><option value="openai">OpenAI Compatible</option><option value="gemini">Gemini Native</option><option value="anthropic">Anthropic Native</option></select></label>
      <label>Base URL<input required placeholder="https://api.example.com/v1" value={value.base_url} onChange={(event) => onChange({ ...value, base_url: event.target.value })} /></label>
      <label>官网<input required placeholder="https://example.com" value={value.official_url} onChange={(event) => onChange({ ...value, official_url: event.target.value })} /></label>
    </div>
  );
}

export function ModelsPage({
  routes,
  providers,
  connections,
  onRefresh,
}: {
  routes: Route[];
  providers: Provider[];
  connections: ConnectionRecord[];
  onRefresh: () => Promise<void>;
}) {
  const [draft, setDraft] = useState<RouteDraft>(blankRoute);
  const [editing, setEditing] = useState<string | null>(null);
  const [customProvider, setCustomProvider] = useState<ProviderDraft>(blankProvider);
  const [modelOptions, setModelOptions] = useState<string[]>([]);
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const [providerDraft, setProviderDraft] = useState<ProviderDraft>(blankProvider);
  const [multiConnections, setMultiConnections] = useState<MultiConnection[]>([]);

  const ordered = useMemo(() => [...routes].sort((a, b) => a.priority - b.priority), [routes]);
  const routesByProvider = useMemo(() => {
    const grouped = new Map<string, Route[]>();
    for (const route of ordered) {
      grouped.set(route.provider_id, [...(grouped.get(route.provider_id) ?? []), route]);
    }
    return grouped;
  }, [ordered]);

  useEffect(() => {
    const raw = sessionStorage.getItem(CATALOG_DRAFT_KEY);
    if (!raw) return;
    sessionStorage.removeItem(CATALOG_DRAFT_KEY);
    try {
      const catalog = JSON.parse(raw) as {
        provider: ProviderDraft;
        remote_model: string;
        display_name: string;
        capabilities: string[];
        public_url: string;
        public_docs_url: string;
        free_summary: string;
        has_endpoint: boolean;
      };
      const exactProvider = providers.find((provider) => {
        try {
          return catalog.provider.base_url && connectionKey(provider) === connectionKey(catalog.provider);
        } catch {
          return false;
        }
      });
      setEditing(null);
      setCustomProvider(catalog.provider);
      setDraft({
        ...blankRoute(),
        provider_id: exactProvider?.id ?? CUSTOM_PROVIDER_ID,
        remote_model: catalog.remote_model,
        display_name: catalog.display_name,
        capabilities: catalog.capabilities.join(","),
        public_url: catalog.public_url,
        public_docs_url: catalog.public_docs_url,
        free_summary: catalog.free_summary,
        catalog_status: "draft",
      });
      setMessage(
        catalog.has_endpoint
          ? "已从 Catalog 预填模型与连接，请验证 API Key 后保存。"
          : "Catalog 没有 API Endpoint：已带入模型信息，请补 Base URL 后再验证。",
      );
    } catch {
      setMessage("Catalog 草稿无法解析，请手动添加模型。");
    }
  }, [providers]);

  function activeProvider(): ProviderDraft | undefined {
    if (draft.provider_id === CUSTOM_PROVIDER_ID) return customProvider;
    return providers.find((provider) => provider.id === draft.provider_id);
  }

  function edit(route: Route) {
    setEditing(route.id);
    setModelOptions([]);
    setSelectedModels([]);
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
      public_url: route.public_url ?? "",
      public_docs_url: route.public_docs_url ?? "",
      free_summary: route.free_summary ?? "",
      catalog_status: route.catalog_status === "published" ? "published" : "draft",
    });
  }

  function routeCommonPayload() {
    return {
      display_name: draft.display_name.trim() || null,
      priority: Number(draft.priority),
      capabilities: draft.capabilities.split(",").map((item) => item.trim()).filter(Boolean),
      reasoning_effort: draft.reasoning_effort.trim() || null,
      input_price_per_million: draft.input_price_per_million === "" ? null : Number(draft.input_price_per_million),
      output_price_per_million: draft.output_price_per_million === "" ? null : Number(draft.output_price_per_million),
      pricing_currency: draft.pricing_currency.trim().toUpperCase() || "USD",
      public_url: draft.public_url.trim() || null,
      public_docs_url: draft.public_docs_url.trim() || null,
      free_summary: draft.free_summary.trim() || null,
      catalog_status: draft.catalog_status,
    };
  }

  async function ensureProvider(provider: ProviderDraft) {
    const existing = providers.find((item) => item.id === provider.id);
    if (existing) {
      let sameConnection = false;
      try {
        sameConnection = connectionKey(existing) === connectionKey(provider);
      } catch {
        sameConnection = false;
      }
      if (!sameConnection) {
        throw new Error("Provider ID 已被另一个协议/Base URL 占用，请修改自定义 Provider ID。");
      }
      return existing;
    }
    return api<Provider>("/api/admin/providers", { method: "POST", body: providerPayload(provider) });
  }

  async function validateAndFetchModels() {
    const provider = activeProvider();
    if (!provider || !draft.credential.trim()) {
      setMessage("请先选择/填写 Provider，并填写 API Key。");
      return;
    }
    try {
      const result = draft.provider_id === CUSTOM_PROVIDER_ID
        ? await api<{ data: string[] }>("/api/admin/connection/models", {
            method: "POST",
            body: { provider: providerPayload(provider), credential: draft.credential.trim() },
          })
        : await api<{ data: string[] }>(`/api/admin/providers/${encodeURIComponent(provider.id)}/models`, {
            method: "POST",
            body: { credential: draft.credential.trim() },
          });
      setModelOptions(result.data ?? []);
      setSelectedModels(result.data ?? []);
      if (!draft.remote_model && result.data?.[0]) setDraft((current) => ({ ...current, remote_model: result.data[0] }));
      setMessage(`连接验证成功，发现 ${result.data?.length ?? 0} 个模型。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }

  async function saveRoute(event: FormEvent) {
    event.preventDefault();
    const provider = activeProvider();
    if (!provider) {
      setMessage("Provider 必填。");
      return;
    }
    if (draft.provider_id === CUSTOM_PROVIDER_ID) await ensureProvider(provider);

    const payload = {
      id: draft.id || `${provider.id}-${draft.remote_model}`.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
      provider_id: provider.id,
      remote_model: draft.remote_model.trim(),
      ...routeCommonPayload(),
      ...(draft.credential.trim() ? { credential: draft.credential.trim() } : {}),
    };
    await api(editing ? `/api/admin/routes/${encodeURIComponent(editing)}` : "/api/admin/routes", {
      method: editing ? "PATCH" : "POST",
      body: payload,
    });
    setDraft(blankRoute());
    setCustomProvider(blankProvider());
    setEditing(null);
    setModelOptions([]);
    setSelectedModels([]);
    setMessage("模型路由已保存。");
    await onRefresh();
  }

  async function saveSelectedModels() {
    const provider = activeProvider();
    if (!provider || !selectedModels.length) {
      setMessage("请先验证连接并选择模型。");
      return;
    }
    const result = await api<{ data: { created: Route[]; skipped: Array<{ remote_model: string }> } }>("/api/admin/routes/bulk", {
      method: "POST",
      body: {
        provider: providerPayload(provider),
        models: selectedModels.map((remote_model) => ({
          remote_model,
          enabled: true,
        })),
        ...routeCommonPayload(),
        ...(draft.credential.trim() ? { credential: draft.credential.trim() } : {}),
      },
    });
    setMessage(`批量加入完成：新增 ${result.data.created.length}，跳过 ${result.data.skipped.length}。`);
    await onRefresh();
  }

  async function mutate(route: Route, action: "probe" | "toggle" | "delete") {
    if (action === "probe") await api(`/api/admin/routes/${encodeURIComponent(route.id)}/probe`, { method: "POST" });
    if (action === "toggle") await api(`/api/admin/routes/${encodeURIComponent(route.id)}`, { method: "PATCH", body: { enabled: !route.enabled } });
    if (action === "delete") await api(`/api/admin/routes/${encodeURIComponent(route.id)}`, { method: "DELETE" });
    await onRefresh();
  }

  async function probeAll() {
    let rateLimitStreak = 0;
    let checked = 0;
    for (const route of ordered) {
      try {
        await api(`/api/admin/routes/${encodeURIComponent(route.id)}/probe`, { method: "POST" });
        rateLimitStreak = 0;
        checked += 1;
      } catch (error) {
        const text = error instanceof Error ? error.message : String(error);
        rateLimitStreak = text.includes("rate_limit") ? rateLimitStreak + 1 : 0;
        if (rateLimitStreak >= 3) {
          setMessage(`连续 3 个 Provider 返回 rate limit，已停止批量探测；完成 ${checked} 个。`);
          await onRefresh();
          return;
        }
      }
    }
    setMessage(`批量探测完成：${checked} 个路由。`);
    await onRefresh();
  }

  async function discover(providerId: string) {
    const result = await api<{ data: Route[] }>(`/api/admin/providers/${encodeURIComponent(providerId)}/discover`, { method: "POST" });
    setMessage(`Provider 自动发现新增 ${result.data.length} 个模型。`);
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
    await api("/api/admin/providers", { method: "POST", body: providerPayload(providerDraft) });
    setProviderDraft(blankProvider());
    setMessage("Provider 已保存。");
    await onRefresh();
  }

  function addMultiConnection(provider?: ProviderDraft) {
    const nextProvider = provider ?? blankProvider();
    const key = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    setMultiConnections((current) => [...current, {
      key,
      provider: nextProvider,
      credential: "",
      models: [],
      selected_models: [],
      status: "idle",
      error: "",
    }]);
  }

  function updateMulti(key: string, patch: Partial<MultiConnection>) {
    setMultiConnections((current) => current.map((item) => item.key === key ? { ...item, ...patch } : item));
  }

  async function validateMulti(item: MultiConnection) {
    updateMulti(item.key, { status: "validating", error: "" });
    try {
      const result = await api<{ data: string[] }>("/api/admin/connection/models", {
        method: "POST",
        body: { provider: providerPayload(item.provider), credential: item.credential.trim() },
      });
      updateMulti(item.key, {
        status: "validated",
        models: result.data ?? [],
        selected_models: result.data ?? [],
        error: "",
      });
    } catch (error) {
      updateMulti(item.key, { status: "error", error: error instanceof Error ? error.message : String(error) });
    }
  }

  async function saveMultiConnections() {
    const ready = multiConnections.filter((item) => item.status === "validated" && item.selected_models.length);
    if (!ready.length || ready.length !== multiConnections.length) {
      setMessage("每个连接都必须先验证，并至少选择一个模型。");
      return;
    }
    const result = await api<{ data: { created: Route[]; skipped: unknown[]; failed: unknown[] } }>("/api/admin/routes/bulk-connections", {
      method: "POST",
      body: {
        connections: ready.map((item) => ({
          provider: providerPayload(item.provider),
          credential: item.credential.trim(),
          models: item.selected_models.map((remote_model) => ({ remote_model })),
        })),
      },
    });
    setMessage(`多连接导入完成：新增 ${result.data.created.length}，跳过 ${result.data.skipped.length}，失败 ${result.data.failed.length}。`);
    setMultiConnections([]);
    await onRefresh();
  }

  return (
    <div className="stack">
      {message && <div className="notice">{message}</div>}

      <section className="card">
        <div className="section-head">
          <div><h2>模型池</h2><p>Provider、连接、能力、优先级、价格和健康状态在一个页面管理。</p></div>
          <div className="actions"><button onClick={() => void probeAll()}>全部探测</button><button className="primary" onClick={() => { setEditing(null); setDraft(blankRoute()); }}>添加模型</button></div>
        </div>
        <div className="table-wrap"><table><thead><tr><th>#</th><th>模型</th><th>Provider</th><th>能力</th><th>价格 / 1M</th><th>运行状态</th><th>目录状态</th><th>操作</th></tr></thead>
          <tbody>{ordered.map((route, index) => <tr key={route.id}>
            <td>{route.priority}</td>
            <td><b>{route.display_name || route.remote_model}</b><small>{route.remote_model}</small></td>
            <td>{route.provider_name}</td>
            <td>{route.capabilities.map((cap) => <span className="tag" key={cap}>{cap}</span>)}</td>
            <td>{route.pricing.input_per_million == null && route.pricing.output_per_million == null ? "—" : `${route.pricing.currency} ${route.pricing.input_per_million ?? "?"} / ${route.pricing.output_per_million ?? "?"}`}</td>
            <td><span className={`badge ${!route.enabled ? "muted-badge" : route.health === "healthy" ? "ok" : "warn"}`}>{route.enabled ? route.health : "disabled"}</span></td>
            <td><span className={`badge ${route.catalog_status === "published" ? "ok" : "muted-badge"}`}>{route.catalog_status}</span></td>
            <td><div className="actions">
              <button onClick={() => void move(index, -1)}>↑</button><button onClick={() => void move(index, 1)}>↓</button>
              <button onClick={() => edit(route)}>编辑</button><button onClick={() => void mutate(route, "probe")}>探测</button>
              <button onClick={() => void mutate(route, "toggle")}>{route.enabled ? "停用" : "启用"}</button>
              <button className="danger" onClick={() => void mutate(route, "delete")}>删除</button>
            </div></td>
          </tr>)}{!ordered.length && <tr><td colSpan={8} className="empty">还没有模型路由。</td></tr>}</tbody>
        </table></div>
      </section>

      <section className="provider-grid-react">
        {providers.map((provider) => {
          const providerRoutes = routesByProvider.get(provider.id) ?? [];
          return <article className="card provider-card" key={provider.id}>
            <div className="section-head"><div><h3>{provider.name}</h3><p>{provider.protocol} · <code>{provider.base_url}</code></p></div><span className="badge muted-badge">{providerRoutes.length} models</span></div>
            <div className="provider-models">{providerRoutes.map((route) => <div key={route.id}><b>{route.remote_model}</b><span className={`badge ${route.enabled && route.health === "healthy" ? "ok" : "muted-badge"}`}>{route.enabled ? route.health : "disabled"}</span></div>)}</div>
            <div className="actions"><button onClick={() => void discover(provider.id)}>发现新模型</button><a href={provider.official_url} target="_blank" rel="noreferrer">官网 ↗</a></div>
          </article>;
        })}
      </section>

      <section className="grid-two model-editor-grid">
        <form className="card form-card" onSubmit={saveRoute}>
          <div className="section-head"><div><h2>{editing ? "编辑模型" : "添加模型 / 批量模型"}</h2><p>自定义 Provider 可在保存前用临时 API Key 验证，不会把 Key 回显到页面。</p></div><button type="button" onClick={() => { setDraft((current) => ({ ...current, provider_id: CUSTOM_PROVIDER_ID })); setCustomProvider(atomGitPreset()); }}>AtomGit 本机预设</button></div>
          <div className="form-grid">
            <label>Provider<select required value={draft.provider_id} onChange={(event) => {
              const providerId = event.target.value;
              const provider = providers.find((item) => item.id === providerId);
              const groqPreset = provider?.name.trim().toLowerCase() === "groq" && !draft.remote_model.trim();
              setDraft({ ...draft, provider_id: providerId, remote_model: groqPreset ? "openai/gpt-oss-120b" : draft.remote_model });
            }}><option value="">请选择</option>{providers.map((provider) => <option key={provider.id} value={provider.id}>{provider.name} · {provider.protocol}</option>)}<option value={CUSTOM_PROVIDER_ID}>＋ 自定义 Provider</option></select></label>
            <label>模型<input list="provider-model-options" required value={draft.remote_model} onChange={(event) => setDraft({ ...draft, remote_model: event.target.value })} /><datalist id="provider-model-options">{modelOptions.map((model) => <option value={model} key={model} />)}</datalist></label>
            <label>显示名<input value={draft.display_name} onChange={(event) => setDraft({ ...draft, display_name: event.target.value })} /></label>
            <label>优先级<input type="number" min={1} value={draft.priority} onChange={(event) => setDraft({ ...draft, priority: Number(event.target.value) })} /></label>
            <label>能力（逗号分隔）<input value={draft.capabilities} onChange={(event) => setDraft({ ...draft, capabilities: event.target.value })} /></label>
            <label>Reasoning Effort<input placeholder="medium / high / low" value={draft.reasoning_effort} onChange={(event) => setDraft({ ...draft, reasoning_effort: event.target.value })} /></label>
            <label>输入价 / 1M<input type="number" min="0" step="0.000001" value={draft.input_price_per_million} onChange={(event) => setDraft({ ...draft, input_price_per_million: event.target.value })} /></label>
            <label>输出价 / 1M<input type="number" min="0" step="0.000001" value={draft.output_price_per_million} onChange={(event) => setDraft({ ...draft, output_price_per_million: event.target.value })} /></label>
            <label>币种<input value={draft.pricing_currency} maxLength={8} onChange={(event) => setDraft({ ...draft, pricing_currency: event.target.value })} /></label>
            <label>API Key（仅验证/保存本次）<input type="password" value={draft.credential} onChange={(event) => setDraft({ ...draft, credential: event.target.value })} /></label>
            <label>公开注册 URL<input value={draft.public_url} onChange={(event) => setDraft({ ...draft, public_url: event.target.value })} /></label>
            <label>公开文档 URL<input value={draft.public_docs_url} onChange={(event) => setDraft({ ...draft, public_docs_url: event.target.value })} /></label>
            <label>目录状态<select value={draft.catalog_status} onChange={(event) => setDraft({ ...draft, catalog_status: event.target.value as "draft" | "published" })}><option value="draft">draft · 进入 review</option><option value="published">published · 可导出公开</option></select></label>
            <label className="full">免费说明<input value={draft.free_summary} onChange={(event) => setDraft({ ...draft, free_summary: event.target.value })} /></label>
          </div>
          {draft.provider_id === CUSTOM_PROVIDER_ID && <ProviderFields value={customProvider} onChange={setCustomProvider} prefix="custom-provider" />}
          <div className="form-actions"><button type="button" onClick={() => void validateAndFetchModels()}>验证连接并获取模型</button><button className="primary" type="submit">保存当前模型</button></div>
          {!!modelOptions.length && <div className="bulk-picker-react">
            <div className="section-head"><div><h3>批量模型</h3><p>验证返回的模型可以一次加入模型池。</p></div><div className="actions"><button type="button" onClick={() => setSelectedModels(modelOptions)}>全选</button><button type="button" onClick={() => setSelectedModels([])}>全不选</button></div></div>
            <div className="check-grid">{modelOptions.map((model) => <label key={model}><input type="checkbox" checked={selectedModels.includes(model)} onChange={(event) => setSelectedModels((current) => event.target.checked ? [...current, model] : current.filter((item) => item !== model))} />{model}</label>)}</div>
            <div className="form-actions"><button className="primary" type="button" onClick={() => void saveSelectedModels()}>保存选中模型（{selectedModels.length}）</button></div>
          </div>}
        </form>

        <form className="card form-card" onSubmit={saveProvider}>
          <div className="section-head"><div><h2>添加 Provider</h2><p>同一个 Provider 名称可以有多个连接；连接身份由协议 + Base URL 区分。</p></div></div>
          <ProviderFields value={providerDraft} onChange={setProviderDraft} prefix="provider-form" />
          <div className="form-actions"><button type="button" onClick={() => setProviderDraft(atomGitPreset())}>AtomGit 预设</button><button className="primary" type="submit">保存 Provider</button></div>
        </form>
      </section>

      <section className="card">
        <div className="section-head"><div><h2>多 Provider 批量连接</h2><p>每个连接独立验证 API Key、选择模型，最后一次提交；失败连接不会污染其他连接。</p></div><div className="actions"><button onClick={() => addMultiConnection()}>＋ 自定义连接</button>{providers.slice(0, 4).map((provider) => <button key={provider.id} onClick={() => addMultiConnection(provider)}>＋ {provider.name}</button>)}</div></div>
        <div className="multi-grid">
          {multiConnections.map((item) => <article className="connection-card" key={item.key}>
            <div className="section-head"><div><h3>{item.provider.name || "新连接"}</h3><p>{item.status === "validated" ? `已验证 · ${item.models.length} models` : item.status === "validating" ? "验证中…" : item.error || "待验证"}</p></div><button className="danger" onClick={() => setMultiConnections((current) => current.filter((candidate) => candidate.key !== item.key))}>移除</button></div>
            <ProviderFields value={item.provider} onChange={(provider) => updateMulti(item.key, { provider, status: "idle", models: [], selected_models: [] })} prefix={`multi-${item.key}`} />
            <label>API Key<input type="password" value={item.credential} onChange={(event) => updateMulti(item.key, { credential: event.target.value, status: "idle" })} /></label>
            <div className="form-actions"><button disabled={!item.credential || item.status === "validating"} onClick={() => void validateMulti(item)}>验证并获取模型</button></div>
            {!!item.models.length && <div className="check-grid compact">{item.models.map((model) => <label key={model}><input type="checkbox" checked={item.selected_models.includes(model)} onChange={(event) => updateMulti(item.key, { selected_models: event.target.checked ? [...item.selected_models, model] : item.selected_models.filter((value) => value !== model) })} />{model}</label>)}</div>}
          </article>)}
        </div>
        {!multiConnections.length && <p className="empty">添加一个或多个 Provider 连接后开始验证。</p>}
        {!!multiConnections.length && <div className="form-actions"><button className="primary" onClick={() => void saveMultiConnections()}>批量加入全部已验证连接</button></div>}
      </section>

      <section className="card">
        <div className="section-head"><div><h2>连接日志</h2><p>安全日志只展示路由、结果、耗时和 Usage，不展示 Prompt / API Key。</p></div></div>
        <div className="table-wrap"><table><thead><tr><th>请求</th><th>路由</th><th>Tenant / App</th><th>结果</th><th>耗时</th><th>Token</th></tr></thead><tbody>
          {connections.map((entry, index) => <tr key={entry.request_id ?? index}><td><code>{entry.request_id ?? "—"}</code><small>{entry.requested_model ?? ""}</small></td><td>{entry.provider_id ?? "—"}<small>{entry.remote_model ?? ""}</small></td><td>{entry.tenant_id ?? "system"}<small>{entry.application_id ?? "legacy-global"}</small></td><td><span className={`badge ${entry.status === "success" ? "ok" : "bad"}`}>{entry.status ?? "unknown"}</span></td><td>{entry.elapsed_ms == null ? "—" : `${entry.elapsed_ms} ms`}</td><td>{formatCount(entry.usage?.total_tokens)}</td></tr>)}
          {!connections.length && <tr><td colSpan={6} className="empty">暂无连接日志。</td></tr>}
        </tbody></table></div>
      </section>
    </div>
  );
}
