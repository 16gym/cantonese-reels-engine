"""One episode = one folder. All state lives in files, never in chat or AGENTS.md.

A gate approval freezes the hashes of that gate's files. If a frozen file changes
later, the gate goes stale and everything downstream refuses to run until the user
re-approves. That refusal is the lock.
"""
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

GATES = ("story", "lock", "angles", "takes", "final")
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class GateError(RuntimeError):
    """A rule of the flow was broken. The message says what to do next."""


def repo_root() -> Path:
    return Path(os.environ.get("REELS_ROOT") or Path(__file__).resolve().parents[2])


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


class Episode:
    def __init__(self, name: str, root: Path | None = None):
        if not NAME.fullmatch(name):
            raise GateError("Episode name: lowercase letters, digits and hyphens only, e.g. lock-test")
        self.name = name
        self.root = Path(root or repo_root())
        self.dir = self.root / "episodes" / name

    def path(self, *parts: str) -> Path:
        return self.dir.joinpath(*parts)

    def exists(self, relative: str) -> bool:
        return bool(relative) and self.path(relative).is_file()

    # ---- state -------------------------------------------------------------
    @property
    def state(self) -> dict:
        path = self.path("state.json")
        if not path.exists():
            raise GateError(f"Episode '{self.name}' does not exist. Run: reels new {self.name}")
        return read_json(path)

    @property
    def provider(self) -> str:
        return self.state.get("provider", "rest")  # episodes made before the CLI route used REST

    @property
    def unit(self) -> str:
        from .config import UNITS
        return UNITS[self.provider]

    def create(self, brief: str = "", mock: bool = False, quality: str = "1080p", provider: str = "cli") -> None:
        if self.path("state.json").exists():
            raise GateError(f"Episode '{self.name}' already exists")
        if quality not in ("720p", "1080p"):
            raise GateError("quality is 720p or 1080p")
        # 720p: takes are shot at 720p and the picked take is the final. No 480p draft, no 1080p pass.
        write_json(self.path("state.json"), {"episode": self.name, "created": now(), "mock": mock, "quality": quality, "provider": provider,
                                             "gates": {g: {"status": "open"} for g in GATES}})
        self.path("brief.md").write_text(brief.strip() + "\n", encoding="utf-8")
        self.log(f"episode created. Brief: {brief.strip() or '(none yet)'}")

    def log(self, message: str) -> None:
        with self.path("log.md").open("a", encoding="utf-8") as stream:
            stream.write(f"- {now()} {message}\n")

    # ---- gates -------------------------------------------------------------
    def gate_status(self, gate: str) -> tuple[str, list[str]]:
        """Returns (open | approved | stale, files that changed since approval)."""
        record = self.state["gates"][gate]
        if record["status"] != "approved":
            return "open", []
        changed = [f for f, digest in record["files"].items() if not self.exists(f) or sha256(self.path(f)) != digest]
        return ("stale", changed) if changed else ("approved", [])

    def require(self, gate: str) -> None:
        """Every gate up to and including `gate` must be approved and untouched."""
        for g in GATES[: GATES.index(gate) + 1]:
            status, changed = self.gate_status(g)
            if status == "open":
                raise GateError(f"Gate '{g}' is not approved yet. Finish it and get the user's approval first.")
            if status == "stale":
                raise GateError(f"Gate '{g}' was approved, then these files changed: {', '.join(changed)}. Show the user the change and re-approve '{g}'.")

    def approve(self, gate: str, text: str, files: list[str]) -> None:
        if gate not in GATES:
            raise GateError(f"Unknown gate '{gate}'. Gates: {', '.join(GATES)}")
        if not text.strip():
            raise GateError("Record the user's own words as --text. An approval without their words is not an approval.")
        index = GATES.index(gate)
        if index:
            self.require(GATES[index - 1])
        missing = [f for f in files if not self.exists(f)]
        if missing:
            raise GateError(f"Cannot approve '{gate}': missing files {', '.join(missing)}")
        state = self.state
        state["gates"][gate] = {"status": "approved", "text": text.strip(), "at": now(), "files": {f: sha256(self.path(f)) for f in sorted(set(files))}}
        write_json(self.path("state.json"), state)
        self.log(f"gate '{gate}' approved by the user: 「{text.strip()}」")

    def summary(self) -> dict:
        return {g: self.gate_status(g)[0] for g in GATES}
