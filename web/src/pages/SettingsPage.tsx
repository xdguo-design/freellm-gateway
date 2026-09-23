import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Application, Overview, Tenant } from "../types";

export function SettingsPage({
  overview,
  tenants,
  applications,
  onRefresh,
}: {
  overview: Overview | null;
  tenants: Tenant[];
  applications: Application[];
  onRefresh: () => Promise<void>;
}) {
  const [tenantDraft, setTenantDraft] = useState({ id: "", name: "" });
  const [appDraft, setAppDraft] = useState({ id: "", tenant_id: tenants[0]?.id ?? "", name: "" });
  const [issuedKey, setIssuedKey] = useState("");

  async function createTenant(event: FormEvent) {
    event.preventDefault();
    await api("/api/admin/tenants", { method: "POST", body: tenantDraft });
    setTenantDraft({ id: "", name: "" });
    await onRefresh();
  }

  async function createApplication(event: FormEvent) {
    event.preventDefault();
    const result = await api<{ api_key: string }>("/api/admin/applications", { method: "POST", body: appDraft });
    setIssuedKey(result.api_key);
    setAppDraft({ id: "", tenant_id: appDraft.tenant_id, name: "" });
    await onRefresh();
  }

  return <div className="stack">
    {issuedKey && <div className="notice warn"><b>Application Key 只显示一次：</b><code>{issuedKey}</code></div>}
    <section className="grid-two">
      <form className="card form-card" onSubmit={createTenant}>
        <div className="section-head"><div><h2>租户</h2><p>Token / Cost 配额的顶层归属。</p></div></div>
        <div className="form-grid one"><label>Tenant ID<input required value={tenantDraft.id} onChange={(e) => setTenantDraft({ ...tenantDraft, id: e.target.value })} /></label><label>名称<input required value={tenantDraft.name} onChange={(e) => setTenantDraft({ ...tenantDraft, name: e.target.value })} /></label></div>
        <div className="form-actions"><button className="primary" type="submit">创建租户</button></div>
        <div className="compact-list">{tenants.map((item) => <div key={item.id}><b>{item.name}</b><code>{item.id}</code></div>)}</div>
      </form>
      <form className="card form-card" onSubmit={createApplication}>
        <div className="section-head"><div><h2>应用</h2><p>应用 Key 认证后自动归属 Tenant / Application Usage。</p></div></div>
        <div className="form-grid one"><label>Application ID<input required value={appDraft.id} onChange={(e) => setAppDraft({ ...appDraft, id: e.target.value })} /></label><label>租户<select required value={appDraft.tenant_id} onChange={(e) => setAppDraft({ ...appDraft, tenant_id: e.target.value })}><option value="">请选择</option>{tenants.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label><label>名称<input required value={appDraft.name} onChange={(e) => setAppDraft({ ...appDraft, name: e.target.value })} /></label></div>
        <div className="form-actions"><button className="primary" type="submit">创建应用</button></div>
        <div className="compact-list">{applications.map((item) => <div key={item.id}><b>{item.name}</b><code>{item.key_prefix}…</code></div>)}</div>
      </form>
    </section>
    <section className="card">
      <div className="section-head"><div><h2>Runtime</h2><p>Gateway 本地运行路径与接口。</p></div></div>
      <div className="kv-list">
        <div><span>Database</span><code>{overview?.database_path ?? "—"}</code></div>
        <div><span>Connection Log</span><code>{overview?.connection_log_path ?? "—"}</code></div>
        <div><span>Catalog Output</span><code>{overview?.catalog_output_path ?? "—"}</code></div>
        <div><span>Docs</span><code>{overview?.docs_url ?? "/docs"}</code></div>
      </div>
    </section>
  </div>;
}
