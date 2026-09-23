import type { ReactNode } from "react";

export type ViewKey = "overview" | "models" | "usage" | "routing" | "catalog" | "settings";

const items: Array<[ViewKey, string, string]> = [
  ["overview", "概览", "OVERVIEW"],
  ["models", "模型池", "MODELS"],
  ["usage", "Token 用量", "USAGE"],
  ["routing", "请求路由", "ROUTING"],
  ["catalog", "目录同步", "CATALOG"],
  ["settings", "设置", "SETTINGS"],
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
  const title = items.find(([key]) => key === view)?.[1] ?? "FreeLLM";
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">Free<span>LLM</span><small>Gateway Console</small></div>
        <nav>
          {items.map(([key, label, kicker]) => (
            <button key={key} className={view === key ? "active" : ""} onClick={() => onView(key)}>
              <small>{kicker}</small><span>{label}</span>
            </button>
          ))}
        </nav>
        <a className="legacy-link" href="/admin/legacy">Legacy Console ↗</a>
      </aside>
      <main>
        <header className="topbar">
          <div><p className="eyebrow">GATEWAY / {view.toUpperCase()}</p><h1>{title}</h1></div>
          <div className="top-actions">
            <label className="token-field">
              <span>Admin Token</span>
              <input
                type="password"
                value={token}
                placeholder="loopback 可留空"
                onChange={(event) => onToken(event.target.value)}
              />
            </label>
            <span className={online ? "service ok" : "service bad"}>{online ? "Service Online" : "API Error"}</span>
            <button onClick={onRefresh}>刷新</button>
          </div>
        </header>
        {children}
      </main>
    </div>
  );
}
