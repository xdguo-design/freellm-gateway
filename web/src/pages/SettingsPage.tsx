import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import { useI18n } from "../i18n";
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
  const { t } = useI18n();
  const text = value || "—";
  return <div><span>{label}</span><code>{text}</code>{value && <button type="button" onClick={() => void copyText(value)}>{t("common.copy")}</button>}</div>;
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
  const { t, errorText } = useI18n();
  const [tenantDraft, setTenantDraft] = useState({ id: "", name: "" });
  const [appDraft, setAppDraft] = useState({ id: "", tenant_id: tenants[0]?.id ?? "", name: "" });
  const [issuedKey, setIssuedKey] = useState("");
  const [copiedKey, setCopiedKey] = useState(false);
  const [message, setMessage] = useState("");

  async function createTenant(event: FormEvent) {
    event.preventDefault();
    try {
      await api("/api/admin/tenants", { method: "POST", body: tenantDraft });
      setTenantDraft({ id: "", name: "" });
      setMessage("");
      await onRefresh();
    } catch (error) {
      setMessage(errorText(error));
    }
  }

  async function createApplication(event: FormEvent) {
    event.preventDefault();
    try {
      const result = await api<{ api_key: string }>("/api/admin/applications", { method: "POST", body: appDraft });
      setIssuedKey(result.api_key);
      setCopiedKey(false);
      setAppDraft({ id: "", tenant_id: appDraft.tenant_id, name: "" });
      setMessage("");
      await onRefresh();
    } catch (error) {
      setMessage(errorText(error));
    }
  }

  async function copyIssuedKey() {
    await copyText(issuedKey);
    setCopiedKey(true);
  }

  return <div className="stack">
    {message && <div className="notice bad">{message}</div>}
    {issuedKey && <div className="notice warn"><b>{t("settings.keyOnce")}</b><code>{issuedKey}</code><div className="actions"><button type="button" onClick={() => void copyIssuedKey()}>{copiedKey ? t("common.copied") : t("settings.copyKey")}</button></div></div>}
    <section className="grid-two">
      <form className="card form-card" onSubmit={createTenant}>
        <div className="section-head"><div><h2>{t("common.tenant")}</h2><p>{t("settings.tenantDesc")}</p></div></div>
        <div className="form-grid one"><label>Tenant ID<input required value={tenantDraft.id} onChange={(event) => setTenantDraft({ ...tenantDraft, id: event.target.value })} /></label><label>{t("common.name")}<input required value={tenantDraft.name} onChange={(event) => setTenantDraft({ ...tenantDraft, name: event.target.value })} /></label></div>
        <div className="form-actions"><button className="primary" type="submit">{t("settings.createTenant")}</button></div>
        <div className="compact-list">{tenants.map((item) => <div key={item.id}><b>{item.name}</b><code>{item.id}</code></div>)}</div>
      </form>
      <form className="card form-card" onSubmit={createApplication}>
        <div className="section-head"><div><h2>{t("common.application")}</h2><p>{t("settings.appDesc")}</p></div></div>
        <div className="form-grid one"><label>Application ID<input required value={appDraft.id} onChange={(event) => setAppDraft({ ...appDraft, id: event.target.value })} /></label><label>{t("common.tenant")}<select required value={appDraft.tenant_id} onChange={(event) => setAppDraft({ ...appDraft, tenant_id: event.target.value })}><option value="">{t("common.select")}</option>{tenants.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label><label>{t("common.name")}<input required value={appDraft.name} onChange={(event) => setAppDraft({ ...appDraft, name: event.target.value })} /></label></div>
        <div className="form-actions"><button className="primary" type="submit">{t("settings.createApp")}</button></div>
        <div className="compact-list">{applications.map((item) => <div key={item.id}><b>{item.name}</b><code>{item.key_prefix}…</code></div>)}</div>
      </form>
    </section>

    <section className="card">
      <div className="section-head"><div><h2>{t("settings.runtimeTitle")}</h2><p>{t("settings.runtimeDesc")}</p></div></div>
      <div className="kv-list copyable">
        <CopyRow label="API Token" value={overview?.api_token} />
        <CopyRow label={t("settings.defaultModel")} value="auto" />
        <CopyRow label="Chat" value={overview?.chat_url} />
        <CopyRow label="Images" value={overview?.images_url} />
        <CopyRow label="Models" value={overview?.models_url} />
        <CopyRow label="Health" value={overview?.health_url} />
        <CopyRow label="Database" value={overview?.database_path} />
        <CopyRow label={t("settings.connectionLog")} value={overview?.connection_log_path} />
        <CopyRow label={t("settings.catalogOutput")} value={overview?.catalog_output_path} />
        <CopyRow label={t("settings.gatewayLog")} value={overview?.logs_path} />
        <CopyRow label="Docs" value={overview?.docs_url} />
      </div>
    </section>
  </div>;
}
