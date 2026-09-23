import type { CostSummary, QuotaStatus } from "../types";

export function formatCount(value: number | null | undefined): string {
  return Number(value ?? 0).toLocaleString();
}

export function formatCosts(costs: CostSummary[] | null | undefined): string {
  if (!costs?.length) return "—";
  return costs
    .map((item) => `${item.currency} ${Number(item.amount ?? 0).toLocaleString(undefined, {
      maximumFractionDigits: 6,
    })}`)
    .join(" · ");
}

export function quotaTone(quota: QuotaStatus | null | undefined): "bad" | "warn" | "ok" | "none" {
  if (!quota) return "none";
  if (quota.token_exceeded || quota.cost_exceeded) return "bad";
  if (quota.token_warning || quota.cost_warning) return "warn";
  return "ok";
}

export function quotaTokens(quota: QuotaStatus | null | undefined): string {
  if (!quota) return "未配置";
  const remaining = quota.remaining_tokens == null ? "不限" : formatCount(quota.remaining_tokens);
  return `${formatCount(quota.used_tokens)} / ${remaining}`;
}

export function quotaCost(quota: QuotaStatus | null | undefined): string {
  if (!quota) return "未配置";
  const remaining =
    quota.remaining_cost == null ? "不限" : `${quota.currency} ${quota.remaining_cost.toLocaleString(undefined, { maximumFractionDigits: 6 })}`;
  const suffix = quota.cost_complete ? "" : " · 费用不完整";
  return `${quota.currency} ${quota.used_cost.toLocaleString(undefined, { maximumFractionDigits: 6 })} / ${remaining}${suffix}`;
}
