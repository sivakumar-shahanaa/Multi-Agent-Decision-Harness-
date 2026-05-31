"""Slide/frame vision via W&B Inference (OpenAI-compatible, base64 image_url blocks).

Deliberately SEPARATE from llm.complete_json (which is pinned to a text-only model):
this uses a vision-capable catalog model (google/gemma-4-31B-it, Kimi-K2.6 fallback).
Routed through resolve_backend so it returns '' (mock) when no W&B key — and so tests
can force-mock it by monkeypatching resolve_backend, exactly like the council engine.
"""
from __future__ import annotations

import asyncio
import base64

import weave

from ...config import get_settings
from ..llm import _wandb_client, resolve_backend


def _data_url(img: bytes, mime: str = "image/jpeg") -> str:
    return f"data:{mime};base64,{base64.b64encode(img).decode()}"


@weave.op()
async def describe_images(images: list[bytes], instruction: str) -> str:
    """Return the vision model's prose reading of the images, or '' when vision is
    unavailable (no images, or no W&B backend)."""
    images = [i for i in images if i]
    if not images or resolve_backend("wandb") != "wandb":
        return ""
    s = get_settings()
    content: list[dict] = [{"type": "text", "text": instruction}]
    for img in images:
        content.append({"type": "image_url", "image_url": {"url": _data_url(img)}})
    messages = [{"role": "user", "content": content}]
    for model in (s.vision_model, s.vision_model_fallback):
        try:
            resp = await asyncio.wait_for(_wandb_client().chat.completions.create(
                model=model, messages=messages, temperature=0, max_tokens=1500), timeout=120)
            text = (resp.choices[0].message.content or "").strip()
            if text:
                return text
        except Exception:
            continue  # fall through to the fallback model, then give up
    return ""
