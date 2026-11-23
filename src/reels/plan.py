"""The three plan files an episode is made of. Unknown fields are rejected so typos surface early.

story.json  - gate 1, written by the Scriptwriter
bible.json  - gate 2, written by Art: the locked look of every person, place and object
shots.json  - gate 3, written by the Director: clips (one video request each) made of shots
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from . import config
from .episode import Episode, GateError, read_json

ID = r"^[a-z][a-z0-9_]{0,23}$"
Size = Literal["ECU", "CU", "MCU", "MS", "MLS", "LS", "INSERT", "WIDE"]
CLOSE = ("ECU", "CU", "MCU")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- story.json -----------------------------------------------------------------
class Role(Strict):
    id: str = Field(pattern=ID)
    name: str
    who: str  # age, job, temperament, how they talk
    want: str  # what they want in this scene


class Place(Strict):
    id: str = Field(pattern=ID)
    name: str
    why: str = ""


class Beat(Strict):
    id: str = Field(pattern=r"^B\d{1,2}$")
    what: str  # what happens and how the balance of power shifts
    seconds: int = Field(ge=1, le=30)


class Line(Strict):
    id: str = Field(pattern=r"^L\d{2}$")
    beat: str
    speaker: str
    text: str = Field(min_length=1)  # colloquial Hong Kong Cantonese, as it will be spoken and captioned
    delivery: str = ""  # how it is said: speed, volume, the feeling underneath
    say: str = ""  # the line spelt for the voice, when the model misreads the caption spelling (SOGO came out as "SOBY")


class Story(Strict):
    title: str
    logline: str
    target_seconds: int = Field(ge=10, le=120)
    chars_per_second: float = Field(default=config.CHARS_PER_SECOND, ge=3.5, le=6.5)  # speaking pace; 6 is a fast Hong Kong argument
    hook: str  # what the viewer sees and hears in the first 2 seconds, and why they stay
    characters: list[Role] = Field(min_length=1)
    locations: list[Place] = Field(min_length=1)
    props: list[Place] = []
    beats: list[Beat] = Field(min_length=1)
    lines: list[Line] = []
    ending: str
    brand: str | None = None  # product or call to action this episode carries, if any


# ---- bible.json -----------------------------------------------------------------
class RealPerson(Strict):
    person: str  # whose likeness
    consent: str  # path to the consent note inside the episode folder


class Character(Strict):
    id: str = Field(pattern=ID)
    name: str
    look: str = Field(min_length=20)  # face, hair, build, age: English, concrete
    wardrobe: str = Field(min_length=10)  # every garment with colour, sleeve length, accessories
    voice: str = Field(min_length=10)  # age, pitch, pace, texture
    zh: str = Field(min_length=4)  # the same thing in plain Cantonese, for the user: the review books show this
    real_person: RealPerson | None = None
    refs: dict[str, str] = {}  # face, body
    # The voice reference is not listed here: it is cut from the first take the user approves and
    # lives at bible/characters/<id>/voice.wav, so adding it later does not reopen the lock gate.


class Fixture(Strict):
    name: str
    en: str = ""  # English name of a landmark the model must keep on the correct side ("steering wheel"); empty = not a landmark
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)


class FloorMap(Strict):
    """Top view. x runs left to right, y runs top to bottom, both 0 to 1."""
    aspect: float = Field(default=1.0, gt=0.2, lt=5)  # width / height of the space
    fixtures: list[Fixture] = []
    marks: dict[str, tuple[float, float]]  # named spots for people and cameras


class Location(Strict):
    id: str = Field(pattern=ID)
    name: str
    look: str = Field(min_length=20)  # materials, wear, clutter, colours: what makes it lived-in
    time: str  # e.g. "night, about 1am"
    light: str  # the actual light sources and their colour
    zh: str = Field(min_length=4)  # the same thing in plain Cantonese, for the user: the review books show this
    real_refs: list[str] = []  # real photos this place is built from
    refs: dict[str, str] = {}  # master, reverse
    map: FloorMap


class Prop(Strict):
    id: str = Field(pattern=ID)
    name: str
    look: str = Field(min_length=10)  # material, colour, size against a hand, wear
    zh: str = Field(min_length=4)  # the same thing in plain Cantonese, for the user: the review books show this
    refs: dict[str, str] = {}  # sheet


class Bible(Strict):
    style: str = Field(min_length=30)  # one paragraph: camera, lens, light and grade of the whole film
    characters: list[Character]
    locations: list[Location]
    props: list[Prop] = []

    def character(self, key):
        return next(c for c in self.characters if c.id == key)

    def location(self, key):
        return next(l for l in self.locations if l.id == key)

    def prop(self, key):
        return next(p for p in self.props if p.id == key)


class RealRef(Strict):
    file: str
    source_url: str
    author: str
    licence: str
    note: str = ""


# ---- shots.json -----------------------------------------------------------------
class Camera(Strict):
    at: str  # mark on the floor map
    look_at: str  # mark or character id
    height: Literal["low", "eye", "high", "overhead"] = "eye"
    move: str = "handheld, almost still, slight natural sway"
    plate: str = "master"  # which locked view of the location this camera stands on (a key of the location's refs)
    view: str = Field(min_length=20)  # in words: where the camera is, which way it looks, what fills the frame and its edges


class Shot(Strict):
    id: str = Field(pattern=r"^s\d{2}$")
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    setup: str = Field(pattern=r"^[a-z0-9-]{1,24}$")  # same setup = same camera = same anchor frame
    size: Size
    camera: Camera
    positions: dict[str, str] = {}  # character id -> mark, for everyone visible
    props: list[str] = []
    action: str = Field(min_length=10)  # what physically happens, start to end
    performance: str = ""  # what the face and body show
    zh: str = Field(min_length=4)  # the same thing in plain Cantonese, for the user: the review books show this
    lines: list[str] = []
    offscreen: list[str] = []  # line ids heard while the speaker is out of frame
    cross_axis_ok: str | None = None  # reason, when this shot deliberately crosses the line


class Clip(Strict):
    id: str = Field(pattern=r"^c\d{2}$")
    location: str
    duration: int = Field(ge=4, le=30)
    new_view_ok: str | None = None  # reason, when this clip comes back to a place on a camera not seen there before
    axis: tuple[str, str] | None = None  # the two characters whose eyeline all cameras stay on one side of
    blocking: str = Field(min_length=20)  # where everyone is and how they move through the space
    ambience: str  # the sound of the place
    zh: str = Field(min_length=4)  # the same thing in plain Cantonese, for the user: the review books show this
    shots: list[Shot] = Field(min_length=1)


class ShotPlan(Strict):
    clips: list[Clip] = Field(min_length=1)

    def clip(self, key):
        return next(c for c in self.clips if c.id == key)


# ---- loading ----------------------------------------------------------------------
def _load(ep: Episode, name: str, model):
    path = ep.path(name)
    if not path.exists():
        raise GateError(f"{name} is missing in episodes/{ep.name}/")
    try:
        return model.model_validate(read_json(path))
    except Exception as exc:  # pydantic's message already names the field
        raise GateError(f"{name} is not valid:\n{exc}") from None


def story(ep: Episode) -> Story:
    return _load(ep, "story.json", Story)


def bible(ep: Episode) -> Bible:
    return _load(ep, "bible.json", Bible)


def shots(ep: Episode) -> ShotPlan:
    return _load(ep, "shots.json", ShotPlan)


def real_refs(ep: Episode) -> list[RealRef]:
    path = ep.path("refs", "refs.json")
    return [RealRef.model_validate(r) for r in read_json(path)] if path.exists() else []


def candidates(ep: Episode, character: str) -> list:
    """Casting pictures for a role in the order they were made: the first is A, the second B."""
    import re
    found = [(int(m.group(1)), p) for p in ep.path("bible", "characters", character).glob("cast-*.png") if (m := re.fullmatch(r"cast-(\d+)\.png", p.name))]
    return [p for _, p in sorted(found)]


def anchor_path(location: str, setup: str) -> str:
    return f"anchors/{location}__{setup}.png"
