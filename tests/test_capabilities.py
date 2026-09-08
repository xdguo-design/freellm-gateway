import pytest

from freellm_gateway.models import ModelRoute
from freellm_gateway.service import ModelGateway


class RecordingAdapter:
    def __init__(self):
        self.models = []

    async def complete(self, payload):
        self.models.append(payload["model"])
        return {"model": payload["model"], "choices": []}


@pytest.mark.asyncio
async def test_image_request_selects_vision_route():
    vision = RecordingAdapter()
    text = RecordingAdapter()
    gateway = ModelGateway(
        [
            ModelRoute(id="text", provider_id="p", remote_model="text", priority=1, capabilities=frozenset({"chat"})),
            ModelRoute(id="vision", provider_id="p", remote_model="vision", priority=2, capabilities=frozenset({"chat", "vision"})),
        ],
        {"text": text, "vision": vision},
    )

    await gateway.complete({"model": "auto", "messages": [{"role": "user", "content": [{"type": "text", "text": "what?"}, {"type": "image_url", "image_url": {"url": "https://example.test/a.png"}}]}]})

    assert vision.models == ["vision"]
    assert text.models == []


@pytest.mark.asyncio
async def test_image_generation_selects_image_generation_route():
    image = RecordingAdapter()
    chat = RecordingAdapter()
    gateway = ModelGateway(
        [
            ModelRoute(id="chat", provider_id="p", remote_model="chat", priority=1),
            ModelRoute(id="image", provider_id="p", remote_model="image", priority=2, capabilities=frozenset({"image_generation"})),
        ],
        {"chat": chat, "image": image},
    )

    await gateway.complete({"model": "auto", "prompt": "a lake", "task": "image_generation"})

    assert image.models == ["image"]
    assert chat.models == []


@pytest.mark.asyncio
async def test_long_context_request_selects_long_context_route():
    long_context = RecordingAdapter()
    short_context = RecordingAdapter()
    gateway = ModelGateway(
        [
            ModelRoute(id="short", provider_id="p", remote_model="short", priority=1),
            ModelRoute(id="long", provider_id="p", remote_model="long", priority=2, capabilities=frozenset({"chat", "long_context"})),
        ],
        {"short": short_context, "long": long_context},
    )

    await gateway.complete({"model": "auto", "messages": [{"role": "user", "content": "x" * 40000}]})

    assert long_context.models == ["long"]
    assert short_context.models == []
