"""Transcribes class voice notes via the OpenAI Whisper API.

Entirely optional — reads OPENAI_API_KEY from environment. When unset,
class.transcript_status stays None and no transcription is attempted;
audio recording/playback works fine without this configured.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

WHISPER_URL = "https://api.openai.com/v1/audio/transcriptions"


def is_configured() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


async def transcribe(audio_bytes: bytes, content_type: str, filename: str) -> str:
    """Returns the transcript text, or raises on failure."""
    api_key = os.environ.get("OPENAI_API_KEY")
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            WHISPER_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": (filename, audio_bytes, content_type)},
            data={"model": "whisper-1"},
        )
        resp.raise_for_status()
        return resp.json()["text"]
