# Token usage dashboard

The admin console includes a Token Usage view backed by persisted SQLite usage
records. The counters are not browser-only analytics.

## Identity and attribution

Usage is attributed by the authentication credential accepted by the gateway.

Legacy global API tokens remain supported and are recorded as:

- tenant: `system`
- application: `legacy-global`

For tenant-aware attribution, create a tenant and an application:

```http
POST /api/admin/tenants
{"id":"team-a","name":"Team A"}

POST /api/admin/applications
{"id":"search-app","tenant_id":"team-a","name":"Search App"}
```

Creating an application returns an `api_key` once. Use it as:

```http
Authorization: Bearer flm-app.search-app.<secret>
```

The application secret is not stored in plaintext. The repository stores a
random salt and an scrypt-derived hash, and verification uses a constant-time
comparison.

Tenant and application IDs are derived from successful authentication. Clients
cannot override usage attribution with request headers or request-body fields.

## Data path

Successful and partially completed provider calls emit normalized connection
records from `ModelGateway`. When a provider reports a usage object, the
application persists:

- request id
- tenant id
- application id
- provider id
- remote model
- prompt/input tokens
- completion/output tokens
- total tokens
- elapsed milliseconds
- stream flag
- request status
- UTC timestamp

Prompt text, credentials, and response bodies are not stored.

## Admin API

```http
GET /api/admin/usage?days=7
```

The `days` window is clamped to 1..365 days.

Optional filters can be combined:

```http
GET /api/admin/usage?days=30&tenant_id=team-a
GET /api/admin/usage?days=30&tenant_id=team-a&application_id=search-app
GET /api/admin/usage?days=7&provider_id=google&remote_model=gemini-2.5-pro
```

Supported filters:

- `tenant_id`
- `application_id`
- `provider_id`
- `remote_model`

The response includes active filters, available filter options, totals, average
latency, and these breakdowns:

- `by_tenant`
- `by_application`
- `by_provider`
- `by_model`
- `by_day`

## Console

Open `/admin` and select **Token Usage** / **Token 用量**.

Available time windows:

- 24 hours
- 7 days
- 30 days

Filters:

- tenant
- application
- provider
- model

Changing a tenant narrows the application choices. Changing a provider narrows
the model choices. Filters are applied on the server, so cards and every
breakdown represent the same selected slice.

## Provider behavior

Usage is recorded only when the upstream provider reports token usage. This is
intentional: the gateway does not estimate unknown usage and present it as
provider-reported data.

Both non-streaming responses and streaming SSE chunks are supported when their
normalized OpenAI-compatible payload contains a `usage` object.

## Database migration

Existing `usage_records` tables are upgraded in place. Historical records are
assigned to `system / legacy-global`, preserving old totals while making the
new dimensions non-null.

## Estimated cost

Each model route can define operator-supplied pricing:

- `input_price_per_million`
- `output_price_per_million`
- `pricing_currency`

Prices are expressed as currency units per 1,000,000 tokens.

When a request finishes, the gateway snapshots the estimated cost into the
usage record. Historical usage is therefore not recalculated when a route's
price changes later.

The persisted amount uses integer micro-units:

```text
estimated_cost_micros =
  prompt_tokens * input_price_per_million
  + completion_tokens * output_price_per_million
```

For example, USD 2 / 1M input tokens and USD 4 / 1M output tokens with 12 input
and 5 output tokens produces 44 micro-USD, or USD 0.000044.

If a request used non-zero input/output tokens but the matching route price is
missing, the cost is stored as unknown rather than zero. Usage summaries expose
`priced_calls` and `unpriced_calls`.

Multiple currencies are never added together. Summary responses return
`estimated_costs` as a list by currency.

## Monthly quotas

Quota policies can be configured at tenant or application scope:

```http
PUT /api/admin/quotas/tenant/team-a
{
  "token_limit": 10000000,
  "cost_limit": 100,
  "currency": "USD"
}

PUT /api/admin/quotas/application/search-app
{
  "token_limit": 2000000,
  "cost_limit": 25,
  "currency": "USD"
}
```

Use `GET /api/admin/quotas` to list configured policies.

Quota periods are UTC calendar months. The dashboard's 24h / 7d / 30d selector
changes the visible usage and cost trend, but monthly quota used/remaining
always reflects the full current calendar month.

For each configured tenant/application the usage response includes:

- token limit
- used tokens
- remaining tokens
- token utilization percent
- cost limit
- estimated cost used
- estimated cost remaining
- cost utilization percent
- unpriced calls
- calls priced in another currency
- `cost_complete`

If any monthly calls are unpriced or priced in a currency different from the
quota currency, `cost_complete` is false. The gateway does not silently treat
those calls as zero-cost.

Configured quota scopes with zero usage still appear in the tenant/application
summary with zero used and the full quota remaining.

This stage reports quota consumption and remaining capacity. Request-time quota
enforcement can build on the same persisted policy and usage data.

