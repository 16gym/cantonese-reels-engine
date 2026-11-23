"""Real photographs for locations. The engine looks first; the user is asked only when it comes up short.

Search runs on Wikimedia Commons: free to query, no key, and every file carries its
author and licence, which are recorded so a reference can always be traced.
Photos from anywhere else (the user's phone, a client's shop) are added with `add`.
"""
import os
import re
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

from . import review
from .episode import Episode, GateError, read_json, repo_root, write_json

COMMONS = "https://commons.wikimedia.org/w/api.php"


def agent() -> str:
    """Wikimedia refuses automated clients that give no contact. The contact is the user's to choose, so it lives in .env."""
    contact = os.environ.get("REELS_CONTACT", "")
    env = repo_root() / ".env"
    if not contact and env.exists():
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            if line.strip().startswith("REELS_CONTACT="):
                contact = line.split("=", 1)[1].strip().strip("\"'")
    if not contact:
        raise GateError("Photo search needs a contact for Wikimedia's robot policy. Ask the user to add one line to .env: REELS_CONTACT=<a website or email they are happy to show Wikimedia>. Until then, ask the user for photos and file them with add-photo.")
    return f"cantonese-reels-engine/0.1 ({contact}) python-httpx"


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html or "")).strip()


def search(query: str, count: int = 12, client: httpx.Client | None = None) -> list[dict]:
    client = client or httpx.Client(timeout=40, headers={"User-Agent": agent()})
    response = client.get(COMMONS, params={"action": "query", "format": "json", "generator": "search", "gsrsearch": f"{query} filetype:bitmap",
                                           "gsrnamespace": 6, "gsrlimit": count, "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": 1600})
    response.raise_for_status()
    found = []
    for page in sorted(response.json().get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0)):
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        if info.get("thumburl"):
            found.append({"title": page["title"], "download": info["thumburl"], "source_url": info.get("descriptionurl", ""),
                          "author": _text(meta.get("Artist", {}).get("value", "")) or "unknown", "licence": _text(meta.get("LicenseShortName", {}).get("value", "")) or "unknown"})
    return found


def find(ep: Episode, query: str, count: int = 12, client: httpx.Client | None = None) -> Path:
    """Downloads candidates into refs/_found/<query>/ and returns a numbered contact sheet to look at."""
    folder = ep.path("refs", "_found", re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-") or "query")
    folder.mkdir(parents=True, exist_ok=True)
    fetch = client or httpx.Client(timeout=60, headers={"User-Agent": agent()}, follow_redirects=True)
    kept = []
    for item in search(query, count, client):
        target = folder / f"{len(kept) + 1:02d}.jpg"
        try:
            reply = fetch.get(item["download"])
            reply.raise_for_status()
            target.write_bytes(reply.content)
            Image.open(target).convert("RGB").save(target, quality=90)
        except Exception:  # one unreadable file must not lose the rest
            target.unlink(missing_ok=True)
            continue
        kept.append({**item, "file": target.relative_to(ep.dir).as_posix()})
    if not kept:
        raise GateError(f"No usable photos for '{query}'. Try other words (English and Chinese both work), or ask the user for a photo.")
    write_json(folder / "found.json", kept)
    cell, columns = 400, 4
    rows = (len(kept) + columns - 1) // columns
    sheet = Image.new("RGB", (cell * columns, (cell + 40) * rows), "white")
    draw = ImageDraw.Draw(sheet)
    for index, item in enumerate(kept):
        picture = Image.open(ep.path(item["file"]))
        picture.thumbnail((cell - 8, cell - 8))
        x, y = (index % columns) * cell, (index // columns) * (cell + 40)
        sheet.paste(picture, (x + 4, y + 40))
        draw.text((x + 8, y + 4), f"{index + 1:02d}  {item['licence'][:22]}", fill=(0, 0, 0), font=review.typeface(24, True))
    sheet.save(folder / "sheet.jpg", quality=85)
    return folder / "sheet.jpg"


def add(ep: Episode, location: str, file: Path, source_url: str, author: str, licence: str, note: str = "") -> str:
    """Files a photo as a real reference for a location and records where it came from."""
    if not Path(file).is_file():
        raise GateError(f"{file} does not exist")
    if not (source_url.strip() and author.strip() and licence.strip()):
        raise GateError("Every real photo needs a source, an author and a licence. For your own photo: source 'own phone', author '<your name>', licence 'own photo'.")
    bible = read_json(ep.path("bible.json"))
    entry = next((l for l in bible["locations"] if l["id"] == location), None)
    if entry is None:
        raise GateError(f"Location '{location}' is not in bible.json")
    folder = ep.path("refs", location)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{len(list(folder.glob('*.jpg'))) + 1:02d}.jpg"
    Image.open(file).convert("RGB").save(target, quality=92)
    relative = target.relative_to(ep.dir).as_posix()
    listing = ep.path("refs", "refs.json")
    records = read_json(listing) if listing.exists() else []
    write_json(listing, [*records, {"file": relative, "source_url": source_url, "author": author, "licence": licence, "note": note}])
    if relative not in entry.setdefault("real_refs", []):
        entry["real_refs"].append(relative)
    write_json(ep.path("bible.json"), bible)
    return relative


def use(ep: Episode, location: str, found_file: str) -> str:
    """Adopts one search result as a real reference, carrying its recorded source and licence."""
    path = ep.path(found_file)
    listing = path.parent / "found.json"
    record = next((r for r in read_json(listing) if r["file"] == found_file), None) if listing.exists() else None
    if record is None:
        raise GateError(f"{found_file} is not a search result. Use add-photo and state its source.")
    return add(ep, location, path, record["source_url"], record["author"], record["licence"], record["title"])
