"""Three ways to reach Higgsfield, one interface (estimate, upload, submit, status, download):

- CliProvider: the official `higgsfield` CLI, logged in by the user. Spends plan credits. Default.
- RestProvider: the pay-as-you-go Model API with a key in .env. Proven live on a full episode.
- MockProvider: free offline stand-in for rehearsals and tests.

Transport rules carried over from the first engine, where they were proven live:
keys go only to their own host, uploads and downloads are unsigned,
submissions carry an idempotency key, and a paid call is never retried automatically.
"""
import base64
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from . import config

CONTENT_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".wav": "audio/wav", ".mp4": "video/mp4"}
TERMINAL = ("completed", "failed", "nsfw", "canceled")


class ProviderError(RuntimeError):
    """The provider call failed. `unknown` means a submission may still have gone through."""

    def __init__(self, message, *, unknown=False):
        super().__init__(message)
        self.unknown = unknown


def load_key(root: Path) -> str:
    """Reads HF_API_KEY_ID + HF_API_KEY_SECRET (or HF_CREDENTIALS) from the repo's .env. Never printed."""
    values = {}
    path = Path(root) / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            name, separator, value = line.strip().partition("=")
            if separator and not name.startswith("#"):
                values[name.strip()] = value.strip().strip("\"'")
    for name in ("HF_API_KEY_ID", "HF_API_KEY_SECRET", "HF_CREDENTIALS"):
        if os.environ.get(name):
            values[name] = os.environ[name].strip()
    key = values.get("HF_CREDENTIALS") or ":".join(filter(None, (values.get("HF_API_KEY_ID"), values.get("HF_API_KEY_SECRET"))))
    if len(key.split(":")) != 2 or not all(key.split(":")) or re.search(r"\s", key):
        raise ProviderError("Higgsfield key missing. Put HF_API_KEY_ID and HF_API_KEY_SECRET in .env (see .env.example). Never paste keys into chat.")
    return key


def asset_url(value) -> str:
    url = urlsplit(value if isinstance(value, str) else "")
    host = url.hostname or ""
    known = host in config.ASSET_HOSTS or any(host == d or host.endswith("." + d) for d in config.ASSET_DOMAINS)
    if url.scheme != "https" or url.username or url.port not in (None, 443):
        raise ProviderError("Provider returned an unsafe media URL")
    if not known:
        raise ProviderError(f"Provider returned media on a host we have not seen before: {host}. If it is Higgsfield's, add it to ASSET_HOSTS in src/reels/config.py and rerun: reels collect")
    return value


def price(result: dict, body: dict) -> str:
    """The estimate endpoint answers either an exact amount or a per-second rate card."""
    if isinstance(result.get("usd"), (str, int, float)):
        return str(result["usd"])
    text = " ".join(str(result.get("pricing_description") or "").split())
    resolution = "480p" if body.get("draft") else body.get("resolution", "720p")
    section = text
    if "- With video input:" in text:
        without, _, with_video = text.partition("- With video input:")
        section = with_video if body.get("video_urls") else without
    rate = re.search(rf"(?<![\w.]){re.escape(str(resolution))}: \$([0-9]+(?:\.[0-9]+)?)", section, re.IGNORECASE)
    if rate:
        from decimal import Decimal
        return str(Decimal(rate.group(1)) * (body.get("duration", 5) if "second" in text else 1))
    raise ProviderError(f"Estimate gave no exact price. Raw answer: {json.dumps(result, ensure_ascii=False)[:400]}")


def download(client: httpx.Client, url: str, target: Path) -> None:
    """Unsigned GET of a provider media URL into target, atomically."""
    asset_url(url)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(uuid.uuid4().hex + ".part")
    try:
        with client.stream("GET", url) as response:
            if response.status_code != 200:
                raise ProviderError(f"Download failed: HTTP {response.status_code}")
            with temporary.open("wb") as stream:
                for chunk in response.iter_bytes():
                    stream.write(chunk)
        if not temporary.stat().st_size:
            raise ProviderError("Downloaded file is empty")
        temporary.replace(target)
    except httpx.TransportError:
        raise ProviderError("Download interrupted. Rerun: reels collect") from None
    finally:
        temporary.unlink(missing_ok=True)


def make(provider: str, root: Path):
    """The live provider an episode was created with."""
    return CliProvider() if provider == "cli" else RestProvider(load_key(root))


# ---- the official Higgsfield CLI -----------------------------------------------------------
DONE = {"completed", "complete", "succeeded", "success", "done", "finished"}
FAILED = {"failed", "error", "errored", "nsfw", "canceled", "cancelled", "rejected", "moderated"}
NOT_MEDIA = ("thumbnail", "min_", "preview", "avatar", "cover", "logo", "favicon", "screenshot", "upload")


def cli_path() -> str:
    """The CLI binary. npm on Windows installs a .cmd shim that would pass prompts through cmd.exe
    (which mangles quotes and %), so the real binary next to it is used instead."""
    override = config.env_value("REELS_HIGGSFIELD_BIN")
    found = override or shutil.which("higgsfield") or shutil.which("hf")
    if not found:
        raise ProviderError("The Higgsfield CLI is not installed. Install it (npm install -g @higgsfield/cli), then run: higgsfield auth login")
    if found.lower().endswith((".cmd", ".ps1", ".bat")) or (os.name == "nt" and not Path(found).suffix):
        vendor = Path(found).parent / "node_modules" / "@higgsfield" / "cli" / "vendor" / "hf.exe"
        if vendor.is_file():
            return str(vendor)
    return found


def cli_request(model: str, body: dict, hint: dict | None = None) -> tuple[str, list[str]]:
    """Turns the engine's request (REST shape) into a CLI job type and its arguments."""
    hint = hint or {}
    args: list[str] = []

    def param(name, value):
        if value is not None:
            args.extend([f"--{name}", str(value).lower() if isinstance(value, bool) else str(value)])

    if model in (config.IMAGE_T2I, config.IMAGE_EDIT):
        job = config.CLI_IMAGE
        for name in ("prompt", "aspect_ratio", "resolution"):
            param(name, body.get(name))
        for ref in body.get("image_urls", []):
            param("image-references", ref)
        return job, args
    if model == config.VIDEO_FINALIZE:  # same request as the draft, rendered again from it at full size
        source = dict(hint.get("source_body") or {})
        if not source:
            raise ProviderError("Finalizing through the CLI needs the draft's original request")
        source.update(draft=False, resolution=body.get("resolution", "1080p"))
        job, args = cli_request(config.VIDEO, source)
        param("draft_job_id", body["draft_id"])
        return job, args
    if model in (config.VIDEO, config.VIDEO_TEXT):
        refs = body.get("image_urls", []) + body.get("audio_urls", [])
        param("mode", "omni_reference" if refs else "t2v")
        for name in ("prompt", "duration", "aspect_ratio", "generate_audio"):
            param(name, body.get(name))
        if body.get("draft"):
            param("draft", True)
            param("resolution", "480p")
        else:
            param("resolution", body.get("resolution", "720p"))
        for ref in body.get("image_urls", []):
            param("image-references", ref)
        for ref in body.get("audio_urls", []):
            param("audio-references", ref)
        return config.CLI_VIDEO, args
    raise ProviderError(f"No CLI route for {model}")


def _media_urls(data, key: str = "") -> list[str]:
    """Every result URL in a job record, video files first. Thumbnails and previews are skipped."""
    found = []
    if isinstance(data, dict):
        for name, value in data.items():
            if not any(word in name.lower() for word in NOT_MEDIA):
                found += _media_urls(value, name)
    elif isinstance(data, list):
        for value in data:
            found += _media_urls(value, key)
    elif isinstance(data, str) and data.startswith("https://") and any(word in key.lower() for word in ("url", "result", "media", "video", "image", "output")):
        found.append(data)
    found = list(dict.fromkeys(found))
    return sorted(found, key=lambda url: 0 if urlsplit(url).path.lower().endswith((".mp4", ".mov")) else 1)


def _job_id(data) -> str | None:
    if isinstance(data, list):
        return next((i for i in map(_job_id, data) if i), None)
    if isinstance(data, dict):
        for name in ("job_id", "id"):
            if isinstance(data.get(name), str) and data[name]:
                return data[name]
        for name in ("jobs", "job", "data", "result", "results"):
            if data.get(name) is not None and (found := _job_id(data[name])):
                return found
    return None


def _status(data) -> str:
    if isinstance(data, list):
        data = data[0] if data else {}
    for name in ("status", "job_status", "state"):
        value = data.get(name) if isinstance(data, dict) else None
        if isinstance(value, str):
            return value.lower()
    for name in ("jobs", "job", "data"):
        if isinstance(data, dict) and data.get(name) is not None:
            return _status(data[name])
    return ""


class CliProvider:
    """Higgsfield's official CLI. The user logs in once (`higgsfield auth login`, a browser click);
    the engine never sees a password or key. Amounts are plan credits."""
    mock = False

    def __init__(self, run=None, *, transport=None):
        self._run = run
        self.client = httpx.Client(transport=transport, timeout=120, follow_redirects=False, trust_env=False)

    def cli(self, *args: str, spend: bool = False, timeout: int = 300):
        if self._run:
            code, out, err = self._run(list(args))
        else:
            try:
                result = subprocess.run([cli_path(), *args, "--json", "--no-color"], capture_output=True, text=True,
                                        encoding="utf-8", errors="replace", timeout=timeout)
            except subprocess.TimeoutExpired:
                raise ProviderError("The Higgsfield CLI did not answer in time", unknown=spend) from None
            code, out, err = result.returncode, result.stdout, result.stderr
        text = (err or "") + (out or "")
        if code != 0:
            raise self._error(text, spend)
        try:
            return json.loads(out)
        except ValueError:
            raise ProviderError(f"The Higgsfield CLI answered with something that is not JSON: {out[:200]}", unknown=spend) from None

    @staticmethod
    def _error(text: str, spend: bool) -> ProviderError:
        lowered = text.lower()
        if any(word in lowered for word in ("not authenticated", "session expired", "not logged in", "unauthorized", "login required", "401")):
            return ProviderError("Not logged in to Higgsfield. Run: higgsfield auth login  (it opens a browser; on a remote machine see README, 'Logging in from another device')")
        if "no workspace selected" in lowered:
            return ProviderError("No Higgsfield workspace selected. Run: higgsfield workspace list, then: higgsfield workspace set <id>")
        if "plan_required" in lowered or "upgrade" in lowered:
            return ProviderError("This Higgsfield plan cannot run this job through the CLI. Seedance 2.5 needs Plus or above. Nothing was charged.")
        if "insufficient" in lowered or "not enough credits" in lowered or "balance" in lowered:
            return ProviderError("Not enough Higgsfield credits for this job. Nothing was charged. Ask the user to top up or wait for the monthly refresh.")
        refused = '"error_type"' in text or "error:" in lowered
        return ProviderError(f"Higgsfield CLI: {text.strip()[:400]}", unknown=spend and not refused)

    def account(self) -> dict:
        return self.cli("account", "status")

    def estimate(self, model: str, body: dict, hint=None) -> str:
        job, args = cli_request(model, body, hint)
        result = self.cli("generate", "cost", job, *args)
        if not isinstance(result, dict) or result.get("credits") is None:
            raise ProviderError(f"Estimate gave no credit amount: {json.dumps(result)[:300]}")
        return str(result["credits"])

    def upload(self, path: Path) -> str:
        result = self.cli("upload", "create", str(Path(path).resolve()))
        if not isinstance(result, dict) or not result.get("id"):
            raise ProviderError(f"Upload of {Path(path).name} returned no id")
        return result["id"]

    def submit(self, model: str, body: dict, idem: str, hint=None) -> dict:
        job, args = cli_request(model, body, hint)
        result = self.cli("generate", "create", job, *args, spend=True)
        job_id = _job_id(result)
        if not job_id:
            raise ProviderError(f"Higgsfield accepted the job but returned no id: {json.dumps(result)[:300]}", unknown=True)
        return {"request_id": job_id, "status_url": f"higgsfield-cli:{job_id}"}

    def status(self, status_url: str) -> dict:
        job_id = status_url.split(":", 1)[1]
        result = self.cli("generate", "get", job_id)
        state = _status(result)
        if state in DONE:
            outputs = [asset_url(u) for u in _media_urls(result)]
            return {"status": "completed" if outputs else "in_progress", "outputs": outputs, "error": None}
        if state in FAILED:
            reason = result.get("error") or result.get("error_description") if isinstance(result, dict) else None
            return {"status": "nsfw" if state in ("nsfw", "moderated") else "failed", "outputs": [], "error": reason or state}
        return {"status": "in_progress", "outputs": [], "error": None}

    def download(self, url: str, target: Path) -> None:
        download(self.client, url, target)


# ---- the pay-as-you-go REST API ----------------------------------------------------------------
class RestProvider:
    mock = False

    def __init__(self, key: str, *, transport=None, sleep=time.sleep):
        self.key, self.sleep = key, sleep
        # No default auth header: storage and CDN requests must stay unsigned.
        self.client = httpx.Client(transport=transport, timeout=60, follow_redirects=False, trust_env=False)

    def _api(self, method, url, *, body=None, headers=None):
        if urlsplit(url).hostname != "api.higgsfield.ai" or not url.startswith("https://"):
            raise ProviderError("Refusing to send the API key anywhere but api.higgsfield.ai")
        attempts = 3 if method == "GET" else 1  # never auto-retry something that could spend money
        for attempt in range(attempts):
            try:
                response = self.client.request(method, url, json=body, headers={"Authorization": f"Key {self.key}", **(headers or {})})
            except httpx.TransportError:
                if attempt + 1 < attempts:
                    self.sleep(2 ** attempt)
                    continue
                raise ProviderError("Could not reach Higgsfield", unknown=method != "GET") from None
            if response.status_code in (429, 500, 502, 503, 504) and attempt + 1 < attempts:
                self.sleep(2 ** attempt)
                continue
            if not 200 <= response.status_code < 300:
                # 4xx = the request itself was refused, nothing ran. 5xx on a POST = outcome unknown.
                detail = response.text[:400].replace(self.key, "<key>")
                raise ProviderError(f"Higgsfield HTTP {response.status_code}: {detail}", unknown=method != "GET" and response.status_code >= 500)
            try:
                return response.json()
            except ValueError:
                raise ProviderError("Higgsfield answered with something that is not JSON", unknown=method != "GET") from None

    def estimate(self, model: str, body: dict, hint=None) -> str:
        return price(self._api("POST", f"{config.API}/estimate/{model}", body=body), body)

    def upload(self, path: Path) -> str:
        content_type = CONTENT_TYPES.get(path.suffix.lower())
        if not content_type:
            raise ProviderError(f"Cannot upload {path.name}: use png, jpg, webp, wav or mp4")
        slot = self._api("POST", f"{config.API}/files/generate-upload-url", body={"content_type": content_type})
        headers = slot.get("upload_headers") or {}
        if any(k.lower() in ("authorization", "cookie", "host") for k in headers):
            raise ProviderError("Unexpected signed-upload headers")
        with path.open("rb") as stream:
            response = self.client.put(slot["upload_url"], headers=headers, content=stream.read())
        if not 200 <= response.status_code < 300:
            raise ProviderError(f"Upload of {path.name} failed: HTTP {response.status_code}")
        return asset_url(slot["public_url"])

    def submit(self, model: str, body: dict, idem: str, hint=None) -> dict:
        result = self._api("POST", f"{config.API}/{model}", body=body, headers={"Idempotency-Key": idem})
        if not result.get("request_id") or not str(result.get("status_url", "")).startswith(config.API):
            raise ProviderError("Higgsfield accepted the call but returned no request id", unknown=True)
        return {"request_id": result["request_id"], "status_url": result["status_url"]}

    def status(self, status_url: str) -> dict:
        result = self._api("GET", status_url)
        files = result.get("images") or ([result["video"]] if result.get("video") else [])
        return {"status": result.get("status"), "outputs": [asset_url(f["url"]) for f in files if isinstance(f, dict) and f.get("url")], "error": result.get("error")}

    def download(self, url: str, target: Path) -> None:
        download(self.client, url, target)


class MockProvider:
    """Free rehearsal: same interface, placeholder pictures and clips stamped MOCK, plausible prices.

    Stateless on purpose (everything needed rides in the fake URLs) because each CLI
    command is its own process.
    """
    mock = True

    def __init__(self, unit: str = "credits"):
        self.plan = config.PLAN[unit]

    @staticmethod
    def _pack(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode()

    @staticmethod
    def _unpack(url: str) -> dict:
        return json.loads(base64.urlsafe_b64decode(url.rsplit("/", 1)[1]))

    def estimate(self, model, body, hint=None) -> str:
        if "video" in model or "draft" in model:
            rate = self.plan["draft_per_second"] if body.get("draft") else self.plan["final_per_second"]
            return str(rate * body.get("duration", 5))
        return str(self.plan["image"])

    def upload(self, path: Path) -> str:
        return f"mock://upload/{self._pack({'name': Path(path).name})}"

    def submit(self, model, body, idem, hint=None) -> dict:
        hint = hint or {}
        video = "video" in model or "draft" in model
        data = {"video": video, "label": hint.get("label", model.split("/")[-1]), "duration": hint.get("duration", body.get("duration", 5)),
                "size": hint.get("size") or ([480, 854] if body.get("draft") else [1080, 1920])}
        return {"request_id": str(uuid.uuid4()), "status_url": f"mock://status/{self._pack(data)}"}

    def status(self, status_url) -> dict:
        return {"status": "completed", "outputs": [status_url.replace("mock://status/", "mock://media/")], "error": None}

    def download(self, url, target: Path) -> None:
        data = self._unpack(url)
        target.parent.mkdir(parents=True, exist_ok=True)
        width, height = data["size"]
        if data["video"]:
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={width}x{height}:rate=24:duration={data['duration']}",
                            "-f", "lavfi", "-i", f"sine=frequency=330:duration={data['duration']}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(target)], check=True)
            return
        from PIL import Image, ImageDraw, ImageFont
        image = Image.new("RGB", (width, height), (58, 66, 74))
        draw = ImageDraw.Draw(image)
        path = config.font(bold=True)
        typeface = ImageFont.truetype(path, max(24, width // 16)) if path else ImageFont.load_default()
        draw.multiline_text((width // 14, height // 3), "MOCK\n" + data["label"].replace("/", "\n"), fill=(240, 240, 240), font=typeface, spacing=12)
        image.save(target)
