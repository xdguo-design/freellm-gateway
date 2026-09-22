from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Mapping
from typing import Any
from urllib.parse import quote

import httpx

from ..contracts import (
    ChatChunk,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ImagePart,
    ModelInfo,
    RawPart,
    TextPart,
    TokenUsage,
)
from ..failures import classify_failure, parse_retry_after
from .base import ProviderError


_DATA_URI = re.compile(
    r"^data:(?P<mime>[a-zA-Z0-9.+-]+/[a-zA-Z0-9.+-]+);base64,(?P<data>.+)$",
    re.DOTALL,
)

_GEMINI_PART_KEYS = frozenset(
    {
        "text",
        "inlineData",
        "fileData",
        "functionCall",
        "functionResponse",
        "executableCode",
        "codeExecutionResult",
        "toolCall",
        "toolResponse",
    }
)

_FINISH_REASON = {
    "STOP": "stop",
    "MAX_TOKENS": "length",
    "SAFETY": "content_filter",
    "RECITATION": "content_filter",
    "BLOCKLIST": "content_filter",
    "PROHIBITED_CONTENT": "content_filter",
    "SPII": "content_filter",
    "IMAGE_SAFETY": "content_filter",
    "MALFORMED_FUNCTION_CALL": "tool_error",
}


class GeminiNativeAdapter:
    """Native Gemini generateContent adapter.

    This adapter intentionally uses Google's Gemini wire protocol rather than
    the OpenAI-compatibility endpoint. The gateway core only sees normalized
    ChatRequest / ChatResponse / ChatChunk values.
    """

    capabilities = frozenset({"chat", "stream", "models", "vision", "tools"})

    def __init__(
        self,
        base_url: str,
        api_key: str,
        client: httpx.AsyncClient | None = None,
        *,
        provider_id: str = "gemini",
    ):
        base = base_url.rstrip("/")
        if "/models/" in base:
            base = base.split("/models/", 1)[0]
        elif base.endswith("/models"):
            base = base[: -len("/models")]
        self.base_url = base
        self.api_key = api_key
        self.provider_id = provider_id
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }

    def _model_url(self, model: str, operation: str) -> str:
        model_id = model.removeprefix("models/")
        return f"{self.base_url}/models/{quote(model_id, safe='-_.')}" f":{operation}"

    async def chat(self, request: ChatRequest) -> ChatResponse:
        payload = self._to_gemini_request(request)
        data = await self._post_json(
            self._model_url(request.model, "generateContent"),
            payload,
        )
        return self._to_chat_response(data, request.model)

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        payload = self._to_gemini_request(request)
        url = self._model_url(request.model, "streamGenerateContent")
        try:
            async with self.client.stream(
                "POST",
                url,
                params={"alt": "sse"},
                headers=self._headers,
                json=payload,
            ) as response:
                self._raise_for_error(response)
                data_lines: list[str] = []
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        data_lines.append(line[5:].strip())
                        continue
                    if line == "" and data_lines:
                        raw = "\n".join(data_lines)
                        data_lines.clear()
                        if raw == "[DONE]":
                            yield ChatChunk(done=True)
                            return
                        yield self._chunk_from_json(raw, request.model)
                if data_lines:
                    raw = "\n".join(data_lines)
                    if raw != "[DONE]":
                        yield self._chunk_from_json(raw, request.model)
        except ProviderError:
            raise
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", 504, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("network_error", 502, str(exc)) from exc

        yield ChatChunk(done=True)

    async def models(self) -> list[ModelInfo]:
        result: list[ModelInfo] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {"pageSize": 1000}
            if page_token:
                params["pageToken"] = page_token
            payload = await self._get_json(f"{self.base_url}/models", params=params)
            for item in payload.get("models", []):
                if not isinstance(item, Mapping):
                    continue
                methods = item.get("supportedGenerationMethods")
                if isinstance(methods, list) and "generateContent" not in methods:
                    continue
                name = item.get("name")
                if not isinstance(name, str):
                    continue
                model_id = name.removeprefix("models/")
                token_limit = item.get("inputTokenLimit")
                result.append(
                    ModelInfo(
                        id=model_id,
                        provider_id=self.provider_id,
                        display_name=(
                            item.get("displayName")
                            if isinstance(item.get("displayName"), str)
                            else None
                        ),
                        context_window=token_limit if isinstance(token_limit, int) else None,
                        capabilities=frozenset({"chat"}),
                        extra={
                            key: value
                            for key, value in item.items()
                            if key
                            not in {
                                "name",
                                "displayName",
                                "inputTokenLimit",
                                "supportedGenerationMethods",
                            }
                        },
                    )
                )
            page_token_value = payload.get("nextPageToken")
            if not isinstance(page_token_value, str) or not page_token_value:
                break
            page_token = page_token_value
        return result

    async def list_models(self) -> list[str]:
        return [model.id for model in await self.models()]

    async def aclose(self) -> None:
        await self.client.aclose()

    async def _post_json(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self.client.post(url, headers=self._headers, json=body)
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", 504, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("network_error", 502, str(exc)) from exc
        self._raise_for_error(response)
        return self._json_object(response)

    async def _get_json(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = await self.client.get(url, headers=self._headers, params=params)
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", 504, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("network_error", 502, str(exc)) from exc
        self._raise_for_error(response)
        return self._json_object(response)

    def _json_object(self, response: httpx.Response) -> dict[str, Any]:
        try:
            value = response.json()
        except ValueError as exc:
            raise ProviderError(
                "invalid_response",
                502,
                "Gemini returned a non-JSON response",
                retriable=False,
            ) from exc
        if not isinstance(value, dict):
            raise ProviderError(
                "invalid_response",
                502,
                "Gemini returned a non-object JSON response",
                retriable=False,
            )
        return value

    def _raise_for_error(self, response: httpx.Response) -> None:
        if not response.is_error:
            return
        message = response.text
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, Mapping):
            error = payload.get("error")
            if isinstance(error, Mapping) and isinstance(error.get("message"), str):
                message = error["message"]
        failure = classify_failure(
            status_code=response.status_code,
            message=message,
            retry_after=parse_retry_after(response.headers.get("retry-after")),
        )
        raise ProviderError(
            failure.type,
            response.status_code,
            message,
            retriable=failure.retryable,
            retry_after=failure.retry_after,
        )

    def _to_gemini_request(self, request: ChatRequest) -> dict[str, Any]:
        system_parts: list[dict[str, Any]] = []
        contents: list[dict[str, Any]] = []
        tool_names = self._tool_call_names(request.messages)

        for message in request.messages:
            if message.role == "system":
                system_parts.extend(self._system_parts(message))
                continue

            role = "model" if message.role == "assistant" else "user"
            parts = self._message_parts(message, tool_names)
            if parts:
                contents.append({"role": role, "parts": parts})

        payload: dict[str, Any] = {"contents": contents}
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}

        generation_config = self._generation_config(request)
        if generation_config:
            payload["generationConfig"] = generation_config

        tools = self._tools(request.tools)
        if tools:
            payload["tools"] = tools

        tool_config = self._tool_config(request.extra.get("tool_choice"))
        if tool_config:
            payload["toolConfig"] = tool_config

        safety = request.extra.get("safety_settings")
        if isinstance(safety, list):
            payload["safetySettings"] = safety

        native = request.extra.get("gemini")
        if isinstance(native, Mapping):
            for key, value in native.items():
                if key not in {"contents", "systemInstruction"}:
                    payload[key] = value

        return payload

    def _system_parts(self, message: ChatMessage) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for part in message.content:
            if isinstance(part, TextPart):
                result.append({"text": part.text})
            else:
                raise ProviderError(
                    "invalid_request",
                    400,
                    "Gemini systemInstruction currently supports text only",
                    retriable=False,
                )
        return result

    def _message_parts(
        self,
        message: ChatMessage,
        tool_names: Mapping[str, str],
    ) -> list[dict[str, Any]]:
        if message.role == "tool":
            return [self._function_response_part(message, tool_names)]

        result: list[dict[str, Any]] = []
        for part in message.content:
            result.append(self._content_part(part))

        if message.role == "assistant":
            for index, tool_call in enumerate(message.tool_calls):
                result.append(self._function_call_part(tool_call, index))
        return result

    def _content_part(self, part) -> dict[str, Any]:
        if isinstance(part, TextPart):
            return {"text": part.text}
        if isinstance(part, ImagePart):
            match = _DATA_URI.match(part.url)
            if not match:
                raise ProviderError(
                    "invalid_request",
                    400,
                    "Gemini image_url must be a data: URI; use a native fileData part for Gemini Files URIs",
                    retriable=False,
                )
            return {
                "inlineData": {
                    "mimeType": match.group("mime"),
                    "data": match.group("data"),
                }
            }
        if isinstance(part, RawPart):
            value = dict(part.value)
            if any(key in value for key in _GEMINI_PART_KEYS):
                return value
            raise ProviderError(
                "invalid_request",
                400,
                "unsupported native Gemini content part",
                retriable=False,
            )
        raise ProviderError(
            "invalid_request",
            400,
            "unsupported chat content part",
            retriable=False,
        )

    def _function_call_part(
        self,
        tool_call: Mapping[str, Any],
        index: int,
    ) -> dict[str, Any]:
        function = tool_call.get("function")
        if not isinstance(function, Mapping) or not isinstance(function.get("name"), str):
            raise ProviderError(
                "invalid_request",
                400,
                "OpenAI function tool call is missing function.name",
                retriable=False,
            )
        arguments = function.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments or "{}")
            except json.JSONDecodeError as exc:
                raise ProviderError(
                    "invalid_request",
                    400,
                    "tool call arguments must be valid JSON",
                    retriable=False,
                ) from exc
        if not isinstance(arguments, Mapping):
            raise ProviderError(
                "invalid_request",
                400,
                "tool call arguments must decode to an object",
                retriable=False,
            )
        call: dict[str, Any] = {
            "name": function["name"],
            "args": dict(arguments),
        }
        call_id = tool_call.get("id")
        if isinstance(call_id, str):
            call["id"] = call_id
        elif index >= 0:
            call["id"] = f"call_{index}"
        return {"functionCall": call}

    def _function_response_part(
        self,
        message: ChatMessage,
        tool_names: Mapping[str, str],
    ) -> dict[str, Any]:
        name = message.name
        if name is None and message.tool_call_id is not None:
            name = tool_names.get(message.tool_call_id)
        if not name:
            raise ProviderError(
                "invalid_request",
                400,
                "tool result cannot be mapped to Gemini without a function name",
                retriable=False,
            )

        text = "".join(
            part.text for part in message.content if isinstance(part, TextPart)
        )
        try:
            response_value = json.loads(text) if text else {}
        except json.JSONDecodeError:
            response_value = {"output": text}
        if not isinstance(response_value, Mapping):
            response_value = {"output": response_value}

        response: dict[str, Any] = {
            "name": name,
            "response": dict(response_value),
        }
        if message.tool_call_id:
            response["id"] = message.tool_call_id
        return {"functionResponse": response}

    def _tool_call_names(
        self,
        messages: tuple[ChatMessage, ...],
    ) -> dict[str, str]:
        names: dict[str, str] = {}
        for message in messages:
            for tool_call in message.tool_calls:
                call_id = tool_call.get("id")
                function = tool_call.get("function")
                if (
                    isinstance(call_id, str)
                    and isinstance(function, Mapping)
                    and isinstance(function.get("name"), str)
                ):
                    names[call_id] = function["name"]
        return names

    def _tools(
        self,
        tools: tuple[Mapping[str, Any], ...],
    ) -> list[dict[str, Any]]:
        declarations: list[dict[str, Any]] = []
        for tool in tools:
            if tool.get("type") != "function":
                raise ProviderError(
                    "invalid_request",
                    400,
                    "Gemini native adapter currently supports function tools only",
                    retriable=False,
                )
            function = tool.get("function")
            if not isinstance(function, Mapping) or not isinstance(function.get("name"), str):
                raise ProviderError(
                    "invalid_request",
                    400,
                    "function tool is missing function.name",
                    retriable=False,
                )
            declaration: dict[str, Any] = {"name": function["name"]}
            description = function.get("description")
            if isinstance(description, str):
                declaration["description"] = description
            parameters = function.get("parameters")
            if isinstance(parameters, Mapping):
                declaration["parameters"] = dict(parameters)
            declarations.append(declaration)
        return [{"functionDeclarations": declarations}] if declarations else []

    def _tool_config(self, choice: Any) -> dict[str, Any] | None:
        mode: str | None = None
        allowed: list[str] | None = None
        if choice == "auto":
            mode = "AUTO"
        elif choice == "none":
            mode = "NONE"
        elif choice == "required":
            mode = "ANY"
        elif isinstance(choice, Mapping):
            function = choice.get("function")
            if isinstance(function, Mapping) and isinstance(function.get("name"), str):
                mode = "ANY"
                allowed = [function["name"]]
        if mode is None:
            return None
        config: dict[str, Any] = {"mode": mode}
        if allowed:
            config["allowedFunctionNames"] = allowed
        return {"functionCallingConfig": config}

    def _generation_config(self, request: ChatRequest) -> dict[str, Any]:
        config: dict[str, Any] = {}
        if request.max_tokens is not None:
            config["maxOutputTokens"] = request.max_tokens
        if request.temperature is not None:
            config["temperature"] = request.temperature

        aliases = {
            "top_p": "topP",
            "top_k": "topK",
            "seed": "seed",
            "presence_penalty": "presencePenalty",
            "frequency_penalty": "frequencyPenalty",
            "n": "candidateCount",
        }
        for source, target in aliases.items():
            if source in request.extra:
                config[target] = request.extra[source]

        stop = request.extra.get("stop")
        if isinstance(stop, str):
            config["stopSequences"] = [stop]
        elif isinstance(stop, list) and all(isinstance(item, str) for item in stop):
            config["stopSequences"] = stop

        response_format = request.extra.get("response_format")
        if isinstance(response_format, Mapping):
            response_type = response_format.get("type")
            if response_type == "json_object":
                config["responseMimeType"] = "application/json"
            elif response_type == "json_schema":
                schema_wrapper = response_format.get("json_schema")
                if isinstance(schema_wrapper, Mapping):
                    schema = schema_wrapper.get("schema")
                    if isinstance(schema, Mapping):
                        config["responseMimeType"] = "application/json"
                        config["responseJsonSchema"] = dict(schema)

        return config

    def _to_chat_response(
        self,
        payload: Mapping[str, Any],
        requested_model: str,
    ) -> ChatResponse:
        candidate = self._first_candidate(payload)
        message = self._message_from_candidate(candidate)
        finish_reason = self._finish_reason(candidate, bool(message.tool_calls))
        usage = self._usage(payload.get("usageMetadata"))
        metadata = {
            key: value
            for key, value in payload.items()
            if key not in {"candidates", "usageMetadata", "responseId", "modelVersion"}
        }
        return ChatResponse(
            id=payload.get("responseId") if isinstance(payload.get("responseId"), str) else "",
            model=(
                payload.get("modelVersion")
                if isinstance(payload.get("modelVersion"), str)
                else requested_model
            ),
            message=message,
            finish_reason=finish_reason,
            usage=usage,
            extra={"gemini": metadata} if metadata else {},
        )

    def _chunk_from_json(self, raw: str, requested_model: str) -> ChatChunk:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProviderError(
                "invalid_response",
                502,
                "Gemini returned invalid SSE JSON",
                retriable=False,
            ) from exc
        if not isinstance(payload, Mapping):
            raise ProviderError(
                "invalid_response",
                502,
                "Gemini returned a non-object SSE event",
                retriable=False,
            )
        candidate = self._first_candidate(payload)
        message = self._message_from_candidate(candidate)
        return ChatChunk(
            id=payload.get("responseId") if isinstance(payload.get("responseId"), str) else "",
            model=(
                payload.get("modelVersion")
                if isinstance(payload.get("modelVersion"), str)
                else requested_model
            ),
            delta=message,
            finish_reason=self._finish_reason(candidate, bool(message.tool_calls)),
            usage=self._usage(payload.get("usageMetadata")),
        )

    def _first_candidate(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        candidates = payload.get("candidates")
        if isinstance(candidates, list) and candidates and isinstance(candidates[0], Mapping):
            return candidates[0]
        return {}

    def _message_from_candidate(self, candidate: Mapping[str, Any]) -> ChatMessage:
        content = candidate.get("content")
        parts = content.get("parts") if isinstance(content, Mapping) else None
        text_parts: list[Any] = []
        tool_calls: list[dict[str, Any]] = []
        if isinstance(parts, list):
            for index, part in enumerate(parts):
                if not isinstance(part, Mapping):
                    continue
                if isinstance(part.get("text"), str):
                    text_parts.append(TextPart(part["text"]))
                    continue
                function_call = part.get("functionCall")
                if isinstance(function_call, Mapping) and isinstance(function_call.get("name"), str):
                    call_id = function_call.get("id")
                    tool_calls.append(
                        {
                            "id": call_id if isinstance(call_id, str) else f"call_{index}",
                            "type": "function",
                            "function": {
                                "name": function_call["name"],
                                "arguments": json.dumps(
                                    function_call.get("args", {}),
                                    separators=(",", ":"),
                                ),
                            },
                        }
                    )
                    continue
                text_parts.append(RawPart({"type": "gemini", "gemini": dict(part)}))
        return ChatMessage(
            role="assistant",
            content=tuple(text_parts),
            tool_calls=tuple(tool_calls),
        )

    def _finish_reason(
        self,
        candidate: Mapping[str, Any],
        has_tool_calls: bool,
    ) -> str | None:
        if has_tool_calls:
            return "tool_calls"
        reason = candidate.get("finishReason")
        if not isinstance(reason, str):
            return None
        return _FINISH_REASON.get(reason, reason.lower())

    def _usage(self, value: Any) -> TokenUsage | None:
        if not isinstance(value, Mapping):
            return None
        prompt = value.get("promptTokenCount", 0)
        output = value.get("candidatesTokenCount", 0)
        total = value.get("totalTokenCount", 0)
        return TokenUsage(
            input_tokens=prompt if isinstance(prompt, int) else 0,
            output_tokens=output if isinstance(output, int) else 0,
            total_tokens=total if isinstance(total, int) else 0,
            extra={
                key: item
                for key, item in value.items()
                if key not in {"promptTokenCount", "candidatesTokenCount", "totalTokenCount"}
            },
        )
