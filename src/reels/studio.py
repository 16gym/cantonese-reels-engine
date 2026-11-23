"""Everything that costs money goes through here: quote, reserve, submit, collect.

Submitting returns at once. `collect` can be rerun any number of times, so a long
render never depends on one shell command staying alive.
"""
import re
import shutil
import subprocess
import time
from decimal import ROUND_UP, Decimal
from pathlib import Path

from . import checks, config, plan, prompts
from .episode import Episode, GateError, read_json, sha256, write_json
from .higgsfield import TERMINAL, MockProvider, ProviderError, make
from .ledger import Ledger, fmt

SIZES = {"3:4": (768, 1024), "9:16": (720, 1280), "16:9": (1280, 720), "1:1": (1024, 1024)}
DRAFT_LIFETIME = 6 * 24 * 3600  # Higgsfield keeps a draft finalizable for 7 days


def cents(value) -> str:
    return str(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_UP))


class Studio:
    def __init__(self, ep: Episode, provider=None):
        self.ep = ep
        self.mock = bool(ep.state.get("mock"))
        self.unit = ep.unit
        data = ep.root / ".data"
        self.ledger = Ledger(data / ("ledger-mock.sqlite" if self.mock else "ledger.sqlite"), self.unit)
        # An upload is a URL on REST and an id on the CLI, so each route keeps its own cache.
        self.uploads = data / ("uploads-mock.json" if self.mock else "uploads.json" if ep.provider == "rest" else f"uploads-{ep.provider}.json")
        self._provider = provider

    @property
    def provider(self):
        if self._provider is None:
            self._provider = MockProvider(self.unit) if self.mock else make(self.ep.provider, self.ep.root)
        return self._provider

    # ---- references -----------------------------------------------------------
    def url(self, relative: str) -> str:
        """Uploads a local file once and reuses the link while it is fresh."""
        path = self.ep.path(relative)
        if not path.is_file():
            raise GateError(f"Reference file is missing: {relative}")
        cache = read_json(self.uploads) if self.uploads.exists() else {}
        digest = sha256(path)
        hit = cache.get(digest)
        if hit and time.time() - hit["at"] < config.UPLOAD_TTL_HOURS * 3600:
            return hit["url"]
        cache[digest] = {"url": self.provider.upload(path), "at": time.time(), "file": relative}
        write_json(self.uploads, cache)
        return cache[digest]["url"]

    # ---- one job ----------------------------------------------------------------
    def start(self, bucket, label, kind, model, body, out: str, hint=None, quote=None) -> dict:
        quote = quote or self.provider.estimate(model, body, hint)
        job = self.ledger.reserve(self.ep.name, bucket, label, kind, model, body, quote, out)
        try:
            identity = self.provider.submit(model, body, job["idem"], {"label": label, **(hint or {})})
        except ProviderError as error:
            if error.unknown:
                self.ledger.unknown(job["id"])
            else:
                self.ledger.rejected(job["id"], str(error))
            raise
        self.ledger.accepted(job["id"], identity["request_id"], identity["status_url"])
        self.ep.log(f"submitted {label} ({bucket}, {self.ledger.show(job['quote_micro'])})")
        return job

    def collect(self, wait: int = 600) -> dict:
        """Polls every job in flight for this episode and downloads what finished."""
        deadline, delay, done, failed = time.time() + wait, 2, [], []
        while True:
            pending = self.ledger.jobs(self.ep.name, states=("queued", "in_progress", "completed"))
            pending = [j for j in pending if j["state"] != "completed" or not self.ep.path(j["out_path"]).exists()]
            for job in pending:
                status = self.provider.status(job["status_url"])
                if status["status"] == "completed" and status["outputs"]:
                    target = self.ep.path(job["out_path"])
                    if target.exists():  # a redo keeps the version it replaces, once
                        shutil.copyfile(target, target.with_name(target.stem + ".prev" + target.suffix))
                    self.provider.download(status["outputs"][0], target)
                    self.ledger.finish(job["id"], "completed", outputs=status["outputs"])
                    done.append(job["label"])
                elif status["status"] in TERMINAL and status["status"] != "completed":
                    self.ledger.finish(job["id"], status["status"], error=status["error"])
                    failed.append(f"{job['label']} ({status['status']}: {status['error'] or 'no reason given'})")
                elif status["status"] in ("queued", "in_progress"):
                    self.ledger.finish(job["id"], status["status"])
            still = [j["label"] for j in self.ledger.jobs(self.ep.name, states=("queued", "in_progress"))]
            if not still or time.time() + delay > deadline:
                unknown = [j["label"] for j in self.ledger.jobs(self.ep.name, states=("submission_unknown", "submitting"))]
                return {"done": done, "failed": failed, "still_running": still, "unknown": unknown}
            time.sleep(0 if self.mock else delay)
            delay = min(10, delay + 2)

    # ---- pictures ---------------------------------------------------------------
    def image(self, label: str, prompt: str, refs: list[str], out: str, aspect: str) -> dict:
        if len(refs) > config.IMAGE_MAX_REFS:
            raise GateError(f"{label}: {len(refs)} reference pictures, the image model takes {config.IMAGE_MAX_REFS}")
        body = {"prompt": prompt, "resolution": config.IMAGE_RESOLUTION, "aspect_ratio": aspect}
        if refs:
            body["image_urls"] = [self.url(r) for r in refs]
        job = self.start("prep", label, "image", config.IMAGE_EDIT if refs else config.IMAGE_T2I, body, out, hint={"size": SIZES[aspect]})
        write_json(self.ep.path(out).with_suffix(".request.json"), {"prompt": prompt, "references": refs, "aspect_ratio": aspect})
        return job

    def set_ref(self, kind: str, key: str, slot: str, path: str) -> None:
        """Points a bible entry at its picture. The path is fixed, so this is safe before the file arrives."""
        data = read_json(self.ep.path("bible.json"))
        entry = next(i for i in data[kind] if i["id"] == key)
        entry.setdefault("refs", {})[slot] = path
        write_json(self.ep.path("bible.json"), data)

    # ---- clips --------------------------------------------------------------------
    def voices(self, clip) -> tuple[dict, list[str]]:
        """Locked voice samples for the people who speak in a clip, on or off screen, in the order they first speak: ({character: audio number}, [paths]).
        Only speakers: a silent person's sample makes the model blend the two voices (seen on a real episode)."""
        speaker = {line.id: line.speaker for line in plan.story(self.ep).lines}
        numbers, paths = {}, []
        for name in dict.fromkeys(speaker[key] for s in clip.shots for key in s.lines if key in speaker):
            sample = f"bible/characters/{name}/voice.wav"
            if self.ep.exists(sample):
                paths.append(sample)
                numbers[name] = len(paths)
        return numbers, paths

    def clip_request(self, clip_id: str) -> tuple[dict, dict]:
        """The exact request for one clip, and a readable record of what went into it."""
        story, bible, shots = plan.story(self.ep), plan.bible(self.ep), plan.shots(self.ep)
        clip = shots.clip(clip_id)
        refs = checks.clip_refs(bible, clip)
        numbers, samples = self.voices(clip)
        corrections = (read_json(self.ep.path("retakes.json")) if self.ep.exists("retakes.json") else {}).get(clip_id, [])
        prompt = prompts.clip_prompt(story, bible, clip, numbers, corrections)
        body = {"prompt": prompt, "image_urls": [self.url(path) for _, path in refs], "duration": clip.duration,
                "aspect_ratio": config.ASPECT, "generate_audio": True, "draft": True}
        if self.hd_takes:
            body.update(draft=False, resolution="720p")
        if samples:
            body["audio_urls"] = [self.url(s) for s in samples]
        record = {"prompt": prompt, "images": [{"number": i, "role": role, "file": path} for i, (role, path) in enumerate(refs, 1)],
                  "audio": samples, "duration": clip.duration, "corrections": corrections}
        return body, record

    def next_take(self, clip_id: str) -> int:
        # Counted from what was actually submitted, so a refused submission leaves no gap.
        labels = [j["label"] for j in self.ledger.jobs(self.ep.name)]
        return max((int(m.group(1)) for l in labels if (m := re.fullmatch(rf"{clip_id}/t(\d+)", l))), default=0) + 1

    def shoot(self, clip_id: str) -> dict:
        self.ep.require("angles")
        take = self.next_take(clip_id)
        body, record = self.clip_request(clip_id)
        job = self.start("draft", f"{clip_id}/t{take}", "video", config.VIDEO, body, f"takes/{clip_id}/t{take}.mp4", hint={"duration": body["duration"]})
        write_json(self.ep.path("takes", clip_id, f"t{take}.request.json"), record)
        return job

    @property
    def hd_takes(self) -> bool:
        return self.ep.state.get("quality") == "720p"

    def finalize(self, clip_id: str) -> dict:
        self.ep.require("takes")
        take = checks.selection(self.ep)[clip_id]
        if self.hd_takes:  # the picked 720p take is the final: copy it with its QA verdict, spend nothing
            source, target = self.ep.path("takes", clip_id, f"t{take}.mp4"), self.ep.path("finals", f"{clip_id}.mp4")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            if source.with_suffix(".qa.json").exists():
                shutil.copy2(source.with_suffix(".qa.json"), target.with_suffix(".qa.json"))
            return {"label": f"{clip_id}/final (the 720p take, no charge)"}
        draft = next((j for j in reversed(self.ledger.jobs(self.ep.name, states=("completed",))) if j["label"] == f"{clip_id}/t{take}"), None)
        if draft is None:
            raise GateError(f"{clip_id}: cannot find the completed draft job for take {take}")
        if time.time() - draft["created"] > DRAFT_LIFETIME:
            raise GateError(f"{clip_id}: take {take} is older than 6 days and can no longer be finalized. Shoot a new take.")
        quote = self.provider.estimate(config.VIDEO, {**draft["body"], "draft": False, "resolution": "1080p"})
        return self.start("final", f"{clip_id}/final", "video", config.VIDEO_FINALIZE, {"draft_id": draft["request_id"], "resolution": "1080p"},
                          f"finals/{clip_id}.mp4", hint={"duration": draft["body"]["duration"], "size": list(config.FINAL_SIZE), "source_body": draft["body"]}, quote=quote)

    # ---- quotes -------------------------------------------------------------------
    def quote(self, bucket: str, takes: int = config.DEFAULT_TAKES) -> dict:
        """Works out what a stage will cost and saves it for the user to approve."""
        if bucket == "prep":
            story = plan.story(self.ep)
            base = Decimal(checks.plan_cost(sum(b.seconds for b in story.beats), len(story.characters), len(story.locations), len(story.props),
                                            quality=self.ep.state.get("quality", "1080p"), unit=self.unit)["prep"])
            quote = {"bucket": bucket, "unit": self.unit, "base": cents(base), "cap": cents(base), "basis": "planning estimate: pictures for casting, sheets and anchor frames, plus voice tests", "inputs": sha256(self.ep.path("story.json"))}
        elif bucket == "draft":
            # Quoted before the angles gate is approved, so the user sees the angles and their price together.
            self.ep.require("lock")
            if not (report := checks.check_shots(self.ep)).ok:
                raise GateError("shots.json or its anchor frames are not ready: " + "; ".join(report.errors[:3]))
            shots = plan.shots(self.ep)
            per_clip = {c.id: Decimal(self.provider.estimate(config.VIDEO, self.clip_request(c.id)[0])) for c in shots.clips}
            base = sum(per_clip.values()) * takes
            quote = {"bucket": bucket, "unit": self.unit, "takes": takes, "per_take": {k: cents(v) for k, v in per_clip.items()}, "base": cents(base),
                     "cap": cents(base * (1 + config.RETAKE_ALLOWANCE)), "basis": f"{'720p takes' if self.hd_takes else '480p drafts'}, {takes} takes per clip, plus {config.RETAKE_ALLOWANCE:.0%} for retakes", "inputs": sha256(self.ep.path("shots.json"))}
        elif bucket == "final":
            self.ep.require("takes")
            picks = checks.selection(self.ep)
            jobs = {j["label"]: j for j in self.ledger.jobs(self.ep.name, states=("completed",))}
            per_clip = {c: Decimal(self.provider.estimate(config.VIDEO, {**jobs[f"{c}/t{t}"]["body"], "draft": False, "resolution": "1080p"})) for c, t in picks.items()}
            base = sum(per_clip.values())
            quote = {"bucket": bucket, "unit": self.unit, "per_clip": {k: cents(v) for k, v in per_clip.items()}, "base": cents(base), "cap": cents(base),
                     "basis": "1080p versions of the picked takes, one each, no retake allowance", "inputs": sha256(self.ep.path("takes", "selection.json"))}
        else:
            raise GateError("Quote one of: prep, draft, final")
        write_json(self.ep.path("money", f"{bucket}.json"), quote)
        return quote

    def approve_money(self, bucket: str, text: str, cap: str | None = None) -> dict:
        if cap is not None:  # the user named the ceiling themselves; there is no quote to match
            self.ledger.approve(self.ep.name, bucket, cap, text)
            self.ep.log(f"money '{bucket}' ceiling set to {fmt(cap, self.unit)} by the user: 「{text.strip()}」")
            return {"cap": cap, "unit": self.unit}
        path = self.ep.path("money", f"{bucket}.json")
        if not path.exists():
            raise GateError(f"No {bucket} quote yet. Run: reels quote {self.ep.name} {bucket}")
        quote = read_json(path)
        source = {"prep": "story.json", "draft": "shots.json", "final": "takes/selection.json"}[bucket]
        if sha256(self.ep.path(source)) != quote["inputs"]:
            raise GateError(f"{source} changed after the {bucket} quote was made. Quote again and show the user the new number.")
        if quote.get("unit", "US$") != self.unit:
            raise GateError(f"The {bucket} quote is in {quote.get('unit', 'US$')} but this episode spends {self.unit}. Quote again.")
        self.ledger.approve(self.ep.name, bucket, quote["cap"], text, base=quote["base"])
        self.ep.log(f"money '{bucket}' approved up to {fmt(quote['cap'], self.unit)} by the user: 「{text.strip()}」")
        return quote


def cut_wav(source: Path, target: Path, start: float, end: float) -> None:
    """A clean voice sample from a take the user approved. ByteDance documents 2 to 30 seconds per sample."""
    if not 2 <= end - start <= 30:
        raise GateError("A voice sample must be 2 to 30 seconds long")
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-to", str(end), "-i", str(source), "-vn", "-ac", "1", "-ar", "44100", str(target)], check=True)
