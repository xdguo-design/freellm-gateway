import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { CatalogOffer } from "../types";

export function CatalogPage() {
  const [offers, setOffers] = useState<CatalogOffer[]>([]);
  const [search, setSearch] = useState("");
  const [message, setMessage] = useState("");

  async function load() {
    const result = await api<{ data: CatalogOffer[] }>("/api/admin/catalog/source?scope=models");
    setOffers(result.data ?? []);
  }
  useEffect(() => { void load().catch((error: Error) => setMessage(error.message)); }, []);

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return offers;
    return offers.filter((offer) => JSON.stringify(offer).toLowerCase().includes(needle));
  }, [offers, search]);

  async function action(kind: "export" | "sync") {
    const result = await api<{ path?: string; data?: unknown }>(`/api/admin/catalog/${kind}`, { method: "POST" });
    setMessage(kind === "export" ? `已导出：${result.path ?? "catalog"}` : "已同步目录");
  }

  return <div className="stack">
    {message && <div className="notice">{message}</div>}
    <section className="card">
      <div className="section-head"><div><h2>FreeLLM 模型目录</h2><p>从公开目录发现模型，发布仍由本地 Gateway 控制。</p></div><div className="actions"><button onClick={() => void load()}>重新加载</button><button onClick={() => void action("export")}>导出</button><button className="primary" onClick={() => void action("sync")}>同步到站点</button></div></div>
      <input className="search" placeholder="搜索 provider / model / capability" value={search} onChange={(e) => setSearch(e.target.value)} />
      <div className="catalog-grid">{filtered.map((offer, index) => <article className="catalog-card" key={String(offer.id ?? index)}>
        <div className="section-head"><div><h3>{String(offer.name ?? offer.model ?? offer.id ?? "Model")}</h3><p>{String(offer.provider ?? "")}</p></div><span className="badge muted-badge">{String(offer.pool_status ?? "catalog")}</span></div>
        <p>{String(offer.free_summary ?? "")}</p>
        <div>{Array.isArray(offer.capabilities) && offer.capabilities.map((cap) => <span className="tag" key={cap}>{cap}</span>)}</div>
        <div className="actions">{typeof offer.public_url === "string" && <a className="button-link" href={offer.public_url} target="_blank" rel="noreferrer">注册 ↗</a>}{typeof offer.docs_url === "string" && <a href={offer.docs_url} target="_blank" rel="noreferrer">文档 ↗</a>}</div>
      </article>)}</div>
      {!filtered.length && <p className="empty">没有匹配目录条目。</p>}
    </section>
  </div>;
}
