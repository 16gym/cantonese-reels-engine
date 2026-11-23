"""Continuity QA: puts each shot's frames next to the locked pictures, and keeps the verdicts.

The QA agent looks at the comparison sheets and fills in the verdict file. Code decides
pass or fail from the answers, so a verdict cannot be 'pass' with an unanswered check.
QA cannot hear: speech is checked by speech.py when it is installed, and by the user's ear.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import checks, config, edit, plan, speech
from .episode import Episode, GateError, read_json, write_json

SHOT_CHECKS = {
    "identity": "Each person has the same face, hair, age and build as their locked face picture.",
    "wardrobe": "Clothes match the locked body picture: garment, colour, sleeve length, accessories.",
    "props": "Each prop matches its locked picture and stays the same object through the shot.",
    "location": "The room matches the locked master: layout, furniture, wall finish, where the light comes from.",
    "layout": "Nothing is mirrored. Every landmark is on the side of the frame the request's geometry line gives (in a Hong Kong taxi the driver and steering wheel are on the car's right). Work it out from concrete cues, such as which arm is nearer the camera. The vehicle or room is the same model as the locked views, not a look-alike.",
    "light": "Time of day and light colour match the bible. No jump from night to day.",
    "staging": "People are where the shot plan puts them, in the planned left-to-right order, at the planned shot size.",
    "anatomy": "Hands, faces, limbs and objects are physically right. Nothing melts, doubles or passes through anything.",
    "text": "No subtitles, captions, watermarks or garbled writing anywhere in frame.",
    "action": "The planned action happens, and the performance reads as the planned feeling.",
    "mouth": "Only the scripted speaker's lips move. Silent people keep their lips closed.",
}
ANCHOR_CHECKS = ("identity", "wardrobe", "props", "location", "layout", "light", "staging", "anatomy", "text")
ANSWERS = ("pass", "fail", "na")


def verdict_path(ep: Episode, media: str) -> Path:
    return ep.path(media).with_suffix(".qa.json")


def result(ep: Episode, media: str) -> str | None:
    """pass, fail, or None when there is no settled verdict for the file as it is now."""
    path = verdict_path(ep, media)
    if not path.exists() or stale(ep, media):
        return None
    return read_json(path).get("result")


def stale(ep: Episode, media: str) -> bool:
    """The file was made again after its verdict was written (a redo), so it must be checked again."""
    path = verdict_path(ep, media)
    return path.exists() and ep.path(media).exists() and ep.path(media).stat().st_mtime > path.stat().st_mtime


def needs_prepare(ep: Episode, media: str, redo: bool = False) -> bool:
    return ep.exists(media) and (redo or not verdict_path(ep, media).exists() or stale(ep, media))


def _font(size: int):
    path = config.font(bold=True)
    return ImageFont.truetype(path, size) if path else ImageFont.load_default()


def _sheet(title: str, references: list[tuple[str, Path]], frames: list[tuple[str, Path]], target: Path) -> None:
    """Top row: the locked pictures. Bottom row: what was generated. Same height, side by side, labelled."""
    cell, pad, label = 420, 16, 44
    def row(items):
        tiles = []
        for name, path in items:
            image = Image.open(path).convert("RGB")
            image.thumbnail((cell * 2, cell))
            tile = Image.new("RGB", (image.width, cell + label), "white")
            tile.paste(image, (0, label))
            ImageDraw.Draw(tile).text((4, 6), name[:40], fill=(0, 0, 0), font=_font(26))
            tiles.append(tile)
        return tiles
    top, bottom = row(references), row(frames)
    width = max(sum(t.width + pad for t in top), sum(t.width + pad for t in bottom)) + pad
    sheet = Image.new("RGB", (width, 70 + 2 * (cell + label + pad)), (235, 235, 235))
    ImageDraw.Draw(sheet).text((pad, 14), title, fill=(0, 0, 0), font=_font(34))
    for line, tiles in enumerate((top, bottom)):
        x = pad
        for tile in tiles:
            sheet.paste(tile, (x, 70 + line * (cell + label + pad)))
            x += tile.width + pad
    target.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(target, quality=88)


def _references(ep: Episode, bible, clip, shot) -> list[tuple[str, Path]]:
    place = bible.location(clip.location)
    items = [("LOCKED place", ep.path(place.refs["master"]))]
    anchor = ep.path(plan.anchor_path(clip.location, shot.setup))
    if anchor.exists():
        items.append((f"LOCKED angle {shot.setup}", anchor))
    for name in shot.positions:
        items += [(f"LOCKED {name} face", ep.path(bible.character(name).refs["face"])), (f"LOCKED {name} body", ep.path(bible.character(name).refs["body"]))]
    items += [(f"LOCKED prop {name}", ep.path(bible.prop(name).refs["sheet"])) for name in shot.props]
    return items


def prepare_clip(ep: Episode, media: str, clip_id: str) -> Path:
    """Builds comparison sheets and an empty verdict for one take or final. Returns the verdict path."""
    story, bible, shots = plan.story(ep), plan.bible(ep), plan.shots(ep)
    clip, video = shots.clip(clip_id), ep.path(media)
    if not video.exists():
        raise GateError(f"{media} does not exist yet. Run: reels collect {ep.name}")
    folder = video.with_suffix(".qa")
    for shot in clip.shots:
        times = [shot.start + 0.3, (shot.start + shot.end) / 2, shot.end - 0.3]
        frames = [(f"{shot.id} at {t:.1f}s", edit.frame(video, t, folder / f"{shot.id}-{i}.jpg")) for i, t in enumerate(times)]
        order = checks.screen_order(bible.location(clip.location), shot)
        title = f"{clip.id}/{shot.id}  {shot.start}-{shot.end}s  {shot.size}  left to right: {', '.join(order) or 'nobody'}"
        _sheet(title, _references(ep, bible, clip, shot), frames, folder / f"{shot.id}.jpg")
    lines = [(l.id, l.text) for l in story.lines if any(l.id in s.lines for s in clip.shots)]
    auto = {"speech": "not checked: faster-whisper is not installed, so the user's ear is the only speech check"}
    if ep.state.get("mock"):
        auto = {"speech": "not checked: mock clips contain a test tone, not speech"}
    elif lines and speech.available():
        heard = speech.listen(video, lines)
        write_json(video.with_suffix(".speech.json"), heard)
        weak = {k: v for k, v in heard["lines"].items() if v["score"] < config.SPEECH_PASS_SCORE}
        auto = {"speech": "pass" if not weak else "fail", "heard": heard["heard"], "weak_lines": {k: {"scripted": dict(lines)[k], **v} for k, v in weak.items()}}
    verdict = {"media": media, "clip": clip_id, "result": None, "auto": auto,
               "shots": {s.id: {**{name: None for name in SHOT_CHECKS}, "notes": ""} for s in clip.shots},
               "fix": [], "summary": ""}
    write_json(verdict_path(ep, media), verdict)
    return verdict_path(ep, media)


def prepare_anchor(ep: Episode, clip_id: str, shot_id: str) -> Path:
    bible, shots = plan.bible(ep), plan.shots(ep)
    clip = shots.clip(clip_id)
    shot = next(s for s in clip.shots if s.id == shot_id)
    media = plan.anchor_path(clip.location, shot.setup)
    if not ep.exists(media):
        raise GateError(f"{media} does not exist yet")
    order = checks.screen_order(bible.location(clip.location), shot)
    references = [r for r in _references(ep, bible, clip, shot) if "angle" not in r[0]]
    _sheet(f"ANCHOR {clip.location}/{shot.setup}  {shot.size}  left to right: {', '.join(order) or 'nobody'}", references,
           [("GENERATED anchor", ep.path(media))], ep.path(media).with_suffix(".qa.jpg"))
    write_json(verdict_path(ep, media), {"media": media, "clip": clip_id, "result": None, "auto": {},
                                         "shots": {shot.setup: {**{name: None for name in ANCHOR_CHECKS}, "notes": ""}}, "fix": [], "summary": ""})
    return verdict_path(ep, media)


def record(ep: Episode, media: str) -> dict:
    """Reads the QA agent's filled-in verdict, refuses blanks, and settles pass or fail."""
    path = verdict_path(ep, media)
    if not path.exists():
        raise GateError(f"No verdict file for {media}. Run: reels qa prepare first")
    verdict = read_json(path)
    blanks, fails = [], []
    for shot, answers in verdict["shots"].items():
        for name, answer in answers.items():
            if name == "notes":
                continue
            if answer not in ANSWERS:
                blanks.append(f"{shot}.{name}")
            elif answer == "fail":
                fails.append(f"{shot}.{name}")
    if blanks:
        raise GateError(f"QA is not finished for {media}. Answer pass, fail or na for: {', '.join(blanks)}")
    if verdict["auto"].get("speech") == "fail":
        fails.append("speech")
    if fails and not verdict["fix"]:
        raise GateError(f"{media} fails on {', '.join(fails)} but 'fix' is empty. Write one concrete instruction per failure for the retake.")
    verdict["result"] = "fail" if fails else "pass"
    verdict["failed"] = fails
    write_json(path, verdict)
    ep.log(f"QA {verdict['result']}: {media}" + (f" ({', '.join(fails)})" if fails else ""))
    return verdict


def override(ep: Episode, media: str, text: str) -> None:
    """Only the user can accept something QA failed. Their words are kept with the verdict."""
    path = verdict_path(ep, media)
    if not path.exists() or not text.strip():
        raise GateError("An override needs an existing verdict and the user's own words")
    verdict = read_json(path)
    verdict.update(result="pass", overridden_by_user=text.strip())
    write_json(path, verdict)
    ep.log(f"QA overridden by the user for {media}: 「{text.strip()}」")
