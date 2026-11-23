import json
import subprocess

import httpx
import pytest

from reels import cli, eleven, plan
from reels.higgsfield import ProviderError

VOICE = "abcdEFGH1234ijkl5678"


def test_speak_sends_the_line_in_the_users_voice(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k-secret")
    seen = {}

    def handler(request):
        seen.update(host=request.url.host, path=request.url.path, key=request.headers["xi-api-key"], body=json.loads(request.content))
        return httpx.Response(200, content=b"ID3fake")

    eleven.speak(VOICE, "八五折嘅旗", tmp_path / "v.mp3", transport=httpx.MockTransport(handler))
    assert (tmp_path / "v.mp3").read_bytes() == b"ID3fake"
    assert seen["host"] == "api.elevenlabs.io" and seen["path"].endswith(VOICE) and seen["key"] == "k-secret"
    assert seen["body"]["text"] == "八五折嘅旗" and seen["body"]["language_code"] == "yue"

    refused = httpx.MockTransport(lambda r: httpx.Response(401, json={"detail": {"status": "missing_permissions", "message": "k-secret lacks text_to_speech"}}))
    with pytest.raises(ProviderError) as error:
        eleven.speak(VOICE, "x", tmp_path / "w.mp3", transport=refused)
    assert "Text to Speech permission" in str(error.value) and "k-secret" not in str(error.value)


def test_voice_lock_reads_the_characters_lines_through_elevenlabs(ep, monkeypatch):
    said = {}

    def fake_speak(voice_id, text, target):
        said.update(voice=voice_id, text=text)
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=d=4", str(target)], check=True)

    monkeypatch.setattr(eleven, "speak", fake_speak)
    character = plan.story(ep).lines[0].speaker
    cli.voice_lock(ep.name, character, 0, file="", eleven=VOICE, start=-1.0, end=-1.0)
    assert said["voice"] == VOICE and plan.story(ep).lines[0].text in said["text"]
    assert ep.path("bible", "characters", character, "voice.wav").is_file()
