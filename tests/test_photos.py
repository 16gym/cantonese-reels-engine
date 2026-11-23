"""Real-photo sourcing: every reference is filed with where it came from."""
import io

import httpx
import pytest
from PIL import Image

from reels import checks, photos
from reels.episode import GateError, read_json


def fake_commons(request):
    if request.url.host == "commons.wikimedia.org":
        return httpx.Response(200, json={"query": {"pages": {
            "1": {"index": 1, "title": "File:Cha Chaan Teng 1.jpg", "imageinfo": [{"thumburl": "https://upload.wikimedia.org/a.jpg", "descriptionurl": "https://commons.wikimedia.org/wiki/File:A",
                  "extmetadata": {"Artist": {"value": "<a href='x'>Wing</a>"}, "LicenseShortName": {"value": "CC BY-SA 4.0"}}}]},
            "2": {"index": 2, "title": "File:No thumb.jpg", "imageinfo": [{}]}}}})
    buffer = io.BytesIO()
    Image.new("RGB", (800, 600), (120, 130, 110)).save(buffer, "JPEG")
    return httpx.Response(200, content=buffer.getvalue())


def test_search_result_becomes_a_filed_reference(ep):
    client = httpx.Client(transport=httpx.MockTransport(fake_commons))
    sheet = photos.find(ep, "Hong Kong cha chaan teng booth", 6, client)
    assert sheet.exists()
    found = read_json(sheet.parent / "found.json")
    assert [(f["author"], f["licence"]) for f in found] == [("Wing", "CC BY-SA 4.0")]
    filed = photos.use(ep, "booth", found[0]["file"])
    assert filed == "refs/booth/01.jpg" and ep.exists(filed)
    record = read_json(ep.path("refs", "refs.json"))[0]
    assert record["source_url"] == "https://commons.wikimedia.org/wiki/File:A" and record["licence"] == "CC BY-SA 4.0"
    assert filed in read_json(ep.path("bible.json"))["locations"][0]["real_refs"]


def test_a_photo_without_a_source_is_refused(ep, tmp_path):
    picture = tmp_path / "phone.jpg"
    Image.new("RGB", (400, 300)).save(picture)
    with pytest.raises(GateError, match="source"):
        photos.add(ep, "bar", picture, "", "Ada", "own photo")
    assert any("Location 'bar' has no real photo" in e for e in checks.check_bible(ep).errors)
    assert photos.add(ep, "bar", picture, "own phone", "Ada", "own photo") == "refs/bar/01.jpg"
    assert not any("'bar'" in e and "photo" in e for e in checks.check_bible(ep).errors)


def test_search_asks_for_a_contact_instead_of_inventing_one(ep, monkeypatch):
    monkeypatch.delenv("REELS_CONTACT", raising=False)
    with pytest.raises(GateError, match="REELS_CONTACT"):
        photos.agent()
    monkeypatch.setenv("REELS_CONTACT", "https://example.org")
    assert "(https://example.org)" in photos.agent()
