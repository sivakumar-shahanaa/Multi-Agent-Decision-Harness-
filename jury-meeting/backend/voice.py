"""ElevenLabs voice layer: TTS per juror, plus optional Scribe STT.

Audio is cached to backend/audio/ keyed by a hash of (voice_id, text), so
re-runs are instant and the API serves stable filenames.
"""
from __future__ import annotations

import hashlib
import io
import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

AUDIO_DIR = Path(__file__).parent / "audio"
AUDIO_DIR.mkdir(exist_ok=True)

TTS_MODEL = os.getenv("ELEVENLABS_TTS_MODEL", "eleven_flash_v2_5")
STT_MODEL = os.getenv("ELEVENLABS_STT_MODEL", "scribe_v1")

_client = None


def _get_client():
    global _client
    if _client is None:
        api_key = os.getenv("ELEVENLABS_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ELEVENLABS_API_KEY is not set. Add it to backend/.env "
                "(https://elevenlabs.io/app/settings/api-keys)."
            )
        from elevenlabs.client import ElevenLabs

        _client = ElevenLabs(api_key=api_key)
    return _client


def _cache_path(voice_id: str, text: str) -> Path:
    digest = hashlib.sha1(f"{voice_id}:{TTS_MODEL}:{text}".encode()).hexdigest()[:16]
    return AUDIO_DIR / f"{digest}.mp3"


def speak(text: str, voice_id: str) -> str:
    """Synthesize `text` with `voice_id`. Returns the cached mp3 filename.

    Returns an empty string if no API key is configured, so the rest of the
    pipeline still works text-only.
    """
    if not text.strip():
        return ""
    path = _cache_path(voice_id, text)
    if path.exists():
        return path.name
    try:
        client = _get_client()
    except RuntimeError:
        return ""  # no key -> text-only mode

    # Starter-tier ElevenLabs rate-limits rapid/concurrent calls (the 5 openings
    # fire back-to-back). Retry transient errors with backoff; give up fast on a
    # real quota cap (no point retrying) and degrade to text-only.
    for attempt in range(4):
        try:
            audio = client.text_to_speech.convert(
                text=text,
                voice_id=voice_id,
                model_id=TTS_MODEL,
                output_format="mp3_44100_128",
            )
            with open(path, "wb") as f:
                for chunk in audio:
                    if chunk:
                        f.write(chunk)
            return path.name
        except Exception as e:  # noqa: BLE001
            path.unlink(missing_ok=True)
            body = str(getattr(e, "body", "")) + str(e)
            if "quota_exceeded" in body:
                print("[voice] ElevenLabs per-key credit cap hit; text-only.")
                return ""
            if attempt < 3:
                time.sleep(1.5 * (attempt + 1))  # backoff on rate-limit/transient
                continue
            print(f"[voice] TTS failed ({type(e).__name__}); text-only.")
            return ""
    return ""


def transcribe(audio_bytes: bytes, filename: str = "question.webm") -> str:
    """Scribe STT for spoken applicant questions (mic input)."""
    client = _get_client()
    bio = io.BytesIO(audio_bytes)
    bio.name = filename  # the SDK uses the extension to sniff the format
    result = client.speech_to_text.convert(file=bio, model_id=STT_MODEL)
    return (getattr(result, "text", "") or "").strip()


def voice_turn(turn: dict) -> dict:
    """Attach an `audio` filename to a turn dict (mutates + returns it)."""
    turn["audio"] = speak(turn.get("text", ""), turn.get("voice_id", ""))
    return turn
