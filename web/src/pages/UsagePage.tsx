import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { api } from "../api/client";
import { formatCosts, formatCount, quotaCost, quotaTone, quotaTokens } from "../lib/format";
import type { QuotaPolicy, UsageGroup, UsageSummary } from "../types";

type Filters = { tenant_id: string; application_id: string; provider_id: string; remote_model: string };
const emptyFilters: Filters = { tenant_id: "", application_id: "", provider_id: "", remote_model: "" };

function QuotaBadge({ row }: { row: UsageGroup }) {
  const tone = quotaTone(row.quota);
  if (tone === "none") return <span className="badge muted-badge">未配置</span>;
  return <span className={`badge ${tone === "bad" ? "bad" : tone === "warn" ? "warn" : "ok"}`}>{tone === "bad" ? "已超额" : tone === "warn" ? "预警" : "正常"}</span>;
}

export function UsagePage() {
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
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, [days, filters]);

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
    await api(`/api/admin/quotas/${quotaDraft.scope_type}/${encodeURIComponent(quotaDraft.scope_id)}`, {
      method: "PUT",
      body: {
        token_limit: quotaDraft.token_limit === "" ? null : Number(quotaDraft.token_limit),
        cost_limit: quotaDraft.cost_limit === "" ? null : Number(quotaDraft.cost_limit),
        currency: quotaDraft.currency.trim().toUpperCase() || "USD",
        warning_threshold_percent: Number(quotaDraft.warning_threshold_percent || 80),
      },
    });
    await load();
  }

  if (!usage) return <section className="card">{error ? <div className="notice bad">{error}</div> : "正在加载 Usage…"}</section>;

  const apps = usage.filter_options.applications.filter((item) => !filters.tenant_id || item.tenant_id === filters.tenant_id);
  const models = usage.filter_options.models.filter((item) => !filters.provider_id || item.provider_id === filters.provider_id);

  return (
    <div className="stack">
      {error && <div className="notice bad">{error}</div>}
      <section className="card">
        <div className="section-head"><div><h2>Token / Cost Usage</h2><p>筛选影响趋势和汇总；配额已用/剩余固定按 UTC 自然月。</p></div><div className="actions">{[1, 7, 30].map((value) => <button className={days === value ? "primary" : ""} key={value} onClick={() => setDays(value)}>{value === 1 ? "24h" : `${value}d`}</button>)}</div></div>
        <div className="filter-grid">
          <label>租户<select value={filters.tenant_id} onChange={(e) => setFilters({ ...filters, tenant_id: e.target.value, application_id: "" })}><option value="">全部租户</option>{usage.filter_options.tenants.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
          <label>应用<select value={filters.application_id} onChange={(e) => setFilters({ ...filters, application_id: e.target.value })}><option value="">全部应用</option>{apps.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
          <label>Provider<select value={filters.provider_id} onChange={(e) => setFilters({ ...filters, provider_id: e.target.value, remote_model: "" })}><option value="">全部 Provider</option>{usage.filter_options.providers.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
          <label>模型<select value={filters.remote_model} onChange={(e) => setFilters({ ...filters, remote_model: e.target.value })}><option value="">全部模型</option>{models.map((x) => <option key={x.id + x.provider_id} value={x.id}>{x.id}</option>)}</select></label>
        </div>
        <div className="form-actions"><button onClick={() => setFilters(emptyFilters)}>清空筛选</button></div>
      </section>

      <section className="stat-grid six">
        <article className="card stat"><b>{formatCount(usage.total_tokens)}</b><span>总 Token</span></article>
        <article className="card stat"><b>{formatCount(usage.prompt_tokens)}</b><span>输入 Token</span></article>
        <article className="card stat"><b>{formatCount(usage.completion_tokens)}</b><span>输出 Token</span></article>
        <article className="card stat"><b>{formatCount(usage.calls)}</b><span>调用次数</span></article>
        <article className="card stat"><b>{formatCosts(usage.estimated_costs)}</b><span>预计费用</span></article>
        <article className="card stat"><b>{usage.priced_calls} / {usage.calls}</b><span>已计价 / 总调用</span></article>
      </section>

      <section className="card">
        <div className="section-head"><div><h2>月度配额</h2><p>请求前同时检查 Tenant 与 Application；默认 80% 预警，超限 429。</p></div></div>
        <form className="filter-grid quota-editor" onSubmit={saveQuota}>
          <label>层级<select value={quotaDraft.scope_type} onChange={(e) => setQuotaDraft({ ...quotaDraft, scope_type: e.target.value as "tenant" | "application", scope_id: "" })}><option value="tenant">租户</option><option value="application">应用</option></select></label>
          <label>目标<select value={quotaDraft.scope_id} onChange={(e) => setQuotaDraft({ ...quotaDraft, scope_id: e.target.value })}>{targets.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
          <label>月 Token 配额<input type="number" min="0" value={quotaDraft.token_limit} onChange={(e) => setQuotaDraft({ ...quotaDraft, token_limit: e.target.value })} /></label>
          <label>月费用预算<input type="number" min="0" step="0.000001" value={quotaDraft.cost_limit} onChange={(e) => setQuotaDraft({ ...quotaDraft, cost_limit: e.target.value })} /></label>
          <label>币种<input maxLength={8} value={quotaDraft.currency} onChange={(e) => setQuotaDraft({ ...quotaDraft, currency: e.target.value })} /></label>
          <label>预警阈值 %<input type="number" min="0" max="100" step="0.1" value={quotaDraft.warning_threshold_percent} onChange={(e) => setQuotaDraft({ ...quotaDraft, warning_threshold_percent: e.target.value })} /></label>
          <div className="form-actions"><button className="primary" type="submit">保存配额</button></div>
        </form>
      </section>

      <section className="grid-two">
        <UsageTable title="按租户" rows={usage.by_tenant} kind="tenant" />
        <UsageTable title="按应用" rows={usage.by_application} kind="application" />
      </section>
      <section className="grid-two">
        <UsageTable title="按 Provider" rows={usage.by_provider} kind="provider" />
        <UsageTable title="按模型" rows={usage.by_model} kind="model" />
      </section>
      <UsageTable title="按天" rows={usage.by_day} kind="day" />
    </div>
  );
}

function UsageTable({ title, rows, kind }: { title: string; rows: UsageGroup[]; kind: "tenant" | "application" | "provider" | "model" | "day" }) {
  return (
    <section className="card">
      <div className="section-head"><div><h2>{title}</h2></div></div>
      <div className="table-wrap"><table><thead><tr><th>维度</th><th>Token</th><th>预计费用</th>{(kind === "tenant" || kind === "application") && <><th>Token 配额</th><th>费用配额</th><th>状态</th></>}</tr></thead>
        <tbody>{rows.map((row, index) => {
          const label = row.tenant_name || row.application_name || row.provider_name || row.remote_model || row.day || "unknown";
          const sub = row.tenant_id || row.application_id || row.provider_id || "";
          return <tr key={`${label}-${sub}-${index}`}><td><b>{label}</b>{sub && sub !== label && <small>{sub}</small>}</td><td>{formatCount(row.total_tokens)}</td><td>{formatCosts(row.estimated_costs)}</td>{(kind === "tenant" || kind === "application") && <><td>{quotaTokens(row.quota)}</td><td>{quotaCost(row.quota)}</td><td><QuotaBadge row={row} /></td></>}</tr>;
        })}{!rows.length && <tr><td className="empty" colSpan={6}>当前筛选范围没有数据。</td></tr>}</tbody>
      </table></div>
    </section>
  );
}
