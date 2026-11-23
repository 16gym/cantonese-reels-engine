"""The craft rules a machine can check. A gate cannot be approved while its check has errors.

Errors block. Warnings are shown to the producer, who either fixes them or tells the user why not.
Each rule exists because breaking it is what made the first engine's film look fake.
"""
import re
from dataclasses import dataclass, field
from decimal import ROUND_UP, Decimal

from . import config, plan
from .episode import Episode, read_json
from .plan import CLOSE

CJK = re.compile(r"[㐀-鿿]")
LATIN = re.compile(r"[A-Za-z0-9$%.]+")
# Written-Chinese words that give a line away as not spoken Cantonese, with the spoken form.
WRITTEN = {"的": "嘅", "是": "係", "沒": "冇", "這": "呢", "那": "嗰", "什麼": "咩／乜嘢", "怎": "點", "他": "佢", "她": "佢", "們": "哋",
           "嗎": "呀／咩", "很": "好", "不": "唔", "也": "都", "和": "同", "看": "睇", "吃": "食", "喝": "飲", "說": "講", "給": "畀",
           "在": "喺", "了": "咗／喇", "誰": "邊個", "哪": "邊", "還": "仲", "視頻": "片", "打車": "搭的士", "外賣員": "外賣仔"}
# Real Cantonese words that happen to contain one of the characters above.
SPOKEN = ("的士", "的確", "目的", "是但", "是非", "不過", "不如", "不嬲", "不停", "不知幾", "差不多", "不得了", "對不起", "不好意思", "了解",
          "除了", "為了", "其他", "和氣", "看更", "實在", "存在", "現在", "正在", "不銹鋼", "不公平", "也文也武", "小吃", "那渣")


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


PACE = config.CHARS_PER_SECOND  # the story being checked sets its own pace (Story.chars_per_second)


def speech_seconds(text: str) -> float:
    """How long a line takes to say at the story's pace."""
    pauses = sum(text.count(mark) for mark in "，、；：,;") + text.count("…") + text.count("—")
    return round(len(CJK.findall(text)) / PACE + len(LATIN.findall(text)) * 0.4 + pauses * config.PAUSE_SECONDS, 2)


def lines_seconds(texts: list[str]) -> float:
    return round(sum(speech_seconds(t) for t in texts) + config.LINE_GAP_SECONDS * max(0, len(texts) - 1), 2)


def written_words(text: str) -> list[str]:
    for word in SPOKEN:
        text = text.replace(word, "")
    return [f"{bad}→{good}" for bad, good in WRITTEN.items() if bad in text]


def plan_cost(seconds: int, characters: int, locations: int, props: int, takes: int = config.DEFAULT_TAKES, quality: str = "1080p", unit: str = "credits") -> dict:
    """Planning numbers for the story gate, in the episode's unit. Real quotes come from Higgsfield at each money stop."""
    def cents(value):
        return str(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_UP))
    rates = config.PLAN[unit]
    pictures = characters * 10 + locations * 2 + props + max(3, seconds // 3)  # casting, face, four side views, body; places; anchor frames
    voice_clips = 1 + characters  # the Cantonese test, then one audition per role
    prep = pictures * rates["image"] * Decimal("1.5") + rates["draft_per_second"] * 5 * voice_clips  # half again for redos
    hd = quality == "720p"  # takes shot at 720p, the picked take is the final
    draft = seconds * (rates["720_per_second"] if hd else rates["draft_per_second"]) * takes
    final = 0 if hd else seconds * rates["final_per_second"]
    return {"unit": unit, "prep": cents(prep), "draft": cents(draft), "draft_cap": cents(draft * (1 + config.RETAKE_ALLOWANCE)),
            "final": cents(final), "total": cents(prep + draft * (1 + config.RETAKE_ALLOWANCE) + final)}


# ---- gate 1 -------------------------------------------------------------------------
def check_story(ep: Episode) -> Report:
    global PACE
    story, report = plan.story(ep), Report()
    PACE = story.chars_per_second
    for label, items in (("character", story.characters), ("location", story.locations), ("prop", story.props), ("beat", story.beats), ("line", story.lines)):
        ids = [i.id for i in items]
        report.errors += [f"Duplicate {label} id: {i}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    people, beats = {c.id for c in story.characters}, [b.id for b in story.beats]
    last_beat = 0
    for line in story.lines:
        if line.speaker not in people:
            report.errors.append(f"{line.id}: speaker '{line.speaker}' is not a character")
        if line.beat not in beats:
            report.errors.append(f"{line.id}: beat '{line.beat}' does not exist")
            continue
        if beats.index(line.beat) < last_beat:
            report.errors.append(f"{line.id}: lines must be listed in the order they are spoken (beat {line.beat} comes earlier)")
        last_beat = max(last_beat, beats.index(line.beat))
        if len(CJK.findall(line.text)) > config.MAX_LINE_CHARS:
            report.warnings.append(f"{line.id}: {len(CJK.findall(line.text))} characters in one breath. Split it or cut it (limit {config.MAX_LINE_CHARS}).")
        if written := written_words(line.text):
            report.warnings.append(f"{line.id} reads like written Chinese, check: {', '.join(written)}")
    for beat in story.beats:
        need = lines_seconds([l.text for l in story.lines if l.beat == beat.id])
        if need > beat.seconds:
            report.errors.append(f"Beat {beat.id} is {beat.seconds}s but its lines take about {need}s to say. Cut words or give the beat more time.")
    total = sum(b.seconds for b in story.beats)
    if abs(total - story.target_seconds) > max(2, story.target_seconds * 0.1):
        report.errors.append(f"Beats add up to {total}s but target_seconds is {story.target_seconds}. Make them agree.")
    if story.beats[0].seconds > 3:
        report.errors.append(f"Hook: the first beat is {story.beats[0].seconds}s. It must be 3s or less and already be the strongest moment.")
    if len(story.hook.strip()) < 10:
        report.errors.append("Hook: say what the viewer sees and hears in the first 2 seconds and why they stay.")
    if len(story.characters) > 3:
        report.warnings.append(f"{len(story.characters)} characters. Faces drift more with every extra person; 2 or 3 is the safe range.")
    if len(story.locations) > 2:
        report.warnings.append(f"{len(story.locations)} locations. Each one must be found, built and locked; 1 or 2 keeps a reel tight.")
    report.info = {"seconds": total, "lines": len(story.lines), "speech_seconds": lines_seconds([l.text for l in story.lines]),
                   "cost": plan_cost(total, len(story.characters), len(story.locations), len(story.props), quality=ep.state.get("quality", "1080p"), unit=ep.unit)}
    return report


# ---- gate 2 -------------------------------------------------------------------------
def check_bible(ep: Episode) -> Report:
    story, bible, report = plan.story(ep), plan.bible(ep), Report()
    licensed = {r.file: r for r in plan.real_refs(ep)}
    for label, wanted, have in (("character", story.characters, bible.characters), ("location", story.locations, bible.locations), ("prop", story.props, bible.props)):
        missing = {w.id for w in wanted} - {h.id for h in have}
        extra = {h.id for h in have} - {w.id for w in wanted}
        report.errors += [f"Story {label} '{m}' is not in bible.json" for m in sorted(missing)]
        report.warnings += [f"bible.json has {label} '{e}' that the story never uses" for e in sorted(extra)]
    for character in bible.characters:
        for slot in ("face", "body"):
            if not ep.exists(character.refs.get(slot, "")):
                report.errors.append(f"Character '{character.id}' has no locked {slot} picture yet")
        if not ep.exists(character.refs.get("turn", "")):
            report.errors.append(f"Character '{character.id}' has no five-angle sheet yet. Run: reels turn {ep.name} {character.id}")
        if character.real_person and not ep.exists(character.real_person.consent):
            report.errors.append(f"Character '{character.id}' uses {character.real_person.person}'s likeness but the consent note {character.real_person.consent} is missing")
    for location in bible.locations:
        if not location.real_refs:
            report.errors.append(f"Location '{location.id}' has no real photo. Find one, or ask the user for a photo.")
        for ref in location.real_refs:
            if not ep.exists(ref):
                report.errors.append(f"Location '{location.id}': real photo {ref} is missing")
            elif ref not in licensed or not licensed[ref].licence.strip() or not licensed[ref].source_url.strip():
                report.errors.append(f"Location '{location.id}': {ref} has no source and licence in refs/refs.json")
        if not ep.exists(location.refs.get("master", "")):
            report.errors.append(f"Location '{location.id}' has no locked master picture yet")
        if len(location.map.marks) < 2:
            report.errors.append(f"Location '{location.id}': the floor map needs marks for where people and cameras stand")
    for prop in bible.props:
        if not ep.exists(prop.refs.get("sheet", "")):
            report.errors.append(f"Prop '{prop.id}' has no locked picture yet")
    report.info = {"characters": len(bible.characters), "locations": len(bible.locations), "props": len(bible.props)}
    return report


# ---- gate 3 -------------------------------------------------------------------------
def point(location, shot, name):
    """A mark, or a character standing on one, as (x, y) in real proportions."""
    mark = shot.positions.get(name, name)
    x, y = location.map.marks[mark]
    return x * location.map.aspect, y


def screen_order(location, shot) -> list[str]:
    """Who is where in frame, left to right, worked out from the floor map."""
    cx, cy = point(location, shot, shot.camera.at)
    tx, ty = point(location, shot, shot.camera.look_at)
    right = (-(ty - cy), tx - cx)  # y grows downward on the map
    def across(name):
        px, py = point(location, shot, name)
        return (px - cx) * right[0] + (py - cy) * right[1]
    return sorted(shot.positions, key=across)


def frame_sides(location, shot) -> list[tuple[str, str]]:
    """Where the place's landmarks fall in this frame, worked out on the floor map: (name, left|right|middle|edge-left|edge-right|behind).
    This is what stops a room, or a right-hand-drive taxi, from being drawn mirrored."""
    import math
    cx, cy = point(location, shot, shot.camera.at)
    tx, ty = point(location, shot, shot.camera.look_at)
    fx, fy = tx - cx, ty - cy
    length = math.hypot(fx, fy) or 1.0
    fx, fy = fx / length, fy / length
    out = []
    for fixture in location.map.fixtures:
        if not fixture.en:
            continue
        px, py = (fixture.x + fixture.w / 2) * location.map.aspect, fixture.y + fixture.h / 2
        ahead = (px - cx) * fx + (py - cy) * fy
        across = (px - cx) * -fy + (py - cy) * fx  # y grows downward on the map
        angle = math.degrees(math.atan2(across, ahead))
        if abs(angle) > 100:
            side = "behind"
        elif abs(angle) > 55:
            side = "edge-right" if angle > 0 else "edge-left"
        elif abs(angle) < 10:
            side = "middle"
        else:
            side = "right" if angle > 0 else "left"
        out.append((fixture.en, side))
    return out


def plates(location, clip) -> list[str]:
    """The locked views of the location that a clip's shots stand on, in order of first use."""
    return list(dict.fromkeys(shot.camera.plate for shot in clip.shots))


HEAD = "{name}'s head from five angles: one and the same person"


def clip_refs(bible, clip) -> list[tuple[str, str]]:
    """Every locked picture a clip must carry, in order of first appearance. (role text, path)"""
    location, refs, seen = bible.location(clip.location), [], set()
    refs.append((f"the opening frame of this clip in the location '{location.name}': match its composition, set and light exactly", plan.anchor_path(clip.location, clip.shots[0].setup)))
    for shot in clip.shots:
        for name in shot.positions:
            if name not in seen:
                seen.add(name)
                character = bible.character(name)
                refs.append((HEAD.format(name=character.id.upper()), character.refs["turn"]))
                refs.append((f"{character.id.upper()}'s whole body and costume", character.refs["body"]))
    # The approved frame of every other camera setup in the clip. These stand in for the bare location views:
    # they are what the user signed off, and the video model takes few pictures (config.VIDEO_MAX_IMAGE_REFS).
    setups = {clip.shots[0].setup}
    for number, shot in enumerate(clip.shots, 1):
        if shot.setup not in setups:
            setups.add(shot.setup)
            refs.append((f"the frame of shot {number}: when the film cuts to it, match its composition, set and light", plan.anchor_path(clip.location, shot.setup)))
    for shot in clip.shots:
        for name in shot.props:
            if name not in seen:
                seen.add(name)
                refs.append((f"the prop {name.upper()}", bible.prop(name).refs["sheet"]))
    return refs


def check_shots(ep: Episode, anchors: bool = True) -> Report:
    global PACE
    story, bible, shots, report = plan.story(ep), plan.bible(ep), plan.shots(ep), Report()
    PACE = story.chars_per_second
    speaker = {l.id: l.speaker for l in story.lines}
    text = {l.id: l.text for l in story.lines}
    people, things, places = {c.id for c in bible.characters}, {p.id for p in bible.props}, {l.id for l in bible.locations}
    spoken, sequence, setups, visited = [], [], {}, {}
    shot_ids = [s.id for c in shots.clips for s in c.shots]
    report.errors += [f"Duplicate shot id: {i}" for i in sorted({i for i in shot_ids if shot_ids.count(i) > 1})]
    report.errors += [f"Duplicate clip id: {i}" for i in sorted({c.id for c in shots.clips if [k.id for k in shots.clips].count(c.id) > 1})]

    for index, clip in enumerate(shots.clips):
        if clip.location not in places:
            report.errors.append(f"{clip.id}: location '{clip.location}' is not in the bible")
            continue
        location = bible.location(clip.location)
        marks = location.map.marks
        # The return rule: coming back to a place must reuse a camera the viewer has already seen there.
        earlier = visited.get(clip.location)
        seen_views = {s.camera.plate for c in shots.clips[:index] if c.location == clip.location for s in c.shots}
        if (not clip.new_view_ok and earlier is not None and shots.clips[index - 1].location != clip.location and clip.shots[0].setup not in earlier
                and (clip.shots[0].camera.plate == "master" or clip.shots[0].camera.plate not in seen_views)):  # a named view seen before is the same side of the place
            report.errors.append(f"{clip.id} returns to '{clip.location}' with a new camera setup '{clip.shots[0].setup}'. Open the return on a setup already used there ({', '.join(sorted(earlier))}), or on the same locked view, so the place is recognisably the same.")
        visited.setdefault(clip.location, set())
        clock = 0
        for shot in clip.shots:
            where = f"{clip.id}/{shot.id}"
            if shot.start != clock or shot.end <= shot.start:
                report.errors.append(f"{where}: shots must run back to back in whole seconds. Expected start {clock}, got {shot.start}–{shot.end}.")
            clock = shot.end
            bad_marks = [m for m in [shot.camera.at, *shot.positions.values()] if m not in marks]
            if shot.camera.look_at not in marks and shot.camera.look_at not in shot.positions:
                bad_marks.append(shot.camera.look_at)
            if bad_marks:
                report.errors.append(f"{where}: not on the floor map of '{clip.location}': {', '.join(bad_marks)}")
            if shot.camera.plate not in location.refs:
                report.errors.append(f"{where}: camera.plate '{shot.camera.plate}' is not a locked view of '{clip.location}'. Locked views: {', '.join(sorted(location.refs)) or 'none'}.")
            report.errors += [f"{where}: '{n}' is not a character in the bible" for n in shot.positions if n not in people]
            report.errors += [f"{where}: prop '{n}' is not in the bible" for n in shot.props if n not in things]
            for line in shot.lines:
                if line not in speaker:
                    report.errors.append(f"{where}: line {line} is not in the story")
                elif speaker[line] not in shot.positions and line not in shot.offscreen:
                    report.errors.append(f"{where}: {speaker[line]} says {line} but is not in frame. Put them in positions, or list {line} under offscreen.")
            spoken += shot.lines
            need = lines_seconds([text[l] for l in shot.lines if l in text])
            if need > shot.end - shot.start + 0.25:
                report.errors.append(f"{where}: {shot.end - shot.start}s long but its lines take about {need}s. Lengthen the shot or move a line.")
            if shot.end - shot.start > config.MAX_SHOT_SECONDS:
                report.warnings.append(f"{where}: {shot.end - shot.start}s on one shot. Past {config.MAX_SHOT_SECONDS}s it needs a reason (a long reaction, a reveal).")
            key = (clip.location, shot.setup)
            camera = (shot.size, shot.camera.at, shot.camera.look_at, shot.camera.height)
            if setups.setdefault(key, camera) != camera:
                report.errors.append(f"{where}: setup '{shot.setup}' was defined earlier with a different size or camera. One setup = one camera. Rename this one.")
            if sequence and sequence[-1][0] == key:
                report.errors.append(f"{where}: same setup as the shot before it ({sequence[-1][1]}). That is a jump cut; change size or angle, or merge the two shots.")
            sequence.append((key, where, shot.end - shot.start, bool(shot.lines), shot.size))
            visited[clip.location].add(shot.setup)
        if clock != clip.duration:
            report.errors.append(f"{clip.id}: shots end at {clock}s but duration is {clip.duration}s")
        if len(clip.shots) > config.MAX_SHOTS_PER_CLIP:
            report.warnings.append(f"{clip.id}: {len(clip.shots)} shots in one clip. Past {config.MAX_SHOTS_PER_CLIP} the model starts dropping shots; split the clip.")
        # The 180-degree rule, checked on the floor map.
        cast = {n for s in clip.shots for n in s.positions}
        if len(cast) >= 2 and not bad_marks_in(clip, marks):
            if clip.axis is None or not set(clip.axis) <= cast:
                report.errors.append(f"{clip.id}: two or more people are in this clip. Set axis to the two whose eyeline the cameras must stay on one side of.")
            else:
                sides = {}
                for shot in clip.shots:
                    if shot.size in ("INSERT", "WIDE") or shot.cross_axis_ok:
                        continue
                    # Where each of the two stands: this shot if it shows them, otherwise any shot of the clip that does (a clip may be all singles).
                    (ax, ay), (bx, by) = (point(location, next(s for s in [shot, *clip.shots] if name in s.positions), name) for name in clip.axis)
                    cx, cy = point(location, shot, shot.camera.at)
                    cross = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
                    if abs(cross) < 1e-6:
                        report.errors.append(f"{clip.id}/{shot.id}: the camera sits exactly on the eyeline. Move it to one side.")
                    else:
                        sides.setdefault(cross > 0, []).append(shot.id)
                if len(sides) == 2:
                    minority = min(sides.values(), key=len)
                    report.errors.append(f"{clip.id}: cameras are on both sides of the {clip.axis[0]}–{clip.axis[1]} eyeline, so people will flip left and right between cuts. Move {', '.join(minority)} across, or give cross_axis_ok a reason.")
        if not report.errors:
            count = len(clip_refs(bible, clip))
            if count > config.VIDEO_MAX_IMAGE_REFS:
                report.errors.append(f"{clip.id} needs {count} reference pictures; the limit is {config.VIDEO_MAX_IMAGE_REFS}. Split the clip so each half shows fewer people and props.")

    wanted = [l.id for l in story.lines]
    if spoken != wanted:
        missing = [l for l in wanted if l not in spoken]
        twice = sorted({l for l in spoken if spoken.count(l) > 1})
        detail = "; ".join(filter(None, [f"missing {', '.join(missing)}" if missing else "", f"used twice {', '.join(twice)}" if twice else "", "" if missing or twice else "out of order"]))
        report.errors.append(f"Every story line must be spoken exactly once, in order: {detail}")
    total = sum(item[2] for item in sequence) or 1
    for key in setups:
        share = sum(item[2] for item in sequence if item[0] == key) / total
        if share > config.SETUP_SHARE_ERROR:
            report.errors.append(f"Setup '{key[1]}' in '{key[0]}' carries {share:.0%} of the film. Add coverage: a closer size, the reverse angle, a reaction, an insert.")
        elif share > config.SETUP_SHARE_WARN:
            report.warnings.append(f"Setup '{key[1]}' in '{key[0]}' carries {share:.0%} of the film. Consider more coverage.")
    talk = sum(item[2] for item in sequence if item[3])
    if talk and sum(item[2] for item in sequence if item[3] and item[4] in CLOSE) / talk < 0.3:
        report.warnings.append("Under 30% of the dialogue is in close shots (ECU, CU, MCU). Feeling reads in close-ups; move the turning points closer.")
    if sequence and not sequence[0][3] and sequence[0][2] > 2:
        report.warnings.append("The film opens on a silent shot longer than 2s. Start on the hook line or the strongest action.")
    if abs(total - story.target_seconds) > max(2, story.target_seconds * 0.1):
        report.warnings.append(f"Shots add up to {total}s; the approved story targets {story.target_seconds}s.")
    if anchors and not report.errors:
        from . import qa
        for location, setup in setups:
            media = plan.anchor_path(location, setup)
            if not ep.exists(media):
                report.errors.append(f"No anchor frame yet for setup '{setup}' in '{location}'")
            elif qa.result(ep, media) != "pass":
                report.errors.append(f"The anchor frame for setup '{setup}' in '{location}' has not passed QA")
    report.info = {"seconds": total, "clips": len(shots.clips), "shots": len(sequence), "setups": [f"{l}/{s}" for l, s in setups]}
    return report


def bad_marks_in(clip, marks) -> bool:
    return any(m not in marks for s in clip.shots for m in [s.camera.at, *s.positions.values()])


# ---- gates 4 and 5 ------------------------------------------------------------------
def selection(ep: Episode) -> dict:
    """The take the user picked for each clip: {"c01": 2, "c02": 1}."""
    path = ep.path("takes", "selection.json")
    return read_json(path) if path.exists() else {}


def check_takes(ep: Episode) -> Report:
    from . import qa
    shots, chosen, report = plan.shots(ep), selection(ep), Report()
    for clip in shots.clips:
        take = chosen.get(clip.id)
        video = f"takes/{clip.id}/t{take}.mp4"
        if take is None:
            report.errors.append(f"{clip.id}: the user has not picked a take")
        elif not ep.exists(video):
            report.errors.append(f"{clip.id}: picked take {take} does not exist")
        elif qa.result(ep, video) != "pass":
            report.errors.append(f"{clip.id}: take {take} did not pass QA. Pick a passing take, or record the user's acceptance with: reels qa override")
    return report


def check_final(ep: Episode) -> Report:
    from . import qa
    shots, report = plan.shots(ep), Report()
    for clip in shots.clips:
        if ep.exists(f"finals/{clip.id}.mp4"):  # route A: Higgsfield's 1080p pass, checked again by QA
            if qa.result(ep, f"finals/{clip.id}.mp4") != "pass":
                report.errors.append(f"{clip.id}: the 1080p final has not passed QA")
        elif not ep.exists(f"upscale/{clip.id}.mp4"):  # route B: the picked take (QA'd at gate 4) upscaled on Kie
            report.errors.append(f"{clip.id}: no final yet. Route A: reels finalize. Route B: reels upscale")
    if not ep.exists("out/final.mp4") and not ep.exists("out/final-4k.mp4"):
        report.errors.append("The film has not been cut yet: reels cut (or reels cut --upscaled)")
    return report


CHECKS = {"story": check_story, "lock": check_bible, "angles": check_shots, "takes": check_takes, "final": check_final}


def frozen_files(ep: Episode, gate: str) -> list[str]:
    """The files an approval of this gate freezes."""
    if gate == "story":
        return ["story.json"]
    if gate == "lock":
        bible = plan.bible(ep)
        files = ["bible.json", "refs/refs.json"]
        for item in [*bible.characters, *bible.locations, *bible.props]:
            files += list(item.refs.values()) + list(getattr(item, "real_refs", []))
        return files
    if gate == "angles":
        shots = plan.shots(ep)
        return ["shots.json", *sorted({plan.anchor_path(c.location, s.setup) for c in shots.clips for s in c.shots})]
    if gate == "takes":
        return ["takes/selection.json", *[f"takes/{c}/t{t}.mp4" for c, t in selection(ep).items()]]
    return [f for f in ("out/final.mp4", "out/final-4k.mp4") if ep.exists(f)] or ["out/final.mp4"]
