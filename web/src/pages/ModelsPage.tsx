import { useEffect, useMemo, useState, type FormEvent } from "react";
import { api } from "../api/client";
import {
  CATALOG_DRAFT_KEY,
  CUSTOM_PROVIDER_ID,
  atomGitPreset,
  connectionKey,
  type ProviderDraft,
} from "../features/models/connection";
import { useI18n } from "../i18n";
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
  const { t } = useI18n();
  return (
    <div className="provider-fields" data-testid={prefix}>
      <label>Provider ID<input required value={value.id} onChange={(event) => onChange({ ...value, id: event.target.value })} /></label>
      <label>{t("common.name")}<input required value={value.name} onChange={(event) => onChange({ ...value, name: event.target.value })} /></label>
      <label>{t("common.protocol")}<select value={value.protocol} onChange={(event) => onChange({ ...value, protocol: event.target.value })}><option value="openai">OpenAI Compatible</option><option value="gemini">Gemini Native</option><option value="anthropic">Anthropic Native</option></select></label>
      <label>Base URL<input required placeholder="https://api.example.com/v1" value={value.base_url} onChange={(event) => onChange({ ...value, base_url: event.target.value })} /></label>
      <label>{t("common.officialSite")}<input required placeholder="https://example.com" value={value.official_url} onChange={(event) => onChange({ ...value, official_url: event.target.value })} /></label>
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
  const { t, status, errorText } = useI18n();
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
          ? t("models.catalogPrefilled")
          : t("models.catalogNoEndpoint"),
      );
    } catch {
      setMessage(t("models.catalogInvalid"));
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
        throw new Error(t("models.providerConflict"));
      }
      return existing;
    }
    return api<Provider>("/api/admin/providers", { method: "POST", body: providerPayload(provider) });
  }

  async function validateAndFetchModels() {
    const provider = activeProvider();
    if (!provider || !draft.credential.trim()) {
      setMessage(t("models.needProviderKey"));
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
      setMessage(t("models.connectionOk", { count: result.data?.length ?? 0 }));
    } catch (error) {
      setMessage(errorText(error));
    }
  }

  async function saveRoute(event: FormEvent) {
    event.preventDefault();
    const provider = activeProvider();
    if (!provider) {
      setMessage(t("models.providerRequired"));
      return;
    }
    try {
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
      setMessage(t("models.routeSaved"));
      await onRefresh();
    } catch (error) {
      setMessage(errorText(error));
    }
  }

  async function saveSelectedModels() {
    const provider = activeProvider();
    if (!provider || !selectedModels.length) {
      setMessage(t("models.needModels"));
      return;
    }
    try {
      const result = await api<{ data: { created: Route[]; skipped: Array<{ remote_model: string }> } }>("/api/admin/routes/bulk", {
        method: "POST",
        body: {
          provider: providerPayload(provider),
          models: selectedModels.map((remote_model) => ({ remote_model, enabled: true })),
          ...routeCommonPayload(),
          ...(draft.credential.trim() ? { credential: draft.credential.trim() } : {}),
        },
      });
      setMessage(t("models.bulkDone", { created: result.data.created.length, skipped: result.data.skipped.length }));
      await onRefresh();
    } catch (error) {
      setMessage(errorText(error));
    }
  }

  async function mutate(route: Route, action: "probe" | "toggle" | "delete") {
    try {
      if (action === "probe") await api(`/api/admin/routes/${encodeURIComponent(route.id)}/probe`, { method: "POST" });
      if (action === "toggle") await api(`/api/admin/routes/${encodeURIComponent(route.id)}`, { method: "PATCH", body: { enabled: !route.enabled } });
      if (action === "delete") await api(`/api/admin/routes/${encodeURIComponent(route.id)}`, { method: "DELETE" });
      await onRefresh();
    } catch (error) {
      setMessage(errorText(error));
    }
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
          setMessage(t("models.probeRateLimited", { count: checked }));
          await onRefresh();
          return;
        }
      }
    }
    setMessage(t("models.probeDone", { count: checked }));
    await onRefresh();
  }

  async function discover(providerId: string) {
    try {
      const result = await api<{ data: Route[] }>(`/api/admin/providers/${encodeURIComponent(providerId)}/discover`, { method: "POST" });
      setMessage(t("models.discoverDone", { count: result.data.length }));
      await onRefresh();
    } catch (error) {
      setMessage(errorText(error));
    }
  }

  async function move(index: number, delta: -1 | 1) {
    const next = index + delta;
    if (next < 0 || next >= ordered.length) return;
    const ids = ordered.map((route) => route.id);
    [ids[index], ids[next]] = [ids[next], ids[index]];
    try {
      await api("/api/admin/routes/reorder", { method: "POST", body: { ids } });
      await onRefresh();
    } catch (error) {
      setMessage(errorText(error));
    }
  }

  async function saveProvider(event: FormEvent) {
    event.preventDefault();
    try {
      await api("/api/admin/providers", { method: "POST", body: providerPayload(providerDraft) });
      setProviderDraft(blankProvider());
      setMessage(t("models.providerSaved"));
      await onRefresh();
    } catch (error) {
      setMessage(errorText(error));
    }
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
      updateMulti(item.key, { status: "error", error: errorText(error) });
    }
  }

  async function saveMultiConnections() {
    const ready = multiConnections.filter((item) => item.status === "validated" && item.selected_models.length);
    if (!ready.length || ready.length !== multiConnections.length) {
      setMessage(t("models.multiNeedValidation"));
      return;
    }
    try {
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
      setMessage(t("models.multiDone", { created: result.data.created.length, skipped: result.data.skipped.length, failed: result.data.failed.length }));
      setMultiConnections([]);
      await onRefresh();
    } catch (error) {
      setMessage(errorText(error));
    }
  }

  return (
    <div className="stack">
      {message && <div className="notice">{message}</div>}

      <section className="card">
        <div className="section-head">
          <div><h2>{t("models.title")}</h2><p>{t("models.desc")}</p></div>
          <div className="actions"><button onClick={() => void probeAll()}>{t("models.probeAll")}</button><button className="primary" onClick={() => { setEditing(null); setDraft(blankRoute()); }}>{t("models.add")}</button></div>
        </div>
        <div className="table-wrap"><table><thead><tr><th>#</th><th>{t("common.model")}</th><th>Provider</th><th>{t("common.capability")}</th><th>{t("common.pricePerMillion")}</th><th>{t("common.runtimeStatus")}</th><th>{t("common.catalogStatus")}</th><th>{t("common.actions")}</th></tr></thead>
          <tbody>{ordered.map((route, index) => <tr key={route.id}>
            <td>{route.priority}</td>
            <td><b>{route.display_name || route.remote_model}</b><small>{route.remote_model}</small></td>
            <td>{route.provider_name}</td>
            <td>{route.capabilities.map((cap) => <span className="tag" key={cap}>{cap}</span>)}</td>
            <td>{route.pricing.input_per_million == null && route.pricing.output_per_million == null ? "—" : `${route.pricing.currency} ${route.pricing.input_per_million ?? "?"} / ${route.pricing.output_per_million ?? "?"}`}</td>
            <td><span className={`badge ${!route.enabled ? "muted-badge" : route.health === "healthy" ? "ok" : "warn"}`}>{status(route.enabled ? route.health : "disabled")}</span></td>
            <td><span className={`badge ${route.catalog_status === "published" ? "ok" : "muted-badge"}`}>{status(route.catalog_status)}</span></td>
            <td><div className="actions">
              <button onClick={() => void move(index, -1)}>↑</button><button onClick={() => void move(index, 1)}>↓</button>
              <button onClick={() => edit(route)}>{t("common.edit")}</button><button onClick={() => void mutate(route, "probe")}>{t("common.probe")}</button>
              <button onClick={() => void mutate(route, "toggle")}>{route.enabled ? t("common.disable") : t("common.enable")}</button>
              <button className="danger" onClick={() => void mutate(route, "delete")}>{t("common.delete")}</button>
            </div></td>
          </tr>)}{!ordered.length && <tr><td colSpan={8} className="empty">{t("models.empty")}</td></tr>}</tbody>
        </table></div>
      </section>

      <section className="provider-grid-react">
        {providers.map((provider) => {
          const providerRoutes = routesByProvider.get(provider.id) ?? [];
          return <article className="card provider-card" key={provider.id}>
            <div className="section-head"><div><h3>{provider.name}</h3><p>{provider.protocol} · <code>{provider.base_url}</code></p></div><span className="badge muted-badge">{t("models.modelsCount", { count: providerRoutes.length })}</span></div>
            <div className="provider-models">{providerRoutes.map((route) => <div key={route.id}><b>{route.remote_model}</b><span className={`badge ${route.enabled && route.health === "healthy" ? "ok" : "muted-badge"}`}>{status(route.enabled ? route.health : "disabled")}</span></div>)}</div>
            <div className="actions"><button onClick={() => void discover(provider.id)}>{t("models.discover")}</button><a href={provider.official_url} target="_blank" rel="noreferrer">{t("common.officialSite")} ↗</a></div>
          </article>;
        })}
      </section>

      <section className="grid-two model-editor-grid">
        <form className="card form-card" onSubmit={saveRoute}>
          <div className="section-head"><div><h2>{editing ? t("models.editTitle") : t("models.addBulkTitle")}</h2><p>{t("models.editorDesc")}</p></div><button type="button" onClick={() => { setDraft((current) => ({ ...current, provider_id: CUSTOM_PROVIDER_ID })); setCustomProvider(atomGitPreset(t("models.atomgitProviderName"))); }}>{t("models.atomgitPreset")}</button></div>
          <div className="form-grid">
            <label>Provider<select required value={draft.provider_id} onChange={(event) => {
              const providerId = event.target.value;
              const provider = providers.find((item) => item.id === providerId);
              const groqPreset = provider?.name.trim().toLowerCase() === "groq" && !draft.remote_model.trim();
              setDraft({ ...draft, provider_id: providerId, remote_model: groqPreset ? "openai/gpt-oss-120b" : draft.remote_model });
            }}><option value="">{t("common.select")}</option>{providers.map((provider) => <option key={provider.id} value={provider.id}>{provider.name} · {provider.protocol}</option>)}<option value={CUSTOM_PROVIDER_ID}>{t("models.customProvider")}</option></select></label>
            <label>{t("common.model")}<input list="provider-model-options" required value={draft.remote_model} onChange={(event) => setDraft({ ...draft, remote_model: event.target.value })} /><datalist id="provider-model-options">{modelOptions.map((model) => <option value={model} key={model} />)}</datalist></label>
            <label>{t("models.displayName")}<input value={draft.display_name} onChange={(event) => setDraft({ ...draft, display_name: event.target.value })} /></label>
            <label>{t("models.priority")}<input type="number" min={1} value={draft.priority} onChange={(event) => setDraft({ ...draft, priority: Number(event.target.value) })} /></label>
            <label>{t("models.capabilitiesCsv")}<input value={draft.capabilities} onChange={(event) => setDraft({ ...draft, capabilities: event.target.value })} /></label>
            <label>Reasoning Effort<input placeholder="medium / high / low" value={draft.reasoning_effort} onChange={(event) => setDraft({ ...draft, reasoning_effort: event.target.value })} /></label>
            <label>{t("models.inputPrice")}<input type="number" min="0" step="0.000001" value={draft.input_price_per_million} onChange={(event) => setDraft({ ...draft, input_price_per_million: event.target.value })} /></label>
            <label>{t("models.outputPrice")}<input type="number" min="0" step="0.000001" value={draft.output_price_per_million} onChange={(event) => setDraft({ ...draft, output_price_per_million: event.target.value })} /></label>
            <label>{t("common.currency")}<input value={draft.pricing_currency} maxLength={8} onChange={(event) => setDraft({ ...draft, pricing_currency: event.target.value })} /></label>
            <label>{t("models.apiKeyOnce")}<input type="password" value={draft.credential} onChange={(event) => setDraft({ ...draft, credential: event.target.value })} /></label>
            <label>{t("models.publicRegister")}<input value={draft.public_url} onChange={(event) => setDraft({ ...draft, public_url: event.target.value })} /></label>
            <label>{t("models.publicDocs")}<input value={draft.public_docs_url} onChange={(event) => setDraft({ ...draft, public_docs_url: event.target.value })} /></label>
            <label>{t("common.catalogStatus")}<select value={draft.catalog_status} onChange={(event) => setDraft({ ...draft, catalog_status: event.target.value as "draft" | "published" })}><option value="draft">{t("models.catalogDraft")}</option><option value="published">{t("models.catalogPublished")}</option></select></label>
            <label className="full">{t("models.freeSummary")}<input value={draft.free_summary} onChange={(event) => setDraft({ ...draft, free_summary: event.target.value })} /></label>
          </div>
          {draft.provider_id === CUSTOM_PROVIDER_ID && <ProviderFields value={customProvider} onChange={setCustomProvider} prefix="custom-provider" />}
          <div className="form-actions"><button type="button" onClick={() => void validateAndFetchModels()}>{t("models.validateFetch")}</button><button className="primary" type="submit">{t("models.saveCurrent")}</button></div>
          {!!modelOptions.length && <div className="bulk-picker-react">
            <div className="section-head"><div><h3>{t("models.bulkTitle")}</h3><p>{t("models.bulkDesc")}</p></div><div className="actions"><button type="button" onClick={() => setSelectedModels(modelOptions)}>{t("models.selectAll")}</button><button type="button" onClick={() => setSelectedModels([])}>{t("models.selectNone")}</button></div></div>
            <div className="check-grid">{modelOptions.map((model) => <label key={model}><input type="checkbox" checked={selectedModels.includes(model)} onChange={(event) => setSelectedModels((current) => event.target.checked ? [...current, model] : current.filter((item) => item !== model))} />{model}</label>)}</div>
            <div className="form-actions"><button className="primary" type="button" onClick={() => void saveSelectedModels()}>{t("models.saveSelected", { count: selectedModels.length })}</button></div>
          </div>}
        </form>

        <form className="card form-card" onSubmit={saveProvider}>
          <div className="section-head"><div><h2>{t("models.providerAddTitle")}</h2><p>{t("models.providerAddDesc")}</p></div></div>
          <ProviderFields value={providerDraft} onChange={setProviderDraft} prefix="provider-form" />
          <div className="form-actions"><button type="button" onClick={() => setProviderDraft(atomGitPreset(t("models.atomgitProviderName")))}>{t("models.atomgitPreset")}</button><button className="primary" type="submit">{t("models.saveProvider")}</button></div>
        </form>
      </section>

      <section className="card">
        <div className="section-head"><div><h2>{t("models.multiTitle")}</h2><p>{t("models.multiDesc")}</p></div><div className="actions"><button onClick={() => addMultiConnection()}>{t("models.addCustomConnection")}</button>{providers.slice(0, 4).map((provider) => <button key={provider.id} onClick={() => addMultiConnection(provider)}>＋ {provider.name}</button>)}</div></div>
        <div className="multi-grid">
          {multiConnections.map((item) => <article className="connection-card" key={item.key}>
            <div className="section-head"><div><h3>{item.provider.name || t("models.newConnection")}</h3><p>{item.status === "validated" ? t("models.validatedModels", { count: item.models.length }) : item.status === "validating" ? t("models.validating") : item.error || t("models.pendingValidation")}</p></div><button className="danger" onClick={() => setMultiConnections((current) => current.filter((candidate) => candidate.key !== item.key))}>{t("models.remove")}</button></div>
            <ProviderFields value={item.provider} onChange={(provider) => updateMulti(item.key, { provider, status: "idle", models: [], selected_models: [] })} prefix={`multi-${item.key}`} />
            <label>API Key<input type="password" value={item.credential} onChange={(event) => updateMulti(item.key, { credential: event.target.value, status: "idle" })} /></label>
            <div className="form-actions"><button disabled={!item.credential || item.status === "validating"} onClick={() => void validateMulti(item)}>{t("models.validateFetch")}</button></div>
            {!!item.models.length && <div className="check-grid compact">{item.models.map((model) => <label key={model}><input type="checkbox" checked={item.selected_models.includes(model)} onChange={(event) => updateMulti(item.key, { selected_models: event.target.checked ? [...item.selected_models, model] : item.selected_models.filter((value) => value !== model) })} />{model}</label>)}</div>}
          </article>)}
        </div>
        {!multiConnections.length && <p className="empty">{t("models.noMultiConnections")}</p>}
        {!!multiConnections.length && <div className="form-actions"><button className="primary" onClick={() => void saveMultiConnections()}>{t("models.bulkSaveConnections")}</button></div>}
      </section>

      <section className="card">
        <div className="section-head"><div><h2>{t("models.logTitle")}</h2><p>{t("models.logDesc")}</p></div></div>
        <div className="table-wrap"><table><thead><tr><th>{t("models.request")}</th><th>{t("models.route")}</th><th>{t("overview.tenantApp")}</th><th>{t("common.result")}</th><th>{t("common.latency")}</th><th>Token</th></tr></thead><tbody>
          {connections.map((entry, index) => <tr key={entry.request_id ?? index}><td><code>{entry.request_id ?? "—"}</code><small>{entry.requested_model ?? ""}</small></td><td>{entry.provider_id ?? "—"}<small>{entry.remote_model ?? ""}</small></td><td>{entry.tenant_id ?? "system"}<small>{entry.application_id ?? "legacy-global"}</small></td><td><span className={`badge ${entry.status === "success" ? "ok" : "bad"}`}>{status(entry.status)}</span></td><td>{entry.elapsed_ms == null ? "—" : `${entry.elapsed_ms} ms`}</td><td>{formatCount(entry.usage?.total_tokens)}</td></tr>)}
          {!connections.length && <tr><td colSpan={6} className="empty">{t("models.noLogs")}</td></tr>}
        </tbody></table></div>
      </section>
    </div>
  );
}
