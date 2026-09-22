from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Any, Mapping


@dataclass(frozen=True)
class TextPart:
    text: str


@dataclass(frozen=True)
class ImagePart:
    url: str
    detail: str | None = None


@dataclass(frozen=True)
class RawPart:
    value: Mapping[str, Any]


ContentPart = TextPart | ImagePart | RawPart


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: tuple[ContentPart, ...] = ()
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: tuple[Mapping[str, Any], ...] = ()
    extra: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_openai(cls, value: Mapping[str, Any]) -> "ChatMessage":
        raw_content = value.get("content")
        parts: list[ContentPart] = []
        if isinstance(raw_content, str):
            parts.append(TextPart(raw_content))
        elif isinstance(raw_content, list):
            for part in raw_content:
                if not isinstance(part, Mapping):
                    parts.append(RawPart({"value": part}))
                    continue
                part_type = part.get("type")
                if part_type in {"text", "input_text"} and isinstance(part.get("text"), str):
                    parts.append(TextPart(part["text"]))
                    continue
                if part_type == "image_url":
                    image = part.get("image_url")
                    if isinstance(image, str):
                        parts.append(ImagePart(image))
                        continue
                    if isinstance(image, Mapping) and isinstance(image.get("url"), str):
                        detail = image.get("detail")
                        parts.append(ImagePart(image["url"], detail if isinstance(detail, str) else None))
                        continue
                parts.append(RawPart(dict(part)))
        elif raw_content is not None:
            parts.append(RawPart({"value": raw_content}))

        tool_calls = tuple(
            dict(item) for item in value.get("tool_calls", []) if isinstance(item, Mapping)
        )
        known = {"role", "content", "name", "tool_call_id", "tool_calls"}
        return cls(
            role=str(value.get("role", "assistant")),
            content=tuple(parts),
            name=value.get("name") if isinstance(value.get("name"), str) else None,
            tool_call_id=(
                value.get("tool_call_id") if isinstance(value.get("tool_call_id"), str) else None
            ),
            tool_calls=tool_calls,
            extra={key: item for key, item in value.items() if key not in known},
        )

    def to_openai(self, *, delta: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = dict(self.extra)
        if not delta or self.role:
            data["role"] = self.role

        if not self.content:
            if not delta:
                data["content"] = None if self.tool_calls else ""
        elif len(self.content) == 1 and isinstance(self.content[0], TextPart):
            data["content"] = self.content[0].text
        else:
            content: list[dict[str, Any]] = []
            for part in self.content:
                if isinstance(part, TextPart):
                    content.append({"type": "text", "text": part.text})
                elif isinstance(part, ImagePart):
                    image: dict[str, Any] = {"url": part.url}
                    if part.detail:
                        image["detail"] = part.detail
                    content.append({"type": "image_url", "image_url": image})
                else:
                    content.append(dict(part.value))
            data["content"] = content

        if self.name is not None:
            data["name"] = self.name
        if self.tool_call_id is not None:
            data["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            data["tool_calls"] = [dict(item) for item in self.tool_calls]
        return data


@dataclass(frozen=True)
class ChatRequest:
    model: str
    messages: tuple[ChatMessage, ...] = ()
    max_tokens: int | None = None
    temperature: float | None = None
    stream: bool | None = None
    tools: tuple[Mapping[str, Any], ...] = ()
    extra: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_openai_payload(cls, payload: Mapping[str, Any]) -> "ChatRequest":
        messages = tuple(
            ChatMessage.from_openai(message)
            for message in payload.get("messages", [])
            if isinstance(message, Mapping)
        )
        tools = tuple(
            dict(tool) for tool in payload.get("tools", []) if isinstance(tool, Mapping)
        )
        known = {"model", "messages", "max_tokens", "temperature", "stream", "tools"}
        max_tokens = payload.get("max_tokens")
        temperature = payload.get("temperature")
        stream = payload.get("stream") if "stream" in payload else None
        return cls(
            model=str(payload.get("model", "auto")),
            messages=messages,
            max_tokens=max_tokens if isinstance(max_tokens, int) else None,
            temperature=(
                float(temperature) if isinstance(temperature, (int, float)) else None
            ),
            stream=stream if isinstance(stream, bool) else None,
            tools=tools,
            extra={key: value for key, value in payload.items() if key not in known},
        )

    def with_model(self, model: str) -> "ChatRequest":
        return replace(self, model=model)

    def to_openai_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = dict(self.extra)
        payload["model"] = self.model
        payload["messages"] = [message.to_openai() for message in self.messages]
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.stream is not None:
            payload["stream"] = self.stream
        if self.tools:
            payload["tools"] = [dict(tool) for tool in self.tools]
        return payload


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    extra: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_openai(cls, usage: Mapping[str, Any] | None) -> "TokenUsage | None":
        if not isinstance(usage, Mapping):
            return None
        known = {"prompt_tokens", "completion_tokens", "total_tokens"}
        prompt = usage.get("prompt_tokens", 0)
        completion = usage.get("completion_tokens", 0)
        total = usage.get("total_tokens", 0)
        return cls(
            input_tokens=prompt if isinstance(prompt, int) else 0,
            output_tokens=completion if isinstance(completion, int) else 0,
            total_tokens=total if isinstance(total, int) else 0,
            extra={key: value for key, value in usage.items() if key not in known},
        )

    def to_openai(self) -> dict[str, Any]:
        usage = dict(self.extra)
        usage.update(
            {
                "prompt_tokens": self.input_tokens,
                "completion_tokens": self.output_tokens,
                "total_tokens": self.total_tokens,
            }
        )
        return usage


@dataclass(frozen=True)
class ChatResponse:
    id: str
    model: str
    message: ChatMessage
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    created: int | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)
    choice_extra: Mapping[str, Any] = field(default_factory=dict)
    additional_choices: tuple[Mapping[str, Any], ...] = ()
    choice_present: bool = True

    @classmethod
    def from_openai_response(cls, payload: Mapping[str, Any]) -> "ChatResponse":
        choices = payload.get("choices") or []
        choice = choices[0] if choices and isinstance(choices[0], Mapping) else {}
        message_value = choice.get("message")
        message = (
            ChatMessage.from_openai(message_value)
            if isinstance(message_value, Mapping)
            else ChatMessage(role="assistant")
        )
        known_top = {"id", "object", "created", "model", "choices", "usage"}
        known_choice = {"index", "message", "finish_reason"}
        created = payload.get("created")
        return cls(
            id=str(payload.get("id", "")),
            model=str(payload.get("model", "")),
            message=message,
            finish_reason=(
                choice.get("finish_reason")
                if isinstance(choice.get("finish_reason"), str)
                else None
            ),
            usage=TokenUsage.from_openai(payload.get("usage")),
            created=created if isinstance(created, int) else None,
            extra={key: value for key, value in payload.items() if key not in known_top},
            choice_extra={key: value for key, value in choice.items() if key not in known_choice},
            additional_choices=tuple(
                dict(item) for item in choices[1:] if isinstance(item, Mapping)
            ),
            choice_present=bool(choices),
        )

    def to_openai_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = dict(self.extra)
        payload.update(
            {
                "id": self.id,
                "object": "chat.completion",
                "model": self.model,
            }
        )
        if self.created is not None:
            payload["created"] = self.created
        choice = dict(self.choice_extra)
        choice.update(
            {
                "index": 0,
                "message": self.message.to_openai(),
                "finish_reason": self.finish_reason,
            }
        )
        payload["choices"] = (
            [choice, *[dict(item) for item in self.additional_choices]]
            if self.choice_present
            else []
        )
        if self.usage is not None:
            payload["usage"] = self.usage.to_openai()
        return payload


@dataclass(frozen=True)
class ChatChunk:
    id: str = ""
    model: str = ""
    delta: ChatMessage = field(default_factory=lambda: ChatMessage(role="assistant"))
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    index: int = 0
    done: bool = False
    extra: Mapping[str, Any] = field(default_factory=dict)
    choice_extra: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_openai_event(cls, payload: Mapping[str, Any]) -> "ChatChunk":
        choices = payload.get("choices") or []
        choice = choices[0] if choices and isinstance(choices[0], Mapping) else {}
        delta_value = choice.get("delta")
        delta = (
            ChatMessage.from_openai(delta_value)
            if isinstance(delta_value, Mapping)
            else ChatMessage(role="assistant")
        )
        known_top = {"id", "object", "created", "model", "choices", "usage"}
        known_choice = {"index", "delta", "finish_reason"}
        index = choice.get("index", 0)
        return cls(
            id=str(payload.get("id", "")),
            model=str(payload.get("model", "")),
            delta=delta,
            finish_reason=(
                choice.get("finish_reason")
                if isinstance(choice.get("finish_reason"), str)
                else None
            ),
            usage=TokenUsage.from_openai(payload.get("usage")),
            index=index if isinstance(index, int) else 0,
            extra={key: value for key, value in payload.items() if key not in known_top},
            choice_extra={key: value for key, value in choice.items() if key not in known_choice},
        )

    def to_openai_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = dict(self.extra)
        payload.update(
            {
                "id": self.id,
                "object": "chat.completion.chunk",
                "model": self.model,
            }
        )
        choice = dict(self.choice_extra)
        choice.update(
            {
                "index": self.index,
                "delta": self.delta.to_openai(delta=True),
                "finish_reason": self.finish_reason,
            }
        )
        payload["choices"] = [choice]
        if self.usage is not None:
            payload["usage"] = self.usage.to_openai()
        return payload

    def to_openai_sse(self) -> bytes:
        if self.done:
            return b"data: [DONE]\n\n"
        return ("data: " + json.dumps(self.to_openai_dict(), separators=(",", ":")) + "\n\n").encode(
            "utf-8"
        )


@dataclass(frozen=True)
class ModelInfo:
    id: str
    provider_id: str
    display_name: str | None = None
    context_window: int | None = None
    capabilities: frozenset[str] = field(default_factory=lambda: frozenset({"chat"}))
    extra: Mapping[str, Any] = field(default_factory=dict)
