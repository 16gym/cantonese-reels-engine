"""Listens to a generated clip: was each scripted line actually said, and when.

Optional. Needs faster-whisper (`pip install faster-whisper`). Without it the engine
still runs: captions use the planned shot timing and the user's ear is the only speech check.

Settings come from measurements made while building the engine: the `medium` model,
language "zh" (only large-v3 knows "yue") and a colloquial-Cantonese prompt. Without
the prompt Whisper writes Mandarin-style text and every line would score as wrong.
"""
import difflib
import re
from pathlib import Path

from . import config

PROMPT = "以下係香港廣東話口語對白，用繁體中文同粵語字寫，例如：嘅、咗、喺、唔、冇、佢、哋、嚟、啲、咩、點解。"
KEEP = re.compile(r"[㐀-鿿A-Za-z0-9]")
_model = None


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def transcribe(video: Path) -> list[tuple[str, float, float]]:
    """Every heard character with its start and end time."""
    global _model
    from faster_whisper import WhisperModel
    if _model is None:
        _model = WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8")
    language = "yue" if config.WHISPER_MODEL.startswith("large-v3") and "turbo" not in config.WHISPER_MODEL else "zh"
    segments, _ = _model.transcribe(str(video), language=language, initial_prompt=PROMPT, word_timestamps=True,
                                    condition_on_previous_text=True, repetition_penalty=1.15, no_repeat_ngram_size=6)
    heard = []
    for segment in segments:
        for word in segment.words or []:
            letters = KEEP.findall(word.word)
            step = (word.end - word.start) / max(1, len(letters))
            heard += [(letter, word.start + i * step, word.start + (i + 1) * step) for i, letter in enumerate(letters)]
    return heard


def align(lines: list[tuple[str, str]], heard: list[tuple[str, float, float]]) -> dict:
    """Matches scripted lines (id, text) to heard characters. score = share of the line that was heard."""
    script, owner = "", []
    for key, text in lines:
        letters = "".join(KEEP.findall(text)).lower()
        script += letters
        owner += [key] * len(letters)
    sound = "".join(letter for letter, _, _ in heard).lower()
    hits = {key: [] for key, _ in lines}
    for block in difflib.SequenceMatcher(None, script, sound, autojunk=False).get_matching_blocks():
        for offset in range(block.size):
            hits[owner[block.a + offset]].append(block.b + offset)
    result = {}
    for key, text in lines:
        size = max(1, len(KEEP.findall(text)))
        found = hits[key]
        result[key] = {"score": round(len(found) / size, 2),
                       "start": round(heard[min(found)][1], 2) if found else None,
                       "end": round(heard[max(found)][2], 2) if found else None,
                       "heard": "".join(h[0] for h in heard[min(found): max(found) + 1]) if found else ""}
    return result


def listen(video: Path, lines: list[tuple[str, str]]) -> dict:
    heard = transcribe(video)
    return {"heard": "".join(h[0] for h in heard), "lines": align(lines, heard)}
