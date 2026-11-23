"""Every tunable in one place. Change values here, not in the code that uses them.

Routes and limits were read from the official Higgsfield API reference (2026-11-20) and
the Higgsfield CLI's own model schemas (`higgsfield model get`, 2026-11-23).
Things the docs do not state (marked UNVERIFIED) are knobs on purpose: the first
real runs tell us the right value.
"""
import os
from decimal import Decimal
from pathlib import Path

# ---- Which way to reach Higgsfield ------------------------------------------------
# cli:  the official `higgsfield` CLI, logged in with `higgsfield auth login`. Spends the
#       credits of a Higgsfield plan (Plus or above has Seedance 2.5). Default.
# rest: the pay-as-you-go Model API with a key in .env. A separate prepaid balance, not plan credits.
# An episode keeps the provider it was created with, so one budget never mixes units.
PROVIDERS = ("cli", "rest")
UNITS = {"cli": "credits", "rest": "US$"}


def default_provider() -> str:
    value = env_value("REELS_PROVIDER").lower() or "cli"
    if value not in PROVIDERS:
        raise ValueError(f"REELS_PROVIDER is '{value}'. Use one of: {', '.join(PROVIDERS)}")
    return value


def env_value(name: str) -> str:
    """One setting: the environment variable if set, else the repo's .env. Never printed. Empty when absent."""
    if os.environ.get(name, "").strip():
        return os.environ[name].strip()
    from .episode import repo_root
    path = repo_root() / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            key, separator, value = line.strip().partition("=")
            if separator and key.strip() == name and not key.startswith("#"):
                return value.strip().strip("\"'")
    return ""


# ---- Higgsfield CLI job types (higgsfield model get <job_type>) --------------------
CLI_VIDEO = "seedance_2_5"  # modes t2v / omni_reference; draft + draft_job_id; 480p-4k; <=30 images, <=50 media in all
CLI_IMAGE = "seedream_v5_pro"  # <=10 image_references; 1k / 1.5k / 2k
HIGGSFIELD_PLANS = "https://higgsfield.ai/pricing"
CLI_MIN_PLANS = ("plus", "ultra", "business", "creator", "team", "enterprise")  # Starter has no Seedance 2.5; Free cannot use the CLI

# ---- Higgsfield REST routes ---------------------------------------------------
API = "https://api.higgsfield.ai"
VIDEO = "bytedance/seedance-2.5/reference-to-video"
VIDEO_TEXT = "bytedance/seedance-2.5/text-to-video"
VIDEO_FINALIZE = "bytedance/seedance-2.5/finalize-draft"
IMAGE_T2I = "bytedance/seedream/v5.0/pro/text-to-image"
IMAGE_EDIT = "bytedance/seedream/v5.0/pro/edit"
IMAGE_RESOLUTION = "1.5k"  # Seedream: 1k, 1.5k, 2k. 2k doubles the price.
IMAGE_MAX_REFS = 10
VIDEO_MAX_IMAGE_REFS = 9  # API allows 30. Higgsfield's own guide: one reference per element drifts least.
ASPECT = "9:16"

# UNVERIFIED on REST: how a prompt names its reference media. This is ByteDance's
# documented wording. If generations ignore references, try "@Image {n}".
IMAGE_TAG = "Image {n}"
AUDIO_TAG = "Audio {n}"

# Hosts we accept media URLs from. The API key is only ever sent to api.higgsfield.ai.
# The CLI's uploads were seen on d2ol7oe51mr4n9.cloudfront.net; its outputs may use another
# CloudFront host, so plain https on cloudfront.net is accepted for downloads (nothing secret is sent).
ASSET_HOSTS = {"d3u0tzju9qaucj.cloudfront.net", "d3snorpfx4xhv8.cloudfront.net", "d2ol7oe51mr4n9.cloudfront.net"}
ASSET_DOMAINS = ("higgsfield.ai", "cloudfront.net")
UPLOAD_TTL_HOURS = 24  # Higgsfield deletes uploads within 7 days; re-upload well before that.

# ---- Planning numbers (real quotes always come from the provider's free estimate) ---
# Per unit. Credits were read from `higgsfield generate cost` on 2026-11-23; US$ from the REST estimate.
PLAN = {
    "credits": {"draft_per_second": Decimal("3"), "final_per_second": Decimal("16"), "720_per_second": Decimal("7"), "image": Decimal("1.25")},
    "US$": {"draft_per_second": Decimal("0.1177"), "final_per_second": Decimal("0.6518"), "720_per_second": Decimal("0.2647"), "image": Decimal("0.054")},
}
RETAKE_ALLOWANCE = Decimal("0.30")  # 30% of the draft budget, then stop and ask the user.
DEFAULT_TAKES = 2

# ---- Kie AI: 4K upscale of the finished clips (the only thing not done on Higgsfield) ---
KIE_API = "https://api.kie.ai/api/v1"
KIE_UPSCALE_MODEL = "video/upscale"
KIE_UPSCALE_PER_SECOND = Decimal("0.03")  # US$ at 4K, measured 2026-11-22 (97 credits for 16 s). Limit 50 MB / 60 s per clip.

# ---- Craft limits ---------------------------------------------------------------
CHARS_PER_SECOND = 4.5  # natural Cantonese drama delivery; calibrate against real takes
PAUSE_SECONDS = 0.2  # per comma, ellipsis or dash inside a line
LINE_GAP_SECONDS = 0.3  # breath between two lines
MAX_LINE_CHARS = 16
MAX_SHOT_SECONDS = 6
MAX_SHOTS_PER_CLIP = 6
SETUP_SHARE_ERROR = 0.5  # one camera setup carrying more than half the runtime is the old engine's failure
SETUP_SHARE_WARN = 0.35
PROMPT_WORD_LIMIT = 950  # ByteDance documents 1,000 English words

# ---- Output -----------------------------------------------------------------------
FINAL_SIZE = (1080, 1920)
UPSCALED_SIZE = (2160, 3840)  # Kie's 4K comes back 2158x3840; the cut pads it to an even size
DRAFT_SIZE = (720, 1280)
TARGET_LUFS = -14.0  # each clip is levelled to this, so no clip is louder than its neighbours
MAX_GAIN_DB = 12.0
MUSIC_VOLUME = 0.15
CAPTION_FONT = os.environ.get("REELS_CAPTION_FONT") or ("Microsoft JhengHei" if os.name == "nt" else "PingFang TC")
CAPTION_MAX_CHARS = 12  # per cue, at 1080 wide
WHISPER_MODEL = os.environ.get("REELS_WHISPER_MODEL", "medium")
SPEECH_PASS_SCORE = 0.7  # share of a scripted line the listener must hear


def font(bold: bool = False) -> str | None:
    """A Traditional Chinese font for review PDFs. Override with REELS_FONT / REELS_FONT_BOLD."""
    override = os.environ.get("REELS_FONT_BOLD" if bold else "REELS_FONT")
    candidates = [override] if override else []
    windows = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    candidates += [windows / ("msjhbd.ttc" if bold else "msjh.ttc"), windows / "NotoSansTC-VF.ttf",
                   "/System/Library/Fonts/PingFang.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]
    return next((str(c) for c in candidates if c and Path(c).is_file()), None)
