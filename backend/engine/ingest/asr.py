"""Speech-to-text for demo videos: Groq Whisper (primary) → ElevenLabs Scribe
(the already-built fallback) → '' (mock). Groq is used for transcription ONLY —
never the council agents, which stay on W&B Inference.

For Groq, the audio track is first extracted to 16 kHz mono FLAC (small, under the
free-tier 25 MB cap); Scribe accepts the container directly so it needs no ffmpeg.
"""
from __future__ import annotations

import asyncio
import os

import weave

from ...config import get_settings
from . import video

_VIDEO_EXTS = (".mp4", ".mov", ".webm", ".m4v", ".mkv")


@weave.op()
async def transcribe(data: bytes, filename: str = "audio") -> str:
    """Best available transcript of the audio in `data`, or '' if none is configured."""
    s = get_settings()
    if s.groq_enabled:
        try:
            text = await _groq(data, filename, s)
            if text:
                return text
        except Exception:
            pass  # fall through to Scribe / mock
    if s.transcription_enabled:
        try:
            from ..transcription import transcribe_media
            return await asyncio.to_thread(transcribe_media, data, filename or "pitch.mp4")
        except Exception:
            pass
    return ""


async def _groq(data: bytes, filename: str, s) -> str:
    from groq import AsyncGroq

    audio, name = data, (filename or "audio")
    if name.lower().endswith(_VIDEO_EXTS):
        flac = await asyncio.to_thread(video.extract_audio, data)
        if flac:
            audio, name = flac, "audio.flac"
    # Bound the call so a stalled Groq socket can't hang the extraction task / freeze
    # the progress stream; a TimeoutError is caught upstream and degrades to Scribe/mock.
    client = AsyncGroq(api_key=s.groq_api_key, timeout=120.0, max_retries=1)
    resp = await client.audio.transcriptions.create(
        file=(os.path.basename(name), audio), model=s.groq_model,
        response_format="text", temperature=0.0)
    return resp if isinstance(resp, str) else (getattr(resp, "text", "") or "")
