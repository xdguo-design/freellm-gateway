export type HealthStatus =
  | "healthy"
  | "slow"
  | "failed"
  | "rate_limited"
  | "quota_exhausted"
  | "cooldown"
  | "disabled"
  | string;

export interface Pricing {
  currency: string;
  input_per_million: number | null;
  output_per_million: number | null;
}

export interface Route {
  id: string;
  provider_id: string;
  provider_name: string;
  remote_model: string;
  display_name: string | null;
  priority: number;
  capabilities: string[];
  enabled: boolean;
  health: HealthStatus;
  reasoning_effort: string | null;
  pricing: Pricing;
  public_url: string | null;
  public_docs_url: string | null;
  free_summary: string | null;
  catalog_status: string;
}

export interface Provider {
  id: string;
  name: string;
  protocol: "openai" | "anthropic" | "gemini" | string;
  base_url: string;
  official_url: string;
}

export interface Overview {
  configured: number;
  enabled: number;
  healthy: number;
  disabled: number;
  capabilities: string[];
  api_base: string;
  admin_base: string;
  docs_url: string;
  api_token: string;
  chat_url: string;
  models_url: string;
  images_url: string;
  health_url: string;
  database_path: string | null;
  catalog_output_path: string;
  logs_path: string;
  connection_log_path: string;
  providers: number;
}

export interface ConnectionRecord {
  request_id?: string;
  requested_model?: string;
  provider_id?: string;
  remote_model?: string;
  tenant_id?: string;
  application_id?: string;
  status?: string;
  elapsed_ms?: number;
  stream?: boolean;
  error_kind?: string;
  usage?: {
    prompt_tokens?: number;
    completion_tokens?: number;
    total_tokens?: number;
  };
  timestamp?: string;
}

export interface Tenant {
  id: string;
  name: string;
  enabled: boolean;
  created_at: string | null;
}

export interface Application {
  id: string;
  tenant_id: string;
  name: string;
  key_prefix: string;
  enabled: boolean;
  created_at: string | null;
}

export interface QuotaPolicy {
  scope_type: "tenant" | "application";
  scope_id: string;
  token_limit: number | null;
  cost_limit_micros: number | null;
  cost_limit: number | null;
  currency: string;
  warning_threshold_percent: number;
  updated_at: string | null;
}

export interface CostSummary {
  currency: string;
  micros: number;
  amount: number;
}

export interface QuotaStatus {
  configured: boolean;
  scope_type: string;
  scope_id: string;
  currency: string;
  warning_threshold_percent: number;
  token_limit: number | null;
  used_tokens: number;
  remaining_tokens: number | null;
  token_utilization_percent: number | null;
  cost_limit_micros: number | null;
  cost_limit: number | null;
  used_cost_micros: number;
  used_cost: number;
  remaining_cost_micros: number | null;
  remaining_cost: number | null;
  cost_utilization_percent: number | null;
  unpriced_calls: number;
  other_currency_calls: number;
  cost_complete: boolean;
  token_warning: boolean;
  cost_warning: boolean;
  token_exceeded: boolean;
  cost_exceeded: boolean;
}

export interface UsageGroup {
  tenant_id?: string;
  tenant_name?: string;
  application_id?: string;
  application_name?: string;
  provider_id?: string;
  provider_name?: string;
  remote_model?: string;
  day?: string;
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  avg_latency_ms?: number;
  estimated_costs: CostSummary[];
  priced_calls: number;
  unpriced_calls: number;
  quota?: QuotaStatus | null;
}

export interface UsageSummary {
  days: number;
  filters: Record<string, string>;
  filter_options: {
    tenants: Array<{ id: string; name: string }>;
    applications: Array<{ id: string; tenant_id: string; name: string }>;
    providers: Array<{ id: string; name: string }>;
    models: Array<{ id: string; provider_id: string }>;
  };
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  avg_latency_ms: number;
  priced_calls: number;
  unpriced_calls: number;
  estimated_costs: CostSummary[];
  quota_period: { type: string; start: string; end: string } | null;
  selected_quota: QuotaStatus | null;
  by_tenant: UsageGroup[];
  by_application: UsageGroup[];
  by_provider: UsageGroup[];
  by_model: UsageGroup[];
  by_day: UsageGroup[];
}

export interface CatalogOffer {
  id?: string;
  order?: number;
  date?: string;
  name?: string;
  providerMark?: string;
  provider?: string;
  model?: string;
  modelMeta?: string;
  productType?: string;
  capabilities?: string[];
  usageGuide?: unknown;
  register?: string;
  registerLabel?: string;
  docsUrl?: string;
  apiEndpoint?: string;
  freeSummary?: string;
  validitySummary?: string;
  accessSummary?: string;
  badges?: string[];
  pool_status?: string;
  [key: string]: unknown;
}
