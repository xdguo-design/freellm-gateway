#!/usr/bin/env python3
"""Deterministic local model-provider service for FreeLLM Gateway E2E tests.

It speaks both an OpenAI-compatible subset and a Gemini-native subset over real
HTTP so the gateway can be tested without vendor credentials or flaky external
network dependencies.
"""

from __future__ import annotations

import argparse
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


OPENAI_MODELS = [
    "mock-chat",
    "mock-vision",
    "mock-long",
    "mock-embedding",
    "mock-image",
    "mock-fail",
]


class MockModelHandler(BaseHTTPRequestHandler):
    server_version = "FreeLLMMockModel/1.0"

    def log_message(self, format, *args):  # noqa: A003
        return

    def _record(self, body=None):
        self.server.records.append(
            {
                "method": self.command,
                "path": urlsplit(self.path).path,
                "query": urlsplit(self.path).query,
                "body": body,
                "authorization": self.headers.get("Authorization"),
                "gemini_key": self.headers.get("x-goog-api-key"),
            }
        )

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def _send_json(self, status, payload):
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_sse(self, events):
        data = "".join(f"data: {event}\n\n" for event in events).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlsplit(self.path).path
        self._record()

        if path == "/openai/v1/models":
            self._send_json(
                200,
                {"object": "list", "data": [{"id": model} for model in OPENAI_MODELS]},
            )
            return

        if path == "/gemini/v1beta/models":
            self._send_json(
                200,
                {
                    "models": [
                        {
                            "name": "models/gemini-mock",
                            "displayName": "Gemini Mock",
                            "inputTokenLimit": 1048576,
                            "supportedGenerationMethods": [
                                "generateContent",
                                "countTokens",
                            ],
                        },
                        {
                            "name": "models/gemini-embedding-mock",
                            "supportedGenerationMethods": ["embedContent"],
                        },
                    ]
                },
            )
            return

        self._send_json(404, {"error": {"message": "not found"}})

    def do_POST(self):
        path = urlsplit(self.path).path
        body = self._read_json()
        self._record(body)

        if path == "/openai/v1/chat/completions":
            self._openai_chat(body)
            return

        if path == "/openai/v1/embeddings":
            model = body.get("model", "mock-embedding")
            self._send_json(
                200,
                {
                    "object": "list",
                    "model": model,
                    "data": [
                        {
                            "object": "embedding",
                            "index": 0,
                            "embedding": [0.1, 0.2, 0.3, 0.4],
                        }
                    ],
                    "usage": {"prompt_tokens": 3, "total_tokens": 3},
                },
            )
            return

        if path == "/openai/v1/images/generations":
            model = body.get("model", "mock-image")
            self._send_json(
                200,
                {
                    "created": 1,
                    "model": model,
                    "data": [
                        {
                            "url": "https://example.test/mock-image.png",
                            "revised_prompt": body.get("prompt", ""),
                        }
                    ],
                },
            )
            return

        if re.fullmatch(r"/gemini/v1beta/models/[^/]+:generateContent", path):
            self._gemini_chat(body, path)
            return

        if re.fullmatch(r"/gemini/v1beta/models/[^/]+:streamGenerateContent", path):
            self._gemini_stream(path)
            return

        self._send_json(404, {"error": {"message": "not found"}})

    def _openai_chat(self, body):
        model = body.get("model", "mock-chat")
        if model == "mock-fail":
            self._send_json(503, {"error": {"message": "temporary upstream failure"}})
            return

        if body.get("stream"):
            self._send_sse(
                [
                    json.dumps(
                        {
                            "id": "openai-stream-1",
                            "model": model,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"role": "assistant", "content": "hello "},
                                    "finish_reason": None,
                                }
                            ],
                        },
                        separators=(",", ":"),
                    ),
                    json.dumps(
                        {
                            "id": "openai-stream-1",
                            "model": model,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": "world"},
                                    "finish_reason": "stop",
                                }
                            ],
                        },
                        separators=(",", ":"),
                    ),
                    "[DONE]",
                ]
            )
            return

        if body.get("tools"):
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_mock_lookup",
                        "type": "function",
                        "function": {
                            "name": "lookup",
                            "arguments": "{\"q\":\"Tokyo\"}",
                        },
                    }
                ],
            }
            finish_reason = "tool_calls"
        elif body.get("response_format"):
            message = {
                "role": "assistant",
                "content": json.dumps({"ok": True, "model": model}, separators=(",", ":")),
            }
            finish_reason = "stop"
        elif _contains_image(body.get("messages", [])):
            message = {"role": "assistant", "content": "vision-ok"}
            finish_reason = "stop"
        else:
            message = {"role": "assistant", "content": f"mock:{model}:ok"}
            finish_reason = "stop"

        self._send_json(
            200,
            {
                "id": "openai-response-1",
                "object": "chat.completion",
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": finish_reason,
                    }
                ],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 3,
                    "total_tokens": 8,
                },
            },
        )

    def _gemini_chat(self, body, path):
        model = path.rsplit("/", 1)[1].split(":", 1)[0]
        self._send_json(
            200,
            {
                "responseId": "gemini-response-1",
                "modelVersion": model,
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [{"text": "gemini-ok"}],
                        },
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 4,
                    "candidatesTokenCount": 2,
                    "totalTokenCount": 6,
                },
            },
        )

    def _gemini_stream(self, path):
        model = path.rsplit("/", 1)[1].split(":", 1)[0]
        self._send_sse(
            [
                json.dumps(
                    {
                        "responseId": "gemini-stream-1",
                        "modelVersion": model,
                        "candidates": [
                            {"content": {"parts": [{"text": "gemini "}]}}
                        ],
                    },
                    separators=(",", ":"),
                ),
                json.dumps(
                    {
                        "responseId": "gemini-stream-1",
                        "modelVersion": model,
                        "candidates": [
                            {
                                "content": {"parts": [{"text": "stream"}]},
                                "finishReason": "STOP",
                            }
                        ],
                        "usageMetadata": {
                            "promptTokenCount": 2,
                            "candidatesTokenCount": 2,
                            "totalTokenCount": 4,
                        },
                    },
                    separators=(",", ":"),
                ),
                "[DONE]",
            ]
        )


def _contains_image(value):
    if isinstance(value, dict):
        if value.get("type") in {"image_url", "input_image"}:
            return True
        return any(_contains_image(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_image(item) for item in value)
    return False


def start_mock_server(host="127.0.0.1", port=0):
    server = ThreadingHTTPServer((host, port), MockModelHandler)
    server.records = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8099)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), MockModelHandler)
    server.records = []
    print(f"mock model service listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
