import { useCallback, useEffect, useState } from "react";
import { api, getAdminToken, setAdminToken } from "./api/client";
import { Shell, type ViewKey } from "./components/Shell";
import { useI18n } from "./i18n";
import { CatalogPage } from "./pages/CatalogPage";
import { ModelsPage } from "./pages/ModelsPage";
import { OverviewPage } from "./pages/OverviewPage";
import { RoutingPage } from "./pages/RoutingPage";
import { SettingsPage } from "./pages/SettingsPage";
import { UsagePage } from "./pages/UsagePage";
import type { Application, ConnectionRecord, Overview, Provider, Route, Tenant } from "./types";

function initialView(): ViewKey {
  const value = window.location.hash.replace("#/", "") as ViewKey;
  return ["overview", "models", "usage", "routing", "catalog", "settings"].includes(value) ? value : "overview";
}

export default function App() {
  const { t, errorText } = useI18n();
  const [view, setView] = useState<ViewKey>(initialView);
  const [token, setTokenState] = useState(getAdminToken);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [routes, setRoutes] = useState<Route[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [connections, setConnections] = useState<ConnectionRecord[]>([]);
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [applications, setApplications] = useState<Application[]>([]);
  const [online, setOnline] = useState(true);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [overviewResult, routesResult, providersResult, connectionsResult, tenantsResult, applicationsResult] = await Promise.all([
        api<{ data: Overview }>("/api/admin/overview"),
        api<{ data: Route[] }>("/api/admin/routes"),
        api<{ data: Provider[] }>("/api/admin/providers"),
        api<{ data: ConnectionRecord[] }>("/api/admin/connections?limit=100"),
        api<{ data: Tenant[] }>("/api/admin/tenants"),
        api<{ data: Application[] }>("/api/admin/applications"),
      ]);
      setOverview(overviewResult.data);
      setRoutes(routesResult.data);
      setProviders(providersResult.data);
      setConnections(connectionsResult.data);
      setTenants(tenantsResult.data);
      setApplications(applicationsResult.data);
      setOnline(true);
      setError("");
    } catch (reason) {
      setOnline(false);
      setError(errorText(reason));
    }
  }, [errorText]);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    const handler = () => setView(initialView());
    window.addEventListener("hashchange", handler);
    return () => window.removeEventListener("hashchange", handler);
  }, []);

  function changeView(next: ViewKey) {
    window.location.hash = `/${next}`;
    setView(next);
  }

  function changeToken(value: string) {
    setTokenState(value);
    setAdminToken(value);
  }

  let page;
  if (view === "models") page = <ModelsPage routes={routes} providers={providers} connections={connections} onRefresh={refresh} />;
  else if (view === "usage") page = <UsagePage />;
  else if (view === "routing") page = <RoutingPage routes={routes} />;
  else if (view === "catalog") page = <CatalogPage />;
  else if (view === "settings") page = <SettingsPage overview={overview} tenants={tenants} applications={applications} onRefresh={refresh} />;
  else page = <OverviewPage overview={overview} routes={routes} providers={providers} connections={connections} />;

  return (
    <Shell view={view} onView={changeView} online={online} onRefresh={() => void refresh()} token={token} onToken={changeToken}>
      {error && <div className="notice bad">{error}<small>{t("app.remoteHint")}</small></div>}
      {page}
    </Shell>
  );
}
