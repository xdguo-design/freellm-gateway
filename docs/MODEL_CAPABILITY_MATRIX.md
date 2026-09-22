# Model Capability Matrix

`ModelRoute` remains the persisted source of truth. `ModelRegistry` is the
runtime index used by current and future routing strategies.

## Persisted metadata

Routes now store declared capabilities, context window, maximum output tokens,
input/output price per 1M tokens, and pricing currency. Existing SQLite
databases are migrated in place by `Database.initialize()`.

Unknown vendor values stay null. The gateway does not guess model limits or
pricing.

## Normalized capabilities

The registry preserves declared values and exposes a stable matrix. Aliases
currently include `tools -> function_calling`, `stream -> streaming`, and
`json -> json_mode`.

## APIs

Normal API bearer token:

- `GET /v1/models`
- `GET /v1/models/{model_id}`
- `GET /v1/models/{model_id}/capabilities`

Admin bearer token:

- `GET /api/admin/models/capability-matrix`

## Route metadata example

```json
{
  "capabilities": ["chat", "vision", "tools", "stream"],
  "context_window": 128000,
  "max_output_tokens": 8192,
  "input_price_per_million": 1.25,
  "output_price_per_million": 5.0,
  "pricing_currency": "USD"
}
```

## Local verification

```bash
python -m pip install -e ".[test]"
python -m compileall -q freellm_gateway tests
python -m pytest -q
```

The next router phase can consume `ModelRegistry.find()` plus persisted prices
without another storage migration.
