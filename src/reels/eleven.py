"""ElevenLabs, for one job only: read a character's lines in the user's own ElevenLabs voice.

The recording becomes the voice sample every clip carries (`voice-lock --eleven`). Seedance still
speaks the lines in the film; the sample only tells it whose voice to use. The key is
ELEVENLABS_API_KEY in .env and only ever goes to api.elevenlabs.io.
"""
import re
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from . import config
from .higgsfield import ProviderError


def speak(voice_id: str, text: str, target: Path, *, transport=None) -> None:
    key = config.env_value("ELEVENLABS_API_KEY")
    if not key:
        raise ProviderError("ElevenLabs key missing. The user puts ELEVENLABS_API_KEY=<their key> in .env "
                            "(the key needs the Text to Speech permission). Never paste keys into chat.")
    if not re.fullmatch(r"[A-Za-z0-9]{10,40}", voice_id):
        raise ProviderError(f"'{voice_id}' does not look like an ElevenLabs voice id (Voices → the voice → ID)")
    url = f"{config.ELEVENLABS_API}/text-to-speech/{voice_id}"
    if urlsplit(url).hostname != "api.elevenlabs.io":
        raise ProviderError("Refusing to send the ElevenLabs key anywhere but api.elevenlabs.io")
    body = {"text": text, "model_id": config.env_value("ELEVENLABS_MODEL") or config.ELEVENLABS_MODEL,
            "language_code": "yue", "apply_text_normalization": "off"}
    try:
        with httpx.Client(transport=transport, timeout=120, follow_redirects=False, trust_env=False) as client:
            response = client.post(url, params={"output_format": "mp3_44100_128"}, json=body,
                                   headers={"xi-api-key": key, "accept": "audio/mpeg"})
    except httpx.TransportError:
        raise ProviderError("Could not reach ElevenLabs") from None
    if response.status_code != 200:
        detail = response.text[:300].replace(key, "<key>")
        if "missing_permissions" in detail:
            detail += " (the key needs the Text to Speech permission: elevenlabs.io → Developers → API keys)"
        raise ProviderError(f"ElevenLabs said HTTP {response.status_code}: {detail}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(response.content)
