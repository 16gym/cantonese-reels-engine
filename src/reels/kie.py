"""Kie AI, for one job only: 4K upscale of the finished clips (Higgsfield does everything else).

The key is KIE_API_KEY in .env and only ever goes to api.kie.ai. Kie answers errors as HTTP 200
with its own `code`, so the code field is what counts. Task ids are saved the moment Kie returns
them: a lost id means a paid job nobody can collect.
"""
import json
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from . import config
from .higgsfield import ProviderError


def load_key() -> str:
    key = config.env_value("KIE_API_KEY")
    if not key:
        raise ProviderError("Kie key missing. The user puts KIE_API_KEY=<their key> in .env (see .env.example). Never paste keys into chat.")
    return key


class Kie:
    def __init__(self, key: str, *, transport=None):
        self.key = key
        self.client = httpx.Client(transport=transport, timeout=120, follow_redirects=False, trust_env=False)

    def _call(self, method: str, path: str, body=None, *, spend=False):
        url = f"{config.KIE_API}/{path}"
        if urlsplit(url).hostname != "api.kie.ai":
            raise ProviderError("Refusing to send the Kie key anywhere but api.kie.ai")
        try:
            response = self.client.request(method, url, json=body, headers={"Authorization": f"Bearer {self.key}"})
            answer = response.json()
        except (httpx.TransportError, ValueError):
            raise ProviderError("Could not reach Kie", unknown=spend) from None
        if answer.get("code") != 200:
            detail = str(answer.get("msg") or answer)[:300].replace(self.key, "<key>")
            if answer.get("code") == 402:
                detail += " (Kie balance too low: the user tops up at kie.ai)"
            raise ProviderError(f"Kie said {answer.get('code')}: {detail}", unknown=spend and (answer.get("code") or 0) >= 500)
        return answer.get("data")

    def credits(self):
        return self._call("GET", "chat/credit")

    def submit(self, video_url: str) -> str:
        data = self._call("POST", "jobs/createTask", {"model": config.KIE_UPSCALE_MODEL, "input": {"video_url": video_url, "resolution": "4K"}}, spend=True)
        if not data or not data.get("taskId"):
            raise ProviderError("Kie accepted the job but returned no task id", unknown=True)
        return data["taskId"]

    def status(self, task_id: str) -> dict:
        data = self._call("GET", f"jobs/recordInfo?taskId={task_id}") or {}
        state = str(data.get("state", "")).lower()
        if state == "success":
            urls = json.loads(data.get("resultJson") or "{}").get("resultUrls") or []
            return {"state": "done", "url": urls[0] if urls else None, "error": None if urls else "no result URL"}
        if state == "fail":
            return {"state": "failed", "url": None, "error": f"{data.get('failCode')}: {data.get('failMsg')}"}
        return {"state": "running", "url": None, "error": None}

    def download(self, url: str, target: Path) -> None:
        if urlsplit(url).scheme != "https":
            raise ProviderError("Kie returned a non-https result URL")
        target.parent.mkdir(parents=True, exist_ok=True)
        with self.client.stream("GET", url) as response:
            if response.status_code != 200:
                raise ProviderError(f"Download of the upscaled clip failed: HTTP {response.status_code}")
            with target.with_suffix(".part").open("wb") as stream:
                for chunk in response.iter_bytes():
                    stream.write(chunk)
        target.with_suffix(".part").replace(target)

