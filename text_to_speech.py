"""
text_to_speech.py
Deepgram Aura-2 TTS via REST — no SDK, no SpeakOptions.
Returns base64-encoded MP3.
"""

import base64
from typing import Optional
import httpx
import logger

log = logger.get("text_to_speech")

DEEPGRAM_TTS_URL = "https://api.deepgram.com/v1/speak"

PERSONA_VOICES: dict[str, str] = {
    "Marcus — Hostile Denier":     "aura-2-arcas-en",
    "Sara — Genuinely Struggling": "aura-2-thalia-en",
    "Steve — Legally Savvy":       "aura-2-orion-en",
    "Carol — Confused & Elderly":  "aura-2-luna-en",
}
# A neutral professional voice for the AI agent
AGENT_VOICE = "aura-2-orion-en"
DEFAULT_VOICE = "aura-2-thalia-en"


def synthesise(text: str, persona_key: str, api_key: str) -> Optional[str]:
    """Synthesise customer voice — voice matched to persona."""
    voice = PERSONA_VOICES.get(persona_key, DEFAULT_VOICE)
    return _call_tts(text, voice, api_key, label="customer")


def synthesise_agent(text: str, api_key: str) -> Optional[str]:
    """Synthesise agent voice — fixed professional voice."""
    return _call_tts(text, AGENT_VOICE, api_key, label="agent")


def _call_tts(text: str, voice: str, api_key: str, label: str = "") -> Optional[str]:
    log.info(f"TTS [{label}] voice={voice} — '{text[:60]}{'...' if len(text)>60 else ''}'")
    try:
        resp = httpx.post(
            DEEPGRAM_TTS_URL,
            params={"model": voice},
            headers={"Authorization": f"Token {api_key}", "Content-Type": "application/json"},
            json={"text": text},
            timeout=30,
        )
        resp.raise_for_status()
        b64 = base64.b64encode(resp.content).decode()
        log.info(f"TTS [{label}] success — {len(resp.content)} bytes audio")
        return b64
    except httpx.HTTPStatusError as e:
        log.error(f"TTS [{label}] HTTP {e.response.status_code}: {e.response.text[:200]}")
        return None
    except Exception as e:
        log.error(f"TTS [{label}] error: {e}")
        return None