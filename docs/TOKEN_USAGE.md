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
