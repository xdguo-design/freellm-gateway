# Mock Provider End-to-End Validation

This test harness validates FreeLLM Gateway against a deterministic provider
service over real localhost TCP sockets. It does not use vendor API keys and it
does not replace the provider adapters with `httpx.MockTransport`.

## Simulated providers and models

| Route | Wire protocol | Capabilities exercised |
| --- | --- | --- |
| `openai-fast` | OpenAI compatible | chat, JSON mode, streaming |
| `openai-vision` | OpenAI compatible | vision, function tools, streaming |
| `openai-long` | OpenAI compatible | automatic long-context routing |
| `openai-embedding` | OpenAI compatible | embeddings |
| `openai-image` | OpenAI compatible | image generation |
| `gemini-native` | Gemini native | chat, vision, tools, JSON mode, streaming |
| `mock-fail` | OpenAI compatible | HTTP 503 and gateway failover |

The mock service also exposes provider model-discovery endpoints.

## What the E2E suite verifies

The suite covers the request path:

```text
Gateway API
  -> ModelGateway
  -> ModelRegistry / capability selection
  -> ProviderAdapter
  -> real localhost HTTP
  -> simulated provider
  -> ProviderAdapter normalization
  -> Gateway API response
```

The checks include:

- model listing and model detail APIs
- capability matrix and persisted pricing/limits
- OpenAI-compatible provider discovery
- Gemini-native provider discovery
- standard chat completion
- JSON response-format passthrough
- image/vision request routing
- function-tool request/response mapping
- OpenAI-compatible SSE streaming
- Gemini-native SSE streaming
- automatic long-context routing
- `POST /v1/embeddings`
- `POST /v1/images/generations`
- route health probing
- retry/failover from an HTTP 503 provider to a healthy provider
- provider credential headers reaching the correct simulated service

## Run only the real-HTTP E2E suite

```bash
python -m pip install -e ".[test]"
python -m pytest -q tests/test_e2e_mock_provider_service.py
```

The test fixture starts the service on an ephemeral localhost port and shuts it
down automatically.

## Run the mock provider manually

```bash
python scripts/mock_model_service.py --port 8099
```

Examples:

```bash
curl http://127.0.0.1:8099/openai/v1/models

curl http://127.0.0.1:8099/openai/v1/chat/completions \
  -H "Authorization: Bearer test" \
  -H "Content-Type: application/json" \
  -d '{"model":"mock-chat","messages":[{"role":"user","content":"hello"}]}'
```

## Full repository verification

```bash
python -m compileall -q freellm_gateway tests
python -m pytest -q
```

GitHub Actions runs the same compile and full-test commands on pull requests and
pushes to the AI base branch.
