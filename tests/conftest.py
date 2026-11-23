import shutil
from pathlib import Path

import pytest
from PIL import Image

from reels import speech
from reels.episode import Episode, read_json, write_json

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "lock-test"


@pytest.fixture
def ep(tmp_path, monkeypatch):
    """A mock episode loaded with the shipped example plan. No network, no spend."""
    monkeypatch.setenv("REELS_ROOT", str(tmp_path))
    monkeypatch.setattr(speech, "available", lambda: False)  # the mock clips contain a tone, not speech
    episode = Episode("demo", tmp_path)
    episode.create("rehearsal", mock=True)
    for name in ("story.json", "bible.json", "shots.json"):
        shutil.copyfile(EXAMPLE / name, episode.path(name))
    return episode


def add_real_refs(episode: Episode) -> None:
    from reels import photos
    source = episode.path("source.jpg")
    Image.new("RGB", (640, 480), (90, 110, 100)).save(source)
    for location in read_json(episode.path("bible.json"))["locations"]:
        photos.add(episode, location["id"], source, "https://commons.wikimedia.org/wiki/Example", "Example", "CC BY-SA 4.0")


def edit_json(path, change) -> None:
    data = read_json(path)
    change(data)
    write_json(path, data)
