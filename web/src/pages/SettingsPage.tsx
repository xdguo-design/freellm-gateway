import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Application, Overview, Tenant } from "../types";

async function copyText(value: string): Promise<void> {
  if (!value) return;
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }
  const input = document.createElement("textarea");
  input.value = value;
  input.style.position = "fixed";
  input.style.opacity = "0";
  document.body.appendChild(input);
  input.select();
  document.execCommand("copy");
  input.remove();
}

function CopyRow({ label, value }: { label: string; value: string | null | undefined }) {
  const text = value || "—";
  return <div><span>{label}</span><code>{text}</code>{value && <button type="button" onClick={() => void copyText(value)}>复制</button>}</div>;
}

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
  const [copiedKey, setCopiedKey] = useState(false);

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
    setCopiedKey(false);
    setAppDraft({ id: "", tenant_id: appDraft.tenant_id, name: "" });
    await onRefresh();
  }

  async function copyIssuedKey() {
    await copyText(issuedKey);
    setCopiedKey(true);
  }

  return <div className="stack">
    {issuedKey && <div className="notice warn"><b>Application Key 只显示一次：</b><code>{issuedKey}</code><div className="actions"><button type="button" onClick={() => void copyIssuedKey()}>{copiedKey ? "已复制" : "复制 Key"}</button></div></div>}
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
      <div className="section-head"><div><h2>API / Runtime</h2><p>Web 与 Tauri 使用同一 Gateway API。</p></div></div>
      <div className="kv-list copyable">
        <CopyRow label="API Token" value={overview?.api_token} />
        <CopyRow label="Default Model" value="auto" />
        <CopyRow label="Chat" value={overview?.chat_url} />
        <CopyRow label="Images" value={overview?.images_url} />
        <CopyRow label="Models" value={overview?.models_url} />
        <CopyRow label="Health" value={overview?.health_url} />
        <CopyRow label="Database" value={overview?.database_path} />
        <CopyRow label="Connection Log" value={overview?.connection_log_path} />
        <CopyRow label="Catalog Output" value={overview?.catalog_output_path} />
        <CopyRow label="Gateway Log" value={overview?.logs_path} />
        <CopyRow label="Docs" value={overview?.docs_url} />
      </div>
    </section>
  </div>;
}
