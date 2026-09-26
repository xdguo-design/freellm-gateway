import type { CostSummary, QuotaStatus } from "../types";

export function formatCount(value: number | null | undefined, locale?: string): string {
  return Number(value ?? 0).toLocaleString(locale);
}

export function formatCosts(costs: CostSummary[] | null | undefined, locale?: string): string {
  if (!costs?.length) return "—";
  return costs
    .map((item) => `${item.currency} ${Number(item.amount ?? 0).toLocaleString(locale, {
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
