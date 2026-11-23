"""Burned-in Traditional Chinese captions, written by code so every character is right.

Caption rules: a cue is a clause, never a width-cut; the
burned line keeps only ？ and ！, drops 。 and turns ，、；： into a space. The .srt
sidecar keeps full punctuation.
"""
import re
from dataclasses import dataclass

from . import config
from .checks import CJK, speech_seconds

SOFT = "，、；：,;"
MIN_CUE = 0.6


@dataclass
class Cue:
    start: float
    end: float
    text: str  # full punctuation


def clauses(text: str) -> list[str]:
    """Splits at punctuation, keeping each mark with the clause it ends."""
    parts = [p for p in re.split(r"(?<=[，、；：,;。！？!?…—])", text.strip()) if p.strip()]
    return parts or [text]


def length(text: str) -> float:
    return len(CJK.findall(text)) + len(re.findall(r"[A-Za-z0-9]+", text)) * 1.5


def split_line(text: str, start: float, end: float) -> list[Cue]:
    """One scripted line becomes one cue, or several clause cues when it is too long to read at once."""
    groups, current = [], ""
    for clause in clauses(text):
        if current and length(current + clause) > config.CAPTION_MAX_CHARS:
            groups.append(current)
            current = clause
        else:
            current += clause
    groups.append(current)
    weights = [max(0.1, speech_seconds(g)) for g in groups]
    cues, clock = [], start
    for group, weight in zip(groups, weights):
        span = (end - start) * weight / sum(weights)
        cues.append(Cue(round(clock, 2), round(clock + span, 2), group.strip()))
        clock += span
    merged = []
    for cue in cues:  # a cue too short to read joins the one before it
        if merged and cue.end - cue.start < MIN_CUE:
            merged[-1] = Cue(merged[-1].start, cue.end, merged[-1].text + cue.text)
        else:
            merged.append(cue)
    return merged


def burned(text: str) -> str:
    text = text.replace("。", "")
    for mark in SOFT:
        text = text.replace(mark, " ")
    return re.sub(r"\s+", " ", text).strip()


def stamp(seconds: float, comma: bool = False) -> str:
    hundredths = round(seconds * 100)
    hours, rest = divmod(hundredths, 360000)
    minutes, rest = divmod(rest, 6000)
    secs, frac = divmod(rest, 100)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{frac * 10:03d}" if comma else f"{hours}:{minutes:02d}:{secs:02d}.{frac:02d}"


def ass(cues: list[Cue], size: tuple[int, int]) -> str:
    width, height = size
    # ASS Fontsize is not the glyph size: libass maps the font's full line height to it,
    # so CJK glyphs come out near 70% of this number. 5.1% of frame height gives ~68px glyphs at 1920.
    font_size, margin_v, outline = round(height * 0.051), round(height * 0.24), max(3, round(height * 0.0026))
    head = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Line,{config.CAPTION_FONT},{font_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{outline},1,2,40,40,{margin_v},1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    return head + "".join(f"Dialogue: 0,{stamp(c.start)},{stamp(c.end)},Line,,0,0,0,,{burned(c.text)}\n" for c in cues)


def srt(cues: list[Cue]) -> str:
    return "".join(f"{i}\n{stamp(c.start, True)} --> {stamp(c.end, True)}\n{c.text}\n\n" for i, c in enumerate(cues, 1))


def planned(shot_lines: list[tuple[float, float, list[tuple[str, str]]]]) -> dict:
    """Timing from the shot plan alone, used when nothing has listened to the clip.

    shot_lines: (shot start, shot end, [(line id, text)]) on the final timeline. Each line
    shows for about as long as it takes to say, not for the whole shot.
    """
    timing = {}
    for start, end, lines in shot_lines:
        spans = [speech_seconds(text) + 0.5 for _, text in lines]
        needed = sum(spans) + config.LINE_GAP_SECONDS * (len(lines) - 1)
        room = end - start
        scale = min(1.0, room / needed) if needed else 1.0
        clock = start + min(0.2, room - needed * scale)
        for (key, _), span in zip(lines, spans):
            timing[key] = (round(clock, 2), round(min(end, clock + span * scale), 2))
            clock += (span + config.LINE_GAP_SECONDS) * scale
    return timing
