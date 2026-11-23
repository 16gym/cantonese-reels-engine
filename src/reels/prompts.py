"""Builds every generation prompt from the locked plan files.

Agents never hand-write a request. They write the bible and the shot plan; this module
turns those into prompts and attaches the locked pictures. A clip therefore cannot be
generated without its character, location and prop references. That is the lock.
"""
import re

from . import checks, config
from .plan import Bible, Clip, Story

REAL = ("Photoreal live-action frame, shot on location in Hong Kong with a real camera. Real skin: pores, uneven tone, small blemishes, "
        "no beauty filter, no retouching. Ordinary-looking people, not models. Available and practical light only. "
        "Not CGI, not an illustration, not a render. No text, captions, subtitles, watermarks or logos anywhere in the image.")


def tag(n: int) -> str:
    return config.IMAGE_TAG.format(n=n)


def reference_block(roles: list[str]) -> str:
    return " ".join(f"{tag(i)} is {role}." for i, role in enumerate(roles, 1))


# ---- pictures -------------------------------------------------------------------
def casting(character, note: str = "") -> str:
    return (f"{REAL} Casting photograph for a Hong Kong drama. Head and shoulders, facing the camera, neutral relaxed expression, "
            f"plain mid-grey wall behind, soft daylight from a window on one side. {character.look} {note}").strip()


def likeness(character, note: str = "") -> str:
    return (f"{tag(1)} is a real photograph of the person to portray. {REAL} Make a casting photograph of this same person: identical face, "
            f"age, hair and build. Head and shoulders, facing the camera, neutral relaxed expression, plain mid-grey wall, soft daylight from one side. {note}").strip()


def body(character, note: str = "") -> str:
    return (f"{tag(1)} is this person's face: keep the identical face, hair, age and build. {REAL} Full-length photograph, head to shoes in frame, "
            f"standing naturally facing the camera, arms relaxed, plain mid-grey wall, soft even daylight. Wearing exactly: {character.wardrobe} {note}").strip()


# A face is locked from five angles, not one. Named by the side of the face we see.
TURN = {
    "l90": ("左面 90°", "Full left profile. The camera stands at the person's left side: we see only the left side of the face and the left ear, and the nose points toward the LEFT edge of the picture."),
    "l45": ("左面 45°", "Three-quarter view from the person's left: we see mostly the left cheek, both eyes are visible, and the nose points toward the LEFT edge of the picture."),
    "r45": ("右面 45°", "Three-quarter view from the person's right: we see mostly the right cheek, both eyes are visible, and the nose points toward the RIGHT edge of the picture."),
    "r90": ("右面 90°", "Full right profile. The camera stands at the person's right side: we see only the right side of the face and the right ear, and the nose points toward the RIGHT edge of the picture."),
}


def turn(character, view: str, has_body: bool, note: str = "") -> str:
    costume = f" {tag(2)} is their whole body and costume." if has_body else ""
    return (f"{tag(1)} is this person's face seen from the front.{costume} {REAL} The same person in the same session: identical face, age, hair, "
            f"skin, build and glasses if they wear them. Tight head and shoulders only, standing: the head fills more than half the height of the picture. Neutral relaxed expression, eyes looking where the head points, the same plain "
            f"mid-grey wall and soft daylight. {TURN[view][1]} Wearing exactly: {character.wardrobe} {note}").strip()


def revise(note: str, has_photo: bool) -> str:
    extra = f" {tag(2)} is a real photograph of what to put in: copy its shape, colour, material and wear exactly." if has_photo else ""
    return (f"{tag(1)} is the current picture.{extra} {REAL} Reproduce {tag(1)} exactly: the same camera position, framing, objects, materials and light. "
            f"Change only this: {note}").strip()


def anchor_edit(bible, shot, note: str, has_photo: bool) -> tuple[str, list[str]]:
    """A frame made by keeping a picture (the current frame, or a 9:16 crop of a locked view) and changing one thing.
    Returns (prompt, the reference pictures that follow the kept picture and the photo)."""
    roles, paths = [], []
    for name in shot.positions:
        character = bible.character(name)
        roles += [checks.HEAD.format(name=name.upper()), f"{name.upper()}'s whole body and costume"]
        paths += [character.refs["turn"], character.refs["body"]]
    first = 3 if has_photo else 2
    people = " ".join(f"{tag(i)} is {role}." for i, role in enumerate(roles, first))
    return f"{revise(note, has_photo)} {people}".strip(), paths


def location(place, count: int, view: str, note: str = "") -> str:
    photos = "is a real photograph" if count == 1 else "are real photographs"
    return (f"{' and '.join(tag(i) for i in range(1, count + 1))} {photos} of the kind of place to build. Keep their materials, wear, clutter, "
            f"colours and the way light falls. {REAL} Create one specific, consistent location: {place.name}. {place.look} "
            f"Time: {place.time}. Light: {place.light}. No people in frame. {view} {note}").strip()


def reverse(place, view: str, note: str = "") -> str:
    return (f"{tag(1)} is the master view of a location. {REAL} Show the SAME room from the opposite side: {view} Every wall finish, fixture, "
            f"piece of furniture and light source seen in {tag(1)} stays the same object in the same place, now seen from the other direction. "
            f"{place.look} Time: {place.time}. Light: {place.light}. No people in frame. {note}").strip()


def prop(item, has_photo: bool, note: str = "") -> str:
    lead = f"{tag(1)} is a real photograph of the object: reproduce it exactly. " if has_photo else ""
    return (f"{lead}{REAL} A single object photographed on a plain mid-grey surface, three-quarter view, soft daylight, whole object in frame: "
            f"{item.name}. {item.look} {note}").strip()


def anchor(bible: Bible, clip: Clip, shot, note: str = "") -> tuple[str, list[str]]:
    """The first frame of a camera setup: who stands where, seen from where. Returns (prompt, reference paths)."""
    place = bible.location(clip.location)
    plate = shot.camera.plate
    roles = [f"the location '{place.name}' seen from the same side as this frame. It is this exact place: keep its shape, every fixed object and which side each one is on. Do not redesign or mirror it"]
    paths = [place.refs[plate]]
    # One location picture only. A second view from another side leaked its dashboard and its car into the frame (seen on a real episode).
    people = []
    for name in checks.screen_order(place, shot):
        character = bible.character(name)
        roles += [checks.HEAD.format(name=name.upper()), f"{name.upper()}'s whole body and costume"]
        paths += [character.refs["turn"], character.refs["body"]]
        people.append(f"{name.upper()} ({character.look} Wearing: {character.wardrobe})")
    for name in shot.props:
        roles.append(f"the prop {name.upper()}")
        paths.append(bible.prop(name).refs["sheet"])
    order = checks.screen_order(place, shot)
    staging = f"In frame from left to right: {', '.join(n.upper() for n in order)}. " if len(order) > 1 else ""
    geometry = "" if shot.size == "INSERT" else sides_text(checks.frame_sides(place, shot))
    opening = (f"{reference_block(roles)} {REAL} {bible.style} One frame of the film, vertical 9:16. {SIZE[shot.size]} CAMERA: {shot.camera.view} "
               f"Camera height: {shot.camera.height}. {geometry}")
    if shot.size in ("INSERT", "WIDE") and not order:
        # A detail shot: the scene's blocking would pull the frame wide and invite faces in.
        text = (f"{opening}Place: {place.name}, {place.time}. Light: {place.light}. No faces anywhere in the picture. "
                f"What fills the frame: {shot.action} {note}")
    else:
        visible = (f"Exactly {len(order)} {'person is' if len(order) == 1 else 'people are'} visible: {', '.join(n.upper() for n in order)}. "
                   "Nobody else appears anywhere in the picture, not in the background, not in a mirror.") if order else "No people in the picture."
        text = (f"{opening}Place: {place.name}, {place.time}. Light: {place.light}. People: {'; '.join(people) or 'none'}. {visible} {staging}"
                f"Staging: {clip.blocking} The moment: {shot.action} {shot.performance} {note}")
    return " ".join(text.split()), paths


WHERE = {"left": "on the LEFT of the frame", "right": "on the RIGHT of the frame", "middle": "in the middle of the frame",
         "edge-left": "at the far LEFT edge or just out of frame", "edge-right": "at the far RIGHT edge or just out of frame",
         "behind": "behind the camera, not in the picture"}


def sides_text(sides: list[tuple[str, str]], short: bool = False) -> str:
    """The landmark line. Long for a picture, short for a shot inside a clip request."""
    if not sides:
        return ""
    if short:
        return " Sides: " + ", ".join(f"{name} {side.replace('edge-', 'far ').replace('behind', 'behind camera')}" for name, side in sides) + "."
    return ("FIXED GEOMETRY, worked out from the floor plan; the picture is wrong if any of these is mirrored: "
            + "; ".join(f"{name} {WHERE[side]}" for name, side in sides) + ". ")


SIZE = {
    "ECU": "Extreme close-up: one detail of the face fills the frame.",
    "CU": "Close-up: the face fills the frame from chin to hairline.",
    "MCU": "Medium close-up: head and shoulders.",
    "MS": "Medium shot: waist up.",
    "MLS": "Medium long shot: knees up, some of the room visible.",
    "LS": "Long shot: whole body with the room around it.",
    "INSERT": "Insert: a tight detail of a hand or an object.",
    "WIDE": "Wide view of the place itself; no person is featured.",
}


# ---- video ------------------------------------------------------------------------
def clip_prompt(story: Story, bible: Bible, clip: Clip, voices: dict[str, int] | None = None, corrections: list[str] | None = None) -> str:
    """One Seedance request: a few timed shots in one location, with dialogue. `voices` maps character id -> audio reference number."""
    place = bible.location(clip.location)
    line = {l.id: l for l in story.lines}
    roles = [role for role, _ in checks.clip_refs(bible, clip)]
    cast = sorted({n for s in clip.shots for n in s.positions}, key=lambda n: next(i for i, s in enumerate(clip.shots) if n in s.positions))
    people = []
    for name in cast:
        character = bible.character(name)
        voice = f" Voice: {character.voice}" + (f" Use the voice timbre of {config.AUDIO_TAG.format(n=voices[name])}." if voices and name in voices else "")
        people.append(f"{name.upper()}: {character.look} Wearing in every shot: {character.wardrobe}{voice}")
    parts = [
        f"GLOBAL STYLE: {bible.style} Vertical 9:16. Photoreal live action shot on location in Hong Kong. Real skin texture, no beauty filter, natural motion, no slow motion.",
        f"REFERENCES: {reference_block(roles)}",
        f"CHARACTERS: {' '.join(people)}",
        f"LOCATION: {place.name}, exactly as in its reference images. Time: {place.time}. Light: {place.light}. The place does not change between shots.",
        f"BLOCKING: {clip.blocking}",
    ]
    shots = []
    for index, shot in enumerate(clip.shots, 1):
        order = checks.screen_order(place, shot)
        staging = f" In frame left to right: {', '.join(n.upper() for n in order)}." if len(order) > 1 else ""
        speech = []
        for key in shot.lines:
            spoken = line[key]
            where = " (off screen, heard over this shot; nobody visible moves their lips)" if key in shot.offscreen else ""
            delivery = f", {spoken.delivery}" if spoken.delivery else ""
            speech.append(f"{spoken.speaker.upper()} says in Hong Kong Cantonese{delivery}{where}: {{{spoken.say or spoken.text}}}")
        silent = "" if shot.lines else " Nobody speaks; lips stay closed."
        cut = " Hard cut." if index < len(clip.shots) else ""
        landmarks = "" if shot.size == "INSERT" else sides_text(checks.frame_sides(place, shot), short=True)  # a macro shot has no use for them
        shots.append(f"Shot {index} ({shot.start}s-{shot.end}s): {SIZE[shot.size].split(':')[0].rstrip('.')}. {shot.camera.view}{landmarks} Camera {shot.camera.height} height, {shot.camera.move}.{staging} "
                     f"{shot.action} {shot.performance} {' '.join(speech)}{silent}{cut}")
    parts.append("SHOTS: " + " ".join(" ".join(s.split()) for s in shots))
    if corrections:
        parts.append("CORRECTIONS (these fix problems in an earlier take, follow them exactly): " + " ".join(corrections))
    fast = "Fast, clipped delivery, no pauses. " if story.chars_per_second > 5 else ""
    parts.append(f"AUDIO: All speech is natural colloquial Hong Kong Cantonese (粵語), never Mandarin. {fast}Only the named speaker's lips move. "
                 f"Location sound: {clip.ambience} No music. No subtitles, captions or on-screen text.")
    text = "\n".join(parts)
    size = words(text)
    if size > config.PROMPT_WORD_LIMIT:
        raise ValueError(f"{clip.id}: the prompt is about {size} words; the limit is {config.PROMPT_WORD_LIMIT}. Shorten look, wardrobe, blocking or action text, or split the clip.")
    return text


def words(text: str) -> int:
    """English words plus Chinese characters at two per word, the way the model's limit is described."""
    return len(re.findall(r"[A-Za-z0-9']+", text)) + len(checks.CJK.findall(text)) // 2


def voice_test(line_a: str, line_b: str) -> str:
    return ("Photoreal live action, vertical 9:16, shot on location in Hong Kong at night. Medium close-up, handheld, almost still. "
            "A man in his thirties and a woman in her fifties stand at a street-side food stall under warm tungsten light. Real skin texture, no beauty filter. "
            f"Shot 1 (0s-3s): the man speaks to her in natural colloquial Hong Kong Cantonese: {{{line_a}}} Hard cut. "
            f"Shot 2 (3s-5s): close-up of the woman answering in Hong Kong Cantonese, unimpressed: {{{line_b}}} "
            "AUDIO: speech is Hong Kong Cantonese (粵語), never Mandarin. Street ambience. No music. No subtitles or on-screen text.")
