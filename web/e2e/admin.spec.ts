import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("freellm_gateway_language", "zh");
  });
});

test("React admin boots, navigates, switches language, and has no runtime errors", async ({ page }) => {
  const runtimeErrors: string[] = [];
  page.on("pageerror", (error) => runtimeErrors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") runtimeErrors.push(`console: ${message.text()}`);
  });

  await page.goto("/admin/");
  await expect(page.getByRole("heading", { level: 1, name: "概览" })).toBeVisible();
  await expect(page).toHaveTitle("概览 · FreeLLM Gateway");

  await page.getByRole("button", { name: "EN", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Overview" })).toBeVisible();
  await expect(page).toHaveTitle("Overview · FreeLLM Gateway");

  await page.getByRole("button", { name: "Model Pool" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Model Pool" })).toBeVisible();
  await expect(page).toHaveTitle("Model Pool · FreeLLM Gateway");

  await page.getByRole("button", { name: "Token Usage" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Token Usage" })).toBeVisible();
  await expect(page.getByText("Monthly Quotas")).toBeVisible();

  await page.getByRole("button", { name: "Routing" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Routing" })).toBeVisible();

  await page.getByRole("button", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();

  expect(runtimeErrors).toEqual([]);
});

test("quota form performs a real UI-to-API round trip", async ({ page, request }) => {
  const tenant = await request.post("/api/admin/tenants", {
    data: { id: "e2e-tenant", name: "E2E Tenant" },
  });
  expect(tenant.status()).toBe(201);

  const application = await request.post("/api/admin/applications", {
    data: { id: "e2e-app", tenant_id: "e2e-tenant", name: "E2E App" },
  });
  expect(application.status()).toBe(201);

  await page.goto("/admin/#/usage");
  await page.getByRole("button", { name: "EN", exact: true }).click();
  await expect(page.getByText("Monthly Quotas")).toBeVisible();

  await page.getByLabel("Scope").selectOption("application");
  await page.getByLabel("Target").selectOption("e2e-app");
  await page.getByLabel("Monthly Token Quota").fill("1000");
  await page.getByLabel("Monthly Cost Budget").fill("10");
  await page.getByLabel("Currency").fill("USD");
  await page.getByLabel("Warning Threshold %").fill("75");
  await page.getByRole("button", { name: "Save Quota" }).click();

  await expect.poll(async () => {
    const response = await request.get("/api/admin/quotas");
    const payload = await response.json();
    const policy = payload.data.find(
      (item: { scope_type: string; scope_id: string }) =>
        item.scope_type === "application" && item.scope_id === "e2e-app",
    );
    return policy
      ? {
          token_limit: policy.token_limit,
          cost_limit: policy.cost_limit,
          warning_threshold_percent: policy.warning_threshold_percent,
        }
      : null;
  }).toEqual({
    token_limit: 1000,
    cost_limit: 10,
    warning_threshold_percent: 75,
  });
});
