"""One-off: generate the Decisive.ai pitch voiceover in a female ElevenLabs voice.

Uses the jury-meeting backend's own ELEVENLABS_API_KEY (backend/.env) and the
same audio/ cache dir.

Run from backend/:
    python gen_decisive_vo.py
Optional overrides:
    VO_VOICE=<voice_id> VO_MODEL=<model> python gen_decisive_vo.py
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent

# --- deps (self-heal if run outside the backend venv) ---
try:
    from dotenv import load_dotenv
    from elevenlabs.client import ElevenLabs
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "elevenlabs", "python-dotenv"])
    from dotenv import load_dotenv
    from elevenlabs.client import ElevenLabs

load_dotenv(HERE / ".env")

# eleven_multilingual_v2 is more expressive than the default flash model -> nicer VO.
MODEL = os.getenv("VO_MODEL", "eleven_multilingual_v2")
VOICE_ID = os.getenv("VO_VOICE", "EXAVITQu4vr4xnSDxMaL")  # Sarah (stock female)
OUT = HERE / "audio" / "decisive_pitch.mp3"

text = (HERE / "audio" / "decisive_pitch_script.txt").read_text().strip()

api_key = os.environ.get("ELEVENLABS_API_KEY")
if not api_key:
    sys.exit("ELEVENLABS_API_KEY missing from backend/.env")

client = ElevenLabs(api_key=api_key)
audio = client.text_to_speech.convert(
    text=text,
    voice_id=VOICE_ID,
    model_id=MODEL,
    output_format="mp3_44100_128",
    voice_settings={
        "stability": 0.45,
        "similarity_boost": 0.8,
        "style": 0.2,
        "use_speaker_boost": True,
    },
)
with open(OUT, "wb") as f:
    for chunk in audio:
        if chunk:
            f.write(chunk)

print(f"WROTE {OUT} ({OUT.stat().st_size:,} bytes)  voice={VOICE_ID}  model={MODEL}")
