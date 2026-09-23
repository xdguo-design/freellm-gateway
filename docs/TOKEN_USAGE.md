# Token usage dashboard

The admin console includes a Token Usage view backed by persisted SQLite usage
records. The counters are not browser-only analytics.

## Data path

Successful and partially completed provider calls already emit normalized
connection records from `ModelGateway`. When a provider reports a usage
object, the application now persists:

- request id
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

Response fields include totals, average latency, per-model aggregation, and
per-day aggregation.

## Console

Open `/admin` and select **Token Usage** / **Token 用量**.

Available windows:

- 24 hours
- 7 days
- 30 days

The page shows total/input/output tokens, call count, model/provider ranking,
and daily totals.

## Provider behavior

Usage is recorded only when the upstream provider reports token usage. This is
intentional: the gateway does not estimate unknown usage and present it as
provider-reported data.

Both non-streaming responses and streaming SSE chunks are supported when their
normalized OpenAI-compatible payload contains a `usage` object.
