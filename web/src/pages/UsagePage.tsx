import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { api } from "../api/client";
import { useI18n } from "../i18n";
import { formatCosts, formatCount, quotaTone } from "../lib/format";
import type { QuotaPolicy, QuotaStatus, UsageGroup, UsageSummary } from "../types";

type Filters = { tenant_id: string; application_id: string; provider_id: string; remote_model: string };
const emptyFilters: Filters = { tenant_id: "", application_id: "", provider_id: "", remote_model: "" };

function QuotaBadge({ row }: { row: UsageGroup }) {
  const { t } = useI18n();
  const tone = quotaTone(row.quota);
  if (tone === "none") return <span className="badge muted-badge">{t("common.unconfigured")}</span>;
  return <span className={`badge ${tone === "bad" ? "bad" : tone === "warn" ? "warn" : "ok"}`}>{tone === "bad" ? t("common.exceeded") : tone === "warn" ? t("common.warning") : t("common.normal")}</span>;
}

function quotaTokens(quota: QuotaStatus | null | undefined, t: ReturnType<typeof useI18n>["t"]): string {
  if (!quota) return t("common.unconfigured");
  const remaining = quota.remaining_tokens == null ? t("common.unlimited") : formatCount(quota.remaining_tokens);
  return `${formatCount(quota.used_tokens)} / ${remaining}`;
}

function quotaCost(quota: QuotaStatus | null | undefined, t: ReturnType<typeof useI18n>["t"]): string {
  if (!quota) return t("common.unconfigured");
  const remaining = quota.remaining_cost == null
    ? t("common.unlimited")
    : `${quota.currency} ${quota.remaining_cost.toLocaleString(undefined, { maximumFractionDigits: 6 })}`;
  const suffix = quota.cost_complete ? "" : ` · ${t("usage.costIncomplete")}`;
  return `${quota.currency} ${quota.used_cost.toLocaleString(undefined, { maximumFractionDigits: 6 })} / ${remaining}${suffix}`;
}

export function UsagePage() {
  const { t, errorText } = useI18n();
  const [days, setDays] = useState(7);
  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [quotas, setQuotas] = useState<QuotaPolicy[]>([]);
  const [error, setError] = useState("");
  const [quotaDraft, setQuotaDraft] = useState({
    scope_type: "tenant" as "tenant" | "application",
    scope_id: "",
    token_limit: "",
    cost_limit: "",
    currency: "USD",
    warning_threshold_percent: "80",
  });

  const load = useCallback(async () => {
    const params = new URLSearchParams({ days: String(days) });
    Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value); });
    try {
      const [usageResult, quotaResult] = await Promise.all([
        api<{ data: UsageSummary }>(`/api/admin/usage?${params}`),
        api<{ data: QuotaPolicy[] }>("/api/admin/quotas"),
      ]);
      setUsage(usageResult.data);
      setQuotas(quotaResult.data);
      setError("");
    } catch (reason) {
      setError(errorText(reason));
    }
  }, [days, filters, errorText]);

  useEffect(() => { void load(); }, [load]);

  const targets = useMemo(() => {
    if (!usage) return [];
    return quotaDraft.scope_type === "tenant"
      ? usage.filter_options.tenants.map((item) => ({ id: item.id, label: item.name }))
      : usage.filter_options.applications.map((item) => ({ id: item.id, label: `${item.name} · ${item.tenant_id}` }));
  }, [usage, quotaDraft.scope_type]);

  useEffect(() => {
    const target = targets.some((item) => item.id === quotaDraft.scope_id) ? quotaDraft.scope_id : targets[0]?.id ?? "";
    const policy = quotas.find((item) => item.scope_type === quotaDraft.scope_type && item.scope_id === target);
    setQuotaDraft((current) => ({
      ...current,
      scope_id: target,
      token_limit: policy?.token_limit?.toString() ?? "",
      cost_limit: policy?.cost_limit?.toString() ?? "",
      currency: policy?.currency ?? "USD",
      warning_threshold_percent: policy?.warning_threshold_percent?.toString() ?? "80",
    }));
  }, [quotaDraft.scope_type, quotas, targets]);

  async function saveQuota(event: FormEvent) {
    event.preventDefault();
    if (!quotaDraft.scope_id) return;
    try {
      await api(`/api/admin/quotas/${quotaDraft.scope_type}/${encodeURIComponent(quotaDraft.scope_id)}`, {
        method: "PUT",
        body: {
          token_limit: quotaDraft.token_limit === "" ? null : Number(quotaDraft.token_limit),
          cost_limit: quotaDraft.cost_limit === "" ? null : Number(quotaDraft.cost_limit),
          currency: quotaDraft.currency.trim().toUpperCase() || "USD",
          warning_threshold_percent: Number(quotaDraft.warning_threshold_percent || 80),
        },
      });
      setError("");
      await load();
    } catch (reason) {
      setError(errorText(reason));
    }
  }

  if (!usage) return <section className="card">{error ? <div className="notice bad">{error}</div> : t("usage.loading")}</section>;

  const apps = usage.filter_options.applications.filter((item) => !filters.tenant_id || item.tenant_id === filters.tenant_id);
  const models = usage.filter_options.models.filter((item) => !filters.provider_id || item.provider_id === filters.provider_id);

  return (
    <div className="stack">
      {error && <div className="notice bad">{error}</div>}
      <section className="card">
        <div className="section-head"><div><h2>{t("usage.title")}</h2><p>{t("usage.desc")}</p></div><div className="actions">{[1, 7, 30].map((value) => <button className={days === value ? "primary" : ""} key={value} onClick={() => setDays(value)}>{value === 1 ? "24h" : `${value}d`}</button>)}</div></div>
        <div className="filter-grid">
          <label>{t("common.tenant")}<select value={filters.tenant_id} onChange={(event) => setFilters({ ...filters, tenant_id: event.target.value, application_id: "" })}><option value="">{t("usage.allTenants")}</option>{usage.filter_options.tenants.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <label>{t("common.application")}<select value={filters.application_id} onChange={(event) => setFilters({ ...filters, application_id: event.target.value })}><option value="">{t("usage.allApplications")}</option>{apps.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <label>Provider<select value={filters.provider_id} onChange={(event) => setFilters({ ...filters, provider_id: event.target.value, remote_model: "" })}><option value="">{t("usage.allProviders")}</option>{usage.filter_options.providers.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <label>{t("common.model")}<select value={filters.remote_model} onChange={(event) => setFilters({ ...filters, remote_model: event.target.value })}><option value="">{t("usage.allModels")}</option>{models.map((item) => <option key={item.id + item.provider_id} value={item.id}>{item.id}</option>)}</select></label>
        </div>
        <div className="form-actions"><button onClick={() => setFilters(emptyFilters)}>{t("usage.reset")}</button></div>
      </section>

      <section className="stat-grid six">
        <article className="card stat"><b>{formatCount(usage.total_tokens)}</b><span>{t("usage.totalTokens")}</span></article>
        <article className="card stat"><b>{formatCount(usage.prompt_tokens)}</b><span>{t("usage.inputTokens")}</span></article>
        <article className="card stat"><b>{formatCount(usage.completion_tokens)}</b><span>{t("usage.outputTokens")}</span></article>
        <article className="card stat"><b>{formatCount(usage.calls)}</b><span>{t("common.calls")}</span></article>
        <article className="card stat"><b>{formatCosts(usage.estimated_costs)}</b><span>{t("usage.estimatedCost")}</span></article>
        <article className="card stat"><b>{usage.priced_calls} / {usage.calls}</b><span>{t("usage.pricedCalls")}</span></article>
      </section>

      <section className="card">
        <div className="section-head"><div><h2>{t("usage.quotaTitle")}</h2><p>{t("usage.quotaDesc")}</p></div></div>
        <form className="filter-grid quota-editor" onSubmit={saveQuota}>
          <label>{t("common.scope")}<select value={quotaDraft.scope_type} onChange={(event) => setQuotaDraft({ ...quotaDraft, scope_type: event.target.value as "tenant" | "application", scope_id: "" })}><option value="tenant">{t("common.tenant")}</option><option value="application">{t("common.application")}</option></select></label>
          <label>{t("common.target")}<select value={quotaDraft.scope_id} onChange={(event) => setQuotaDraft({ ...quotaDraft, scope_id: event.target.value })}>{targets.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
          <label>{t("usage.monthTokenQuota")}<input type="number" min="0" value={quotaDraft.token_limit} onChange={(event) => setQuotaDraft({ ...quotaDraft, token_limit: event.target.value })} /></label>
          <label>{t("usage.monthCostBudget")}<input type="number" min="0" step="0.000001" value={quotaDraft.cost_limit} onChange={(event) => setQuotaDraft({ ...quotaDraft, cost_limit: event.target.value })} /></label>
          <label>{t("common.currency")}<input maxLength={8} value={quotaDraft.currency} onChange={(event) => setQuotaDraft({ ...quotaDraft, currency: event.target.value })} /></label>
          <label>{t("usage.warningThreshold")}<input type="number" min="0" max="100" step="0.1" value={quotaDraft.warning_threshold_percent} onChange={(event) => setQuotaDraft({ ...quotaDraft, warning_threshold_percent: event.target.value })} /></label>
          <div className="form-actions"><button className="primary" type="submit">{t("usage.saveQuota")}</button></div>
        </form>
      </section>

      <section className="grid-two">
        <UsageTable title={t("usage.byTenant")} rows={usage.by_tenant} kind="tenant" />
        <UsageTable title={t("usage.byApplication")} rows={usage.by_application} kind="application" />
      </section>
      <section className="grid-two">
        <UsageTable title={t("usage.byProvider")} rows={usage.by_provider} kind="provider" />
        <UsageTable title={t("usage.byModel")} rows={usage.by_model} kind="model" />
      </section>
      <UsageTable title={t("usage.byDay")} rows={usage.by_day} kind="day" />
    </div>
  );
}

function UsageTable({ title, rows, kind }: { title: string; rows: UsageGroup[]; kind: "tenant" | "application" | "provider" | "model" | "day" }) {
  const { t } = useI18n();
  return (
    <section className="card">
      <div className="section-head"><div><h2>{title}</h2></div></div>
      <div className="table-wrap"><table><thead><tr><th>{t("usage.dimension")}</th><th>Token</th><th>{t("usage.estimatedCost")}</th>{(kind === "tenant" || kind === "application") && <><th>{t("usage.tokenQuota")}</th><th>{t("usage.costQuota")}</th><th>{t("common.status")}</th></>}</tr></thead>
        <tbody>{rows.map((row, index) => {
          const label = row.tenant_name || row.application_name || row.provider_name || row.remote_model || row.day || t("common.unknown");
          const sub = row.tenant_id || row.application_id || row.provider_id || "";
          return <tr key={`${label}-${sub}-${index}`}><td><b>{label}</b>{sub && sub !== label && <small>{sub}</small>}</td><td>{formatCount(row.total_tokens)}</td><td>{formatCosts(row.estimated_costs)}</td>{(kind === "tenant" || kind === "application") && <><td>{quotaTokens(row.quota, t)}</td><td>{quotaCost(row.quota, t)}</td><td><QuotaBadge row={row} /></td></>}</tr>;
        })}{!rows.length && <tr><td className="empty" colSpan={6}>{t("usage.empty")}</td></tr>}</tbody>
      </table></div>
    </section>
  );
}
