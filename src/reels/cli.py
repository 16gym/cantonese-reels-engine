"""`reels` command line. Output is plain text for the producer agent to read and relay.

A line starting with STOP means: do not work around it. Tell the user, or fix the named file.
"""
import json
import shutil
import sys
import time
from pathlib import Path

import typer

from . import captions, checks, config, edit, photos, plan, prompts, qa, review, speech
from .episode import GATES, Episode, GateError, read_json, repo_root, write_json
from .episode import sha256 as sha
from .higgsfield import ProviderError
from .ledger import MoneyError, fmt
from .studio import Studio, cut_wav

app = typer.Typer(no_args_is_help=True, add_completion=False, pretty_exceptions_enable=False)
qa_app = typer.Typer(no_args_is_help=True, help="Continuity QA: compare against the locked pictures.")
app.add_typer(qa_app, name="qa")


def say(value) -> None:
    print(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2))


def show(report: checks.Report) -> None:
    for item in report.errors:
        say(f"ERROR   {item}")
    for item in report.warnings:
        say(f"WARNING {item}")
    if report.info:
        say(report.info)
    say("CHECK PASSED" if report.ok else f"CHECK FAILED: {len(report.errors)} error(s)")


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        app()
    except (GateError, MoneyError, ProviderError, ValueError) as error:
        print(f"STOP: {error}")
        raise SystemExit(1)


# ---- episode and gates ---------------------------------------------------------------
@app.command()
def new(episode: str, brief: str = "", mock: bool = typer.Option(False, help="Free rehearsal: placeholder media, no Higgsfield calls"),
        quality: str = typer.Option("1080p", help="720p: shoot takes at 720p and use the picked take as the final (tests). 1080p: 480p drafts, then 1080p"),
        provider: str = typer.Option("", help="cli (Higgsfield plan credits, default) or rest (pay-as-you-go API key). Default: REELS_PROVIDER in .env, else cli")):
    """Creates an episode folder."""
    ep = Episode(episode)
    chosen = provider or config.default_provider()
    if chosen not in config.PROVIDERS:
        raise GateError(f"--provider is one of: {', '.join(config.PROVIDERS)}")
    ep.create(brief, mock=mock, quality=quality, provider=chosen)
    say(f"Created {ep.dir} (spends {config.UNITS[chosen]} through Higgsfield {chosen.upper()})" + (" (MOCK: nothing here is real footage)" if mock else ""))


@app.command()
def status(episode: str):
    """Where the episode stands: gates, money, jobs in flight."""
    ep = Episode(episode)
    studio = Studio(ep)
    stale = {g: ep.gate_status(g)[1] for g in GATES if ep.gate_status(g)[0] == "stale"}
    running = [j["label"] for j in studio.ledger.jobs(ep.name, states=("queued", "in_progress", "submission_unknown", "submitting"))]
    say({"episode": ep.name, "mock": studio.mock, "provider": ep.provider, "unit": ep.unit, "gates": ep.summary(), "changed_since_approval": stale, "money": studio.ledger.summary(ep.name), "jobs_in_flight": running})


@app.command()
def check(episode: str, gate: str):
    """Runs the craft rules for a gate. Fix every ERROR before showing the user."""
    report = checks.CHECKS[gate](Episode(episode))
    show(report)
    raise typer.Exit(0 if report.ok else 1)


@app.command("review")
def review_book(episode: str, gate: str):
    """Builds the PDF review book for a gate."""
    path = review.BOOKS[gate](Episode(episode))
    say(f"Review book: {path.resolve()}")


@app.command()
def approve(episode: str, gate: str, text: str = typer.Option(..., help="the user's own words, verbatim")):
    """Records the user's approval of a gate and freezes its files."""
    ep = Episode(episode)
    report = checks.CHECKS[gate](ep)
    if not report.ok:
        show(report)
        raise GateError(f"Gate '{gate}' still has errors. Fix them before recording an approval.")
    ep.approve(gate, text, checks.frozen_files(ep, gate))
    say(f"Gate '{gate}' approved and locked.")


# ---- money ----------------------------------------------------------------------------
@app.command()
def quote(episode: str, bucket: str, takes: int = config.DEFAULT_TAKES):
    """Works out the cost of a stage (prep, draft or final) for the user to approve."""
    say(Studio(Episode(episode)).quote(bucket, takes))


@app.command()
def money(episode: str, bucket: str, text: str = typer.Option(..., help="the user's own words, verbatim"),
          cap: str = typer.Option("", help="Only when the user named a new ceiling for this budget, e.g. a top-up for redos: the new total in the episode's unit (credits or US dollars)")):
    """Records the user's approval of a quoted budget, or of a new ceiling they named."""
    quote_data = Studio(Episode(episode)).approve_money(bucket, text, cap if isinstance(cap, str) and cap else None)
    say(f"'{bucket}' approved up to {fmt(quote_data['cap'], quote_data['unit'])}.")


@app.command()
def collect(episode: str, wait: int = 600):
    """Fetches finished pictures and clips. Safe to run again and again."""
    result = Studio(Episode(episode)).collect(wait)
    say(result)
    if result["unknown"]:
        say("STOP: these submissions have an unknown outcome. Do not resubmit. Check with the user on higgsfield.ai (or `higgsfield generate list`): " + ", ".join(result["unknown"]))


# ---- gate 2: pictures --------------------------------------------------------------------
def _studio(episode: str, need: str | None = None) -> tuple[Episode, Studio]:
    ep = Episode(episode)
    if need:
        ep.require(need)
    return ep, Studio(ep)


@app.command("find-photos")
def find_photos(episode: str, query: str, n: int = 12):
    """Searches Wikimedia Commons for real photos of a place. Free. Look at the contact sheet it prints."""
    ep = Episode(episode)
    ep.require("story")
    sheet = photos.find(ep, query, n)
    say({"contact_sheet": str(sheet.resolve()), "details": str((sheet.parent / "found.json").resolve()), "next": f"reels use-photo {episode} <location> refs/_found/.../NN.jpg"})


@app.command("use-photo")
def use_photo(episode: str, location: str, found_file: str):
    """Adopts a search result as a real reference for a location, with its source and licence."""
    say(f"Filed as {photos.use(Episode(episode), location, found_file)}")


@app.command("add-photo")
def add_photo(episode: str, location: str, file: str, source_url: str = typer.Option(...), author: str = typer.Option(...), licence: str = typer.Option(...), note: str = ""):
    """Files a photo from anywhere else (the user's phone, a client's shop) as a real reference. Give an absolute path."""
    say(f"Filed as {photos.add(Episode(episode), location, Path(file), source_url, author, licence, note)}")


@app.command("voice-test")
def voice_test(episode: str, a: str = "老細，一碗雲吞麵，走青，快啲得唔得呀？", b: str = "後生仔，急咩啫，等陣啦。"):
    """Step 0: one 5-second draft to hear whether the model speaks natural Cantonese (about 15 credits, or US$0.59 on REST)."""
    ep, studio = _studio(episode)
    body = {"prompt": prompts.voice_test(a, b), "duration": 5, "aspect_ratio": config.ASPECT, "generate_audio": True, "draft": True}
    studio.start("prep", "voice-test", "video", config.VIDEO_TEXT, body, "voice-test/voice-test.mp4", hint={"duration": 5})
    say("Submitted. Run: reels collect " + episode)


@app.command()
def cast(episode: str, character: str, n: int = 4, note: str = ""):
    """Casting: n candidate faces for a fictional character."""
    ep, studio = _studio(episode, "story")
    person = plan.bible(ep).character(character)
    folder = ep.path("bible", "characters", character)
    first = max((int(p.name.split("-")[1].split(".")[0]) for p in folder.glob("cast-*.request.json")), default=0)
    for index in range(first + 1, first + n + 1):
        studio.image(f"cast/{character}/{index}", prompts.casting(person, note), [], f"bible/characters/{character}/cast-{index}.png", "3:4")
    say(f"Submitted {n} casting pictures. Run: reels collect {episode}")


@app.command()
def pick(episode: str, character: str, choice: str):
    """Locks the face the user chose. choice is the letter or number from the review book (B or 2)."""
    ep, studio = _studio(episode, "story")
    number = ord(choice.upper()) - 64 if choice.isalpha() else int(choice)
    candidates = plan.candidates(ep, character)
    if not 1 <= number <= len(candidates):
        raise GateError(f"No candidate {choice} for {character}; there are {len(candidates)}")
    shutil.copyfile(candidates[number - 1], ep.path("bible", "characters", character, "face.png"))
    studio.set_ref("characters", character, "face", f"bible/characters/{character}/face.png")
    say(f"{character}: face locked to {candidates[number - 1].name}. Next: reels body {episode} {character}")


@app.command()
def likeness(episode: str, character: str, photo: str, note: str = ""):
    """Real-person path: builds the locked face from a photo. Needs the consent note first."""
    ep, studio = _studio(episode, "story")
    person = plan.bible(ep).character(character)
    if not person.real_person or not ep.exists(person.real_person.consent):
        raise GateError(f"{character}: set real_person in bible.json and write the consent note before uploading anyone's photo")
    studio.image(f"likeness/{character}", prompts.likeness(person, note), [photo], f"bible/characters/{character}/face.png", "3:4")
    studio.set_ref("characters", character, "face", f"bible/characters/{character}/face.png")
    say(f"Submitted. Run: reels collect {episode}")


@app.command()
def body(episode: str, character: str, note: str = ""):
    """Full-body costume picture from the locked face."""
    ep, studio = _studio(episode, "story")
    person = plan.bible(ep).character(character)
    if not ep.exists(person.refs.get("face", "")):
        raise GateError(f"{character}: lock a face first (reels pick, or reels likeness)")
    studio.image(f"body/{character}", prompts.body(person, note), [person.refs["face"]], f"bible/characters/{character}/body.png", "9:16")
    studio.set_ref("characters", character, "body", f"bible/characters/{character}/body.png")
    say(f"Submitted. Run: reels collect {episode}")


@app.command()
def turn(episode: str, character: str, redo: str = typer.Option("", help="One side view to make again: l90, l45, r45 or r90"), note: str = ""):
    """Five-angle face lock. First run makes the four side views; after collecting, run again to build the sheet every shot carries."""
    from PIL import Image
    ep, studio = _studio(episode, "story")
    person = plan.bible(ep).character(character)
    if not ep.exists(person.refs.get("face", "")):
        raise GateError(f"{character}: lock a face first (reels pick, or reels likeness)")
    if redo and redo not in prompts.TURN:
        raise GateError(f"--redo is one of: {', '.join(prompts.TURN)}")
    folder = f"bible/characters/{character}"
    refs = [person.refs["face"]] + ([person.refs["body"]] if ep.exists(person.refs.get("body", "")) else [])
    wanted = [redo] if redo else [v for v in prompts.TURN if not ep.exists(f"{folder}/turn-{v}.png")]
    for view in wanted:
        studio.image(f"turn/{character}/{view}", prompts.turn(person, view, len(refs) > 1, note), refs, f"{folder}/turn-{view}.png", "3:4")
    if wanted:
        say(f"Submitted {len(wanted)} side view(s). Run: reels collect {episode}, look at them, then run this command again to build the sheet.")
        return
    # Three across, two down: left profile, left 45, front / right 45, right profile. One picture, so one reference slot.
    wide, high = 640, 853
    sheet = Image.new("RGB", (wide * 3, high * 2), (128, 128, 128))
    tiles = [f"{folder}/turn-l90.png", f"{folder}/turn-l45.png", person.refs["face"], f"{folder}/turn-r45.png", f"{folder}/turn-r90.png"]
    for index, tile in enumerate(tiles):
        sheet.paste(Image.open(ep.path(tile)).convert("RGB").resize((wide, high)), ((index % 3) * wide, (index // 3) * high))
    sheet.save(ep.path(folder, "turn.png"))
    studio.set_ref("characters", character, "turn", f"{folder}/turn.png")
    say(f"{character}: five-angle sheet built.")


@app.command()
def revise(episode: str, kind: str, key: str, slot: str, note: str = typer.Option(..., help="The one change, in the user's words"), photo: str = ""):
    """Keeps a locked picture as it is and changes one thing. --photo is a real photo (inside the episode folder) of what to put in."""
    from PIL import Image
    ep, studio = _studio(episode, "story")
    bible = plan.bible(ep)
    finder = {"characters": bible.character, "locations": bible.location, "props": bible.prop}
    if kind not in finder:
        raise GateError("kind is one of: characters, locations, props")
    current = finder[kind](key).refs.get(slot, "")
    if not ep.exists(current):
        raise GateError(f"{kind}/{key} has no '{slot}' picture to revise")
    if photo and not ep.exists(photo):
        raise GateError(f"{photo} does not exist inside the episode folder")
    width, height = Image.open(ep.path(current)).size
    shapes = {"3:4": 3 / 4, "9:16": 9 / 16, "16:9": 16 / 9, "1:1": 1.0}
    aspect = min(shapes, key=lambda name: abs(shapes[name] - width / height))
    studio.image(f"revise/{kind}/{key}/{slot}", prompts.revise(note, bool(photo)), [current] + ([photo] if photo else []), current, aspect)
    say(f"Submitted. Run: reels collect {episode}")


@app.command()
def voice(episode: str, character: str, line: str = typer.Option(..., help="A Cantonese line in this character's manner")):
    """Voice audition: a 5-second draft of the locked face speaking, for the user to hear."""
    ep, studio = _studio(episode, "story")
    person = plan.bible(ep).character(character)
    if not ep.exists(person.refs.get("face", "")):
        raise GateError(f"{character}: lock a face first")
    folder = ep.path("bible", "characters", character)
    index = len(list(folder.glob("voice-*.request.json"))) + 1
    # Once a voice is locked, auditions carry the sample, so the user hears whether the model really follows it.
    sample = f"bible/characters/{character}/voice.wav"
    timbre = f" Use the voice timbre of {config.AUDIO_TAG.format(n=1)} for {character.upper()}: the same person speaking." if ep.exists(sample) else ""
    text = (f"{prompts.tag(1)} is {character.upper()}'s face. Photoreal live action, vertical 9:16, medium close-up, handheld, almost still, plain interior, soft daylight. "
            f"{person.look} Voice: {person.voice}{timbre} {character.upper()} speaks to someone just off camera in natural colloquial Hong Kong Cantonese: {{{line}}} "
            "AUDIO: Hong Kong Cantonese (粵語), never Mandarin. Quiet room tone. No music. No subtitles or on-screen text.")
    body_data = {"prompt": text, "image_urls": [studio.url(person.refs["face"])], "duration": 5, "aspect_ratio": config.ASPECT, "generate_audio": True, "draft": True}
    if timbre:
        body_data["audio_urls"] = [studio.url(sample)]
    studio.start("prep", f"voice/{character}/{index}", "video", config.VIDEO, body_data, f"bible/characters/{character}/voice-{index}.mp4", hint={"duration": 5})
    write_json(folder / f"voice-{index}.request.json", {"prompt": text, "line": line})
    say(f"Submitted. Run: reels collect {episode}")


@app.command("voice-lock")
def voice_lock(episode: str, character: str, audition: int = typer.Argument(0, help="The audition number the user approved"),
               file: str = typer.Option("", help="Instead of an audition: a recording of the real voice, inside the episode folder"),
               start: float = -1.0, end: float = -1.0):
    """Locks a voice: cuts the sample every later clip will carry, from an audition the user approved or from a real recording."""
    ep = Episode(episode)
    source = ep.path(file) if file else ep.path("bible", "characters", character, f"voice-{audition}.mp4")
    if not source.is_file():
        raise GateError(f"{file or source.name} does not exist")
    if file:  # a real recording: use all of it, up to the 30 seconds the model takes
        start, end = max(start, 0.0), end if end > 0 else min(edit.probe(source)["duration"], 30.0)
    else:  # an audition is 5 seconds: trim the silence at both ends
        start, end = start if start >= 0 else 0.3, end if end > 0 else 4.7
    cut_wav(source, ep.path("bible", "characters", character, "voice.wav"), start, end)
    say(f"{character}: voice locked from {file or f'audition {audition}'} ({end - start:.1f}s).")


@app.command()
def place(episode: str, location: str, view: str = typer.Option(..., help="Where the master camera stands and looks, in words"), reverse_view: str = "", note: str = ""):
    """Builds the locked master picture of a location from its real photos (and the reverse view if asked)."""
    ep, studio = _studio(episode, "story")
    spot = plan.bible(ep).location(location)
    if not spot.real_refs:
        raise GateError(f"{location}: add real photos to real_refs first, or ask the user for one")
    refs = spot.real_refs[:4]
    master = f"bible/locations/{location}/master.png"
    if not reverse_view or not ep.exists(spot.refs.get("master", "")):
        studio.image(f"place/{location}/master", prompts.location(spot, len(refs), view, note), refs, master, "16:9")
        studio.set_ref("locations", location, "master", master)
    if reverse_view:
        if not ep.exists(master):
            say(f"Master submitted. After collecting it, run this command again to build the reverse view.")
            return
        studio.image(f"place/{location}/reverse", prompts.reverse(spot, reverse_view, note), [master], f"bible/locations/{location}/reverse.png", "16:9")
        studio.set_ref("locations", location, "reverse", f"bible/locations/{location}/reverse.png")
    say(f"Submitted. Run: reels collect {episode}")


@app.command()
def prop(episode: str, item: str, photo: str = "", note: str = ""):
    """Builds the locked picture of a prop, from a real photo when there is one."""
    ep, studio = _studio(episode, "story")
    thing = plan.bible(ep).prop(item)
    studio.image(f"prop/{item}", prompts.prop(thing, bool(photo), note), [photo] if photo else [], f"bible/props/{item}/sheet.png", "1:1")
    studio.set_ref("props", item, "sheet", f"bible/props/{item}/sheet.png")
    say(f"Submitted. Run: reels collect {episode}")


@app.command()
def adopt(episode: str, kind: str, key: str, slot: str, file: str):
    """Uses an existing picture as a locked reference, e.g. a real photo as a location master. Free."""
    ep, studio = _studio(episode, "story")
    if kind not in ("characters", "locations", "props"):
        raise GateError("kind is one of: characters, locations, props")
    source = ep.path(file)
    if not source.is_file():
        raise GateError(f"{file} does not exist inside the episode folder")
    target = f"bible/{kind}/{key}/{slot}{source.suffix.lower()}"
    ep.path(target).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, ep.path(target))
    studio.set_ref(kind, key, slot, target)
    say(f"{kind}/{key}: {slot} now points at {target}")


# ---- gate 3: angles ------------------------------------------------------------------------
@app.command()
def anchor(episode: str, only: str = typer.Option("", help="location/setup to redo, e.g. cafe/a-cu"), note: str = "",
           base: str = "", photo: str = ""):
    """Generates the anchor frame for every camera setup that has none yet.
    --base (with --only and --note) keeps a picture inside the episode folder and changes one thing in it, instead of drawing the frame again:
    the current frame, or a 9:16 crop of a locked view. --photo adds a real photo of the thing to put in."""
    ep, studio = _studio(episode, "lock")
    report = checks.check_shots(ep, anchors=False)
    if not report.ok:
        show(report)
        raise GateError("Fix shots.json before spending on anchor frames.")
    bible, shots, sent = plan.bible(ep), plan.shots(ep), []
    for clip in shots.clips:
        for shot in clip.shots:
            name = f"{clip.location}/{shot.setup}"
            target = plan.anchor_path(clip.location, shot.setup)
            if name in sent or (only and name != only) or (not only and ep.exists(target)):
                continue
            if base:
                if not (only and note.strip()) or not ep.exists(base) or (photo and not ep.exists(photo)):
                    raise GateError("--base needs --only, --note (the one change) and pictures that exist inside the episode folder")
                text, people = prompts.anchor_edit(bible, shot, note, bool(photo))
                refs = [base] + ([photo] if photo else []) + people
            else:
                text, refs = prompts.anchor(bible, clip, shot, note)
            studio.image(f"anchor/{name}", text, refs, target, "9:16")
            sent.append(name)
    say(f"Submitted {len(sent)} anchor frame(s): {', '.join(sent) or 'none needed'}. Run: reels collect {episode}")


@app.command()
def prompt(episode: str, clip: str):
    """Prints the exact request a clip would send. Free: read it before quoting."""
    ep = Episode(episode)
    say(Studio(ep).clip_request(clip)[1])


# ---- gate 4: takes -----------------------------------------------------------------------------
@app.command()
def shoot(episode: str, clip: str = "", takes: int = config.DEFAULT_TAKES):
    """Submits 480p draft takes. With --clip it adds takes to that clip only (a retake)."""
    ep, studio = _studio(episode, "angles")
    targets = [clip] if clip else [c.id for c in plan.shots(ep).clips]
    for target in targets:
        for _ in range(takes):
            job = studio.shoot(target)
            say(f"submitted {job['label']}")
    say(f"Run: reels collect {episode}")


@app.command()
def select(episode: str, picks: list[str] = typer.Argument(..., help="clip=take, e.g. c01=2 c02=1")):
    """Writes down the takes the user picked."""
    ep = Episode(episode)
    ep.require("angles")
    chosen = {p.split("=")[0]: int(p.split("=")[1].lower().lstrip("t")) for p in picks}
    write_json(ep.path("takes", "selection.json"), {**checks.selection(ep), **chosen})
    say(checks.selection(ep))


@app.command()
def finalize(episode: str):
    """Turns each picked draft into its 1080p version."""
    ep, studio = _studio(episode, "takes")
    for clip in checks.selection(ep):
        if not ep.exists(f"finals/{clip}.mp4"):
            say(f"submitted {studio.finalize(clip)['label']}")
    say(f"Run: reels collect {episode}")


# ---- QA ------------------------------------------------------------------------------------------
@qa_app.command("prepare")
def qa_prepare(episode: str, stage: str = typer.Argument(..., help="anchors, takes or finals"), redo: bool = False):
    """Builds the comparison sheets and blank verdicts the QA agent fills in."""
    ep = Episode(episode)
    shots, made = plan.shots(ep), []
    for clip in shots.clips:
        if stage == "anchors":
            seen = set()
            for shot in clip.shots:
                media = plan.anchor_path(clip.location, shot.setup)
                if media not in seen and qa.needs_prepare(ep, media, redo):
                    made.append(str(qa.prepare_anchor(ep, clip.id, shot.id)))
                seen.add(media)
        else:
            videos = sorted(ep.path("takes", clip.id).glob("t*.mp4")) if stage == "takes" else [ep.path("finals", f"{clip.id}.mp4")]
            for video in videos:
                media = video.relative_to(ep.dir).as_posix()
                if qa.needs_prepare(ep, media, redo):
                    made.append(str(qa.prepare_clip(ep, media, clip.id)))
    say({"verdicts_to_fill": made, "checks": qa.SHOT_CHECKS})


@qa_app.command("record")
def qa_record(episode: str, media: str):
    """Settles a filled-in verdict as pass or fail."""
    verdict = qa.record(Episode(episode), media)
    say({"media": media, "result": verdict["result"], "failed": verdict.get("failed", []), "fix": verdict["fix"]})


@qa_app.command("override")
def qa_override(episode: str, media: str, text: str = typer.Option(..., help="the user's own words, verbatim")):
    """The user accepts something QA failed."""
    qa.override(Episode(episode), media, text)
    say(f"{media}: accepted on the user's word.")


# ---- gate 5: the cut ---------------------------------------------------------------------------------
def _timeline(ep: Episode, draft: bool, upscaled: bool = False) -> tuple[list[dict], list[captions.Cue], int]:
    story, shots, picks = plan.story(ep), plan.shots(ep), checks.selection(ep)
    text = {l.id: l.text for l in story.lines}
    parts, cues, clock, heard = [], [], 0.0, 0
    for clip in shots.clips:
        media = f"takes/{clip.id}/t{picks.get(clip.id)}.mp4" if draft else f"finals/{clip.id}.mp4"
        if upscaled and not draft and not ep.exists(media):  # cheapest route: Kie 4K straight from the picked 480p take, no 1080p pass
            media = f"takes/{clip.id}/t{picks.get(clip.id)}.mp4"
        video = f"upscale/{clip.id}.mp4" if upscaled else media  # the 4K copy plays; timing still comes from the original's speech check
        if not ep.exists(media) or not ep.exists(video):
            raise GateError(f"{video if ep.exists(media) else media} is missing" + (". Run: reels upscale" if upscaled else ""))
        length = min(edit.probe(ep.path(video))["duration"], clip.duration)
        parts.append({"path": ep.path(video), "end": length})
        timing = captions.planned([(clock + s.start, clock + s.end, [(k, text[k]) for k in s.lines]) for s in clip.shots if s.lines])
        heard_path = ep.path(media).with_suffix(".speech.json")
        if heard_path.exists():  # where a line was clearly heard, use the real timing
            for key, hit in read_json(heard_path)["lines"].items():
                if key in timing and hit["score"] >= config.SPEECH_PASS_SCORE and hit["start"] is not None:
                    timing[key] = (clock + max(0, hit["start"] - 0.05), min(clock + length, clock + hit["end"] + 0.25))
                    heard += 1
        for key, (start, end) in sorted(timing.items(), key=lambda item: item[1]):
            cues += captions.split_line(text[key], start, end)
        clock += length
    for before, after in zip(cues, cues[1:]):  # captions never overlap
        if after.start < before.end:
            before.end = max(before.start + 0.3, after.start)
    return parts, cues, heard


@app.command()
def cut(episode: str, draft: bool = typer.Option(False, help="Cut the picked 480p takes instead of the 1080p finals"),
        upscaled: bool = typer.Option(False, help="Cut the 4K copies made by: reels upscale")):
    """Joins the clips, levels the sound and burns the captions."""
    ep = Episode(episode)
    ep.require("takes")
    upscaled = upscaled is True  # also called as a plain function (demo, tests), where the default is typer's Option object
    parts, cues, heard = _timeline(ep, draft, upscaled)
    size = config.UPSCALED_SIZE if upscaled else config.DRAFT_SIZE if draft or ep.state.get("quality") == "720p" else config.FINAL_SIZE
    name = "final-4k" if upscaled else "draft" if draft else "final"
    out = ep.path("out")
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.ass").write_text(captions.ass(cues, size), encoding="utf-8")
    (out / f"{name}.srt").write_text(captions.srt(cues), encoding="utf-8")
    music = next(iter(sorted(ep.dir.glob("music.*"))), None)
    length = edit.join(parts, out / f"{name}.mp4", size, captions=out / f"{name}.ass", music=music)
    say({"video": str((out / f"{name}.mp4").resolve()), "seconds": length, "captions": len(cues), "music": bool(music),
         "caption_timing": f"{heard} line(s) timed from the actual speech, the rest from the shot plan"})


# ---- free checks ----------------------------------------------------------------------------------------
@app.command()
def preflight(provider: str = typer.Option("", help="cli or rest. Default: REELS_PROVIDER in .env, else cli")):
    """Free checks before any paid work: login, plan, credits, and that Higgsfield accepts every request shape the engine sends. Spends nothing."""
    chosen = provider or config.default_provider()
    cases = lambda picture, voice: {  # noqa: E731  (the same shapes the engine sends)
        "clip draft 480p (6s)": (config.VIDEO, {"prompt": "A man speaks.", "image_urls": [picture], "duration": 6, "aspect_ratio": config.ASPECT, "generate_audio": True, "draft": True}),
        "clip draft, 2 pictures + 2 voices": (config.VIDEO, {"prompt": "Two people talk.", "image_urls": [picture, picture], "audio_urls": [voice, voice], "duration": 6,
                                                             "aspect_ratio": config.ASPECT, "generate_audio": True, "draft": True}),
        "clip 1080p (6s)": (config.VIDEO, {"prompt": "A man speaks.", "image_urls": [picture], "duration": 6, "aspect_ratio": config.ASPECT, "generate_audio": True, "draft": False, "resolution": "1080p"}),
        "voice test (5s)": (config.VIDEO_TEXT, {"prompt": "A man speaks.", "duration": 5, "aspect_ratio": config.ASPECT, "generate_audio": True, "draft": True}),
        "picture from text": (config.IMAGE_T2I, {"prompt": "A portrait.", "resolution": config.IMAGE_RESOLUTION, "aspect_ratio": "3:4"}),
        "picture from references": (config.IMAGE_EDIT, {"prompt": "A portrait.", "image_urls": [picture], "resolution": config.IMAGE_RESOLUTION, "aspect_ratio": config.ASPECT}),
    }
    failed = 0
    if chosen == "rest":
        from .higgsfield import RestProvider, load_key
        live = RestProvider(load_key(repo_root()))
        picture = "https://upload.wikimedia.org/wikipedia/commons/4/47/PNG_transparency_demonstration_1.png"  # any public file; only its URL is sent
        shapes = cases(picture, picture.replace(".png", ".wav"))
        shapes.pop("clip draft, 2 pictures + 2 voices")
    else:
        from PIL import Image

        from .higgsfield import CliProvider, cli_path
        say(f"Higgsfield CLI: {cli_path()}")
        live = CliProvider()
        account = live.account()  # stops with the login instruction when the user is not logged in
        plan_type = str(account.get("subscription_plan_type") or "").lower()
        say(f"Plan: {plan_type or 'unknown'}   Credits left: {account.get('credits')}")
        if plan_type not in config.CLI_MIN_PLANS:
            failed += 1
            say(f"FAIL  plan '{plan_type}': the engine needs Higgsfield Plus or above (Free cannot use the CLI, Starter has no Seedance 2.5). Plans: {config.HIGGSFIELD_PLANS}")
        folder = repo_root() / ".data" / "preflight"
        folder.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (720, 1280), (90, 96, 104)).save(folder / "picture.png")
        edit.run(["-f", "lavfi", "-i", "sine=frequency=220:duration=3", "-ac", "1", "-ar", "44100", str(folder / "voice.wav")])
        shapes = cases(live.upload(folder / "picture.png"), live.upload(folder / "voice.wav"))  # uploads are free
    for name, (model, body) in shapes.items():
        try:
            say(f"OK    {name}: {fmt(live.estimate(model, body), config.UNITS[chosen])}")
        except ProviderError as error:
            failed += 1
            say(f"FAIL  {name}: {error}")
    say("PREFLIGHT PASSED. Nothing was spent." if not failed else f"STOP: {failed} check(s) failed. Do not start paid work; show the user the lines above.")
    raise typer.Exit(1 if failed else 0)


# ---- 4K upscale on Kie AI ------------------------------------------------------------------------------
@app.command()
def upscale(episode: str, text: str = typer.Option("", help="The user's own words approving the Kie quote. Without it, only the quote is made."),
            wait: int = 900):
    """4K upscale of the picked clips on Kie AI (US$0.03 a second). Run once for the quote, show the user, run again with --text."""
    from decimal import Decimal

    from .kie import Kie, load_key
    ep, studio = _studio(episode, "takes")
    folder, picks = ep.path("upscale"), checks.selection(ep)
    folder.mkdir(exist_ok=True)
    jobs = {j["label"]: j for j in studio.ledger.jobs(ep.name, states=("completed",))}
    sources = {}
    for clip, take in picks.items():
        job = jobs.get(f"{clip}/final") or jobs.get(f"{clip}/t{take}")  # 1080p final, or the picked take when it is the final (720p episodes)
        if not job or not job["outputs"]:
            raise GateError(f"{clip}: no finished clip with a download link yet. Finalize and collect first.")
        local = ep.path("finals", f"{clip}.mp4") if ep.exists(f"finals/{clip}.mp4") else ep.path("takes", clip, f"t{take}.mp4")
        sources[clip] = {"url": job["outputs"][0], "seconds": round(edit.probe(local)["duration"], 2)}
    seconds = sum(s["seconds"] for s in sources.values())
    quote = {"unit": "US$", "seconds": seconds, "cap": str((Decimal(str(seconds)) * config.KIE_UPSCALE_PER_SECOND).quantize(Decimal("0.01"))),
             "clips": sorted(sources), "inputs": sha(ep.path("takes", "selection.json"))}
    record = folder / "tasks.json"
    tasks = read_json(record) if record.exists() else {}
    if not text.strip():
        write_json(ep.path("money", "upscale.json"), quote)
        say(f"Kie 4K upscale: {len(sources)} clips, {seconds:.0f} s, about US${quote['cap']}. Show the user; if they approve, run again with --text \"<their words>\".")
        return
    saved = read_json(ep.path("money", "upscale.json")) if ep.exists("money/upscale.json") else None
    if not saved or saved["inputs"] != quote["inputs"]:
        raise GateError("No current upscale quote. Run reels upscale without --text, show the user the number, then run again.")
    if not tasks:
        ep.log(f"Kie upscale approved, about US${saved['cap']}, by the user: 「{text.strip()}」")
    kie = Kie(load_key())
    for clip, source in sources.items():
        if (folder / f"{clip}.mp4").exists() or tasks.get(clip, {}).get("state") in ("running", "done"):
            continue
        tasks[clip] = {"task": kie.submit(source["url"]), "state": "running"}
        write_json(record, tasks)  # saved at once: a lost task id is a paid job nobody can collect
    deadline = time.time() + wait
    while any(t["state"] == "running" for t in tasks.values()) and time.time() < deadline:
        for clip, task in tasks.items():
            if task["state"] != "running":
                continue
            state = kie.status(task["task"])
            if state["state"] == "done":
                kie.download(state["url"], folder / f"{clip}.mp4")
                task["state"] = "done"
            elif state["state"] == "failed":
                task.update(state="failed", error=state["error"])
            write_json(record, tasks)
        time.sleep(10)
    say({clip: t["state"] + (f" ({t.get('error')})" if t["state"] == "failed" else "") for clip, t in tasks.items()})
    if any(t["state"] == "failed" for t in tasks.values()):
        say("Some clips failed on Kie (often 'service is busy'). Tell the user; rerunning this command resubmits only those.")
        for task in tasks.values():
            if task["state"] == "failed":
                task["state"] = "retry"
        write_json(record, tasks)
    elif all((folder / f"{c}.mp4").exists() for c in sources):
        say(f"All clips are 4K in {folder.resolve()}. Next: reels cut {episode} --upscaled")


# ---- free rehearsal -----------------------------------------------------------------------------------
@app.command()
def demo():
    """Walks all five gates with placeholder media. Spends nothing, calls nobody. Proves the install works."""
    from datetime import datetime

    from PIL import Image, ImageDraw
    # A fresh folder every run: OneDrive holds handles on synced folders, so deleting an old one is unreliable.
    episode = f"demo-{datetime.now():%m%d-%H%M%S}"
    ep = Episode(episode)
    ep.create("Free rehearsal of the shipped lock-test example. Every picture and clip is a placeholder.", mock=True)
    for name in ("story.json", "bible.json", "shots.json"):
        shutil.copyfile(repo_root() / "examples" / "lock-test" / name, ep.path(name))
    word = "(rehearsal, no real approval)"

    def qa_pass(media):
        verdict = read_json(qa.verdict_path(ep, media))
        for answers in verdict["shots"].values():
            answers.update({k: "pass" for k in answers if k != "notes"})
        verdict["summary"] = "彩排：自動當過"
        write_json(qa.verdict_path(ep, media), verdict)
        qa.record(ep, media)

    review_book(episode, "story")
    approve(episode, "story", text=word)
    quote(episode, "prep", takes=config.DEFAULT_TAKES)
    money(episode, "prep", text=word)
    bible = plan.bible(ep)
    for spot in bible.locations:
        picture = Image.new("RGB", (960, 640), (96, 104, 92))
        ImageDraw.Draw(picture).text((40, 40), "MOCK real photo", fill="white")
        picture.save(ep.path("mock-photo.jpg"))
        photos.add(ep, spot.id, ep.path("mock-photo.jpg"), "mock", "mock", "mock")
    for person in bible.characters:
        cast(episode, person.id, n=4, note="")
    collect(episode, wait=60)
    review_book(episode, "lock")
    shutil.copyfile(ep.path("review", "2-lock.pdf"), ep.path("review", "2-lock-casting.pdf"))
    for person in bible.characters:
        pick(episode, person.id, "B")
        body(episode, person.id, note="")
        turn(episode, person.id, redo="", note="")
    for spot in bible.locations:
        place(episode, spot.id, view="Wide view from the main camera side.", reverse_view="", note="")
    for thing in bible.props:
        prop(episode, thing.id, photo="", note="")
    collect(episode, wait=60)
    for person in bible.characters:
        turn(episode, person.id, redo="", note="")
    review_book(episode, "lock")
    approve(episode, "lock", text=word)
    anchor(episode, only="", note="")
    collect(episode, wait=60)
    qa_prepare(episode, "anchors", redo=False)
    shots = plan.shots(ep)
    for media in sorted({plan.anchor_path(c.location, s.setup) for c in shots.clips for s in c.shots}):
        qa_pass(media)
    quote(episode, "draft", takes=config.DEFAULT_TAKES)
    review_book(episode, "angles")
    approve(episode, "angles", text=word)
    money(episode, "draft", text=word)
    shoot(episode, clip="", takes=config.DEFAULT_TAKES)
    collect(episode, wait=120)
    qa_prepare(episode, "takes", redo=False)
    for clip in shots.clips:
        for take in range(1, config.DEFAULT_TAKES + 1):
            qa_pass(f"takes/{clip.id}/t{take}.mp4")
    review_book(episode, "takes")
    select(episode, [f"{c.id}=1" for c in shots.clips])
    approve(episode, "takes", text=word)
    quote(episode, "final", takes=config.DEFAULT_TAKES)
    money(episode, "final", text=word)
    finalize(episode)
    collect(episode, wait=120)
    qa_prepare(episode, "finals", redo=False)
    for clip in shots.clips:
        qa_pass(f"finals/{clip.id}.mp4")
    cut(episode, draft=False)
    review_book(episode, "final")
    approve(episode, "final", text=word)
    say(f"REHEARSAL COMPLETE. Nothing was spent. Review books: {ep.path('review').resolve()}  Film: {ep.path('out', 'final.mp4').resolve()}")


if __name__ == "__main__":
    main()
