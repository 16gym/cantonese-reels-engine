"""Money ledger. Nothing is submitted without a reservation inside an approved cap.

Three buckets per episode, each approved by the user in their own words:
  prep  - pictures for casting, sheets and anchor frames, plus the voice test
  draft - 480p takes. The cap already includes the 30% retake allowance.
  final - 1080p versions of the takes they picked
Amounts are in the episode's unit: Higgsfield plan credits (CLI) or US dollars (REST).
A submission whose outcome is unknown keeps its reservation: never resubmit blindly.
"""
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path

BUCKETS = ("prep", "draft", "final")
LIVE = ("submitting", "submission_unknown", "queued", "in_progress")  # in flight: a second submit would pay twice


class MoneyError(RuntimeError):
    """Stop and ask the user. The message says why."""


def money(value) -> int:
    """An amount as integer millionths, so sums are exact."""
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"Not an amount: {value!r}") from exc
    scaled = number * 1_000_000
    if not number.is_finite() or number < 0 or scaled != scaled.to_integral_value():
        raise ValueError(f"Not an amount: {value!r}")
    return int(scaled)


def amount(micro: int) -> str:
    value = Decimal(micro) / 1_000_000
    return f"{value:.2f}" if micro % 10_000 == 0 else f"{value:.4f}".rstrip("0")


def fmt(value, unit: str) -> str:
    """'US$1.20' or '18 credits'. value is an amount string or number."""
    text = str(value)
    return f"US${text}" if unit == "US$" else f"{text} {unit}"


class Ledger:
    def __init__(self, path: Path, unit: str = "US$"):
        self.path, self.unit = Path(path), unit
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS approvals (
                episode TEXT NOT NULL, bucket TEXT NOT NULL, cap_micro INTEGER NOT NULL,
                base_micro INTEGER NOT NULL, text TEXT NOT NULL, at REAL NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, episode TEXT NOT NULL, bucket TEXT NOT NULL, label TEXT NOT NULL,
                kind TEXT NOT NULL, model TEXT NOT NULL, body TEXT NOT NULL, out_path TEXT NOT NULL,
                quote_micro INTEGER NOT NULL, commit_micro INTEGER NOT NULL, state TEXT NOT NULL,
                idem TEXT NOT NULL, request_id TEXT, status_url TEXT, outputs TEXT, error TEXT, created REAL NOT NULL)""")

    def show(self, micro: int) -> str:
        return fmt(amount(micro), self.unit)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            # Synced folders (OneDrive, Dropbox): short rollback-journal transactions, no WAL sidecar files.
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    # ---- approvals -----------------------------------------------------------
    def approve(self, episode: str, bucket: str, cap, text: str, base=None) -> None:
        if bucket not in BUCKETS:
            raise MoneyError(f"Unknown bucket '{bucket}'. Buckets: {', '.join(BUCKETS)}")
        if not text.strip():
            raise MoneyError("Record the user's own words. A cap without their words is not approved.")
        cap_micro = money(cap)
        if cap_micro <= 0:
            raise MoneyError("Cap must be above zero")
        with self.connection() as db:
            db.execute("INSERT INTO approvals VALUES (?,?,?,?,?,?)", (episode, bucket, cap_micro, money(base if base is not None else cap), text.strip(), time.time()))

    def cap(self, episode: str, bucket: str):
        with self.connection() as db:
            return db.execute("SELECT * FROM approvals WHERE episode=? AND bucket=? ORDER BY rowid DESC LIMIT 1", (episode, bucket)).fetchone()

    # ---- jobs ----------------------------------------------------------------
    def reserve(self, episode, bucket, label, kind, model, body, quote, out_path) -> dict:
        quote = money(quote)
        with self.connection() as db:
            approval = db.execute("SELECT * FROM approvals WHERE episode=? AND bucket=? ORDER BY rowid DESC LIMIT 1", (episode, bucket)).fetchone()
            if approval is None:
                raise MoneyError(f"No approved '{bucket}' budget for {episode}. Quote it, show the user, record their approval first.")
            clash = db.execute(f"SELECT id FROM jobs WHERE episode=? AND label=? AND state IN ({','.join('?' * len(LIVE))})", (episode, label, *LIVE)).fetchone()
            if clash:
                raise MoneyError(f"'{label}' is already in flight (job {clash['id']}). Run: reels collect")
            used = db.execute("SELECT coalesce(sum(commit_micro),0) FROM jobs WHERE episode=? AND bucket=?", (episode, bucket)).fetchone()[0]
            if used + quote > approval["cap_micro"]:
                raise MoneyError(f"'{bucket}' budget for {episode} would be exceeded: used {self.show(used)} + this {self.show(quote)} > cap {self.show(approval['cap_micro'])}. Stop and ask the user.")
            job_id = str(uuid.uuid4())
            db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (job_id, episode, bucket, label, kind, model, json.dumps(body, ensure_ascii=False), str(out_path), quote, quote, "submitting", str(uuid.uuid4()), None, None, None, None, time.time()))
        return self.get(job_id)

    def get(self, job_id) -> dict:
        with self.connection() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise MoneyError(f"Unknown job {job_id}")
        item = dict(row)
        item["body"] = json.loads(item["body"])
        item["outputs"] = json.loads(item["outputs"]) if item["outputs"] else []
        return item

    def accepted(self, job_id, request_id, status_url) -> None:
        with self.connection() as db:
            db.execute("UPDATE jobs SET state='queued', request_id=?, status_url=? WHERE id=?", (request_id, status_url, job_id))

    def unknown(self, job_id) -> None:
        """Submit may or may not have reached the provider: keep the money held."""
        with self.connection() as db:
            db.execute("UPDATE jobs SET state='submission_unknown' WHERE id=? AND state='submitting'", (job_id,))

    def rejected(self, job_id, error: str) -> None:
        """Provider refused the request outright: nothing was generated, release the money."""
        with self.connection() as db:
            db.execute("UPDATE jobs SET state='failed', commit_micro=0, error=? WHERE id=?", (error[:500], job_id))

    def finish(self, job_id, state, outputs=None, error=None) -> None:
        # Higgsfield does not charge failed or nsfw requests, so those release their reservation.
        release = state in ("failed", "nsfw", "canceled")
        with self.connection() as db:
            db.execute("UPDATE jobs SET state=?, outputs=coalesce(?,outputs), error=?, commit_micro=CASE WHEN ? THEN 0 ELSE commit_micro END WHERE id=?",
                       (state, json.dumps(outputs) if outputs else None, error, release, job_id))

    def jobs(self, episode, states=None) -> list[dict]:
        with self.connection() as db:
            ids = [r["id"] for r in db.execute("SELECT id, state FROM jobs WHERE episode=? ORDER BY rowid", (episode,)) if states is None or r["state"] in states]
        return [self.get(i) for i in ids]

    def summary(self, episode) -> dict:
        result = {}
        for bucket in BUCKETS:
            approval = self.cap(episode, bucket)
            with self.connection() as db:
                used = db.execute("SELECT coalesce(sum(commit_micro),0) FROM jobs WHERE episode=? AND bucket=?", (episode, bucket)).fetchone()[0]
            result[bucket] = {
                "unit": self.unit,
                "approved": bool(approval),
                "cap": amount(approval["cap_micro"]) if approval else None,
                "base": amount(approval["base_micro"]) if approval else None,
                "used": amount(used),
                "into_retake_allowance": bool(approval) and used > approval["base_micro"],
            }
        return result
