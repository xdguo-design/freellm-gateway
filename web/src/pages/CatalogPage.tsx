import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { CATALOG_DRAFT_KEY, catalogRouteDraft } from "../features/models/connection";
import { useI18n } from "../i18n";
import type { CatalogOffer } from "../types";

export function CatalogPage() {
  const { t, status, errorText } = useI18n();
  const [offers, setOffers] = useState<CatalogOffer[]>([]);
  const [search, setSearch] = useState("");
  const [message, setMessage] = useState("");

  async function load() {
    try {
      const result = await api<{ data: CatalogOffer[] }>("/api/admin/catalog/source?scope=models");
      setOffers(result.data ?? []);
    } catch (error) {
      setMessage(errorText(error));
    }
  }

  useEffect(() => { void load(); }, []);

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return offers;
    return offers.filter((offer) => JSON.stringify(offer).toLowerCase().includes(needle));
  }, [offers, search]);

  async function action(kind: "export" | "sync") {
    try {
      const result = await api<{ path?: string; data?: unknown }>(`/api/admin/catalog/${kind}`, { method: "POST" });
      setMessage(kind === "export" ? t("catalog.exported", { path: result.path ?? "catalog" }) : t("catalog.synced"));
    } catch (error) {
      setMessage(errorText(error));
    }
  }

  function addToPool(offer: CatalogOffer) {
    const draft = catalogRouteDraft(offer);
    sessionStorage.setItem(CATALOG_DRAFT_KEY, JSON.stringify(draft));
    window.location.hash = "/models";
  }

  return (
    <div className="stack">
      {message && <div className="notice">{message}</div>}
      <section className="card">
        <div className="section-head">
          <div><h2>{t("catalog.title")}</h2><p>{t("catalog.desc")}</p></div>
          <div className="actions">
            <button onClick={() => void load()}>{t("common.reload")}</button>
            <button onClick={() => void action("export")}>{t("catalog.export")}</button>
            <button className="primary" onClick={() => void action("sync")}>{t("catalog.sync")}</button>
          </div>
        </div>
        <input className="search" placeholder={t("catalog.search")} value={search} onChange={(event) => setSearch(event.target.value)} />
        <div className="catalog-grid">
          {filtered.map((offer, index) => (
            <article className="catalog-card" key={String(offer.id ?? index)}>
              <div className="section-head">
                <div><h3>{String(offer.name ?? offer.model ?? offer.id ?? "Model")}</h3><p>{String(offer.provider ?? "")}</p></div>
                <span className="badge muted-badge">{status(String(offer.pool_status ?? "catalog"))}</span>
              </div>
              <p>{String(offer.freeSummary ?? "")}</p>
              <div>{offer.capabilities?.map((cap) => <span className="tag" key={cap}>{cap}</span>)}</div>
              <div className="catalog-meta">
                <span>{t("common.model")} <code>{String(offer.model ?? "—")}</code></span>
                <span>{t("common.endpoint")} <code>{String(offer.apiEndpoint ?? t("catalog.manualEndpoint"))}</code></span>
              </div>
              <div className="actions">
                <button className="primary" onClick={() => addToPool(offer)}>{t("catalog.addPool")}</button>
                {offer.register && <a className="button-link" href={offer.register} target="_blank" rel="noreferrer">{t("common.register")} ↗</a>}
                {offer.docsUrl && <a href={offer.docsUrl} target="_blank" rel="noreferrer">{t("common.docs")} ↗</a>}
              </div>
            </article>
          ))}
        </div>
        {!filtered.length && <p className="empty">{t("catalog.empty")}</p>}
      </section>
    </div>
  );
}
