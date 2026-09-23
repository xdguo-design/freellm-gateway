import type { ReactNode } from "react";
import { useI18n } from "../i18n";

export type ViewKey = "overview" | "models" | "usage" | "routing" | "catalog" | "settings";

const items: Array<[ViewKey, string, string]> = [
  ["overview", "nav.overview", "OVERVIEW"],
  ["models", "nav.models", "MODELS"],
  ["usage", "nav.usage", "USAGE"],
  ["routing", "nav.routing", "ROUTING"],
  ["catalog", "nav.catalog", "CATALOG"],
  ["settings", "nav.settings", "SETTINGS"],
];

export function Shell({
  view,
  onView,
  children,
  online,
  onRefresh,
  token,
  onToken,
}: {
  view: ViewKey;
  onView: (view: ViewKey) => void;
  children: ReactNode;
  online: boolean;
  onRefresh: () => void;
  token: string;
  onToken: (token: string) => void;
}) {
  const { language, setLanguage, t } = useI18n();
  const titleKey = items.find(([key]) => key === view)?.[1] ?? "nav.overview";
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">Free<span>LLM</span><small>{t("shell.console")}</small></div>
        <nav>
          {items.map(([key, labelKey, kicker]) => (
            <button key={key} className={view === key ? "active" : ""} onClick={() => onView(key)}>
              <small>{kicker}</small><span>{t(labelKey)}</span>
            </button>
          ))}
        </nav>
        <a className="legacy-link" href="/admin/legacy">{t("shell.legacy")} ↗</a>
      </aside>
      <main>
        <header className="topbar">
          <div><p className="eyebrow">GATEWAY / {view.toUpperCase()}</p><h1>{t(titleKey)}</h1></div>
          <div className="top-actions">
            <div className="language-switch" role="group" aria-label="Language">
              <button className={language === "zh" ? "active" : ""} onClick={() => setLanguage("zh")}>{t("lang.zh")}</button>
              <button className={language === "en" ? "active" : ""} onClick={() => setLanguage("en")}>{t("lang.en")}</button>
            </div>
            <label className="token-field">
              <span>{t("shell.adminToken")}</span>
              <input
                type="password"
                value={token}
                placeholder={t("shell.tokenPlaceholder")}
                onChange={(event) => onToken(event.target.value)}
              />
            </label>
            <span className={online ? "service ok" : "service bad"}>{online ? t("shell.online") : t("shell.apiError")}</span>
            <button onClick={onRefresh}>{t("common.refresh")}</button>
          </div>
        </header>
        {children}
      </main>
    </div>
  );
}
