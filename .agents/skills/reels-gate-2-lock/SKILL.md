---
name: reels-gate-2-lock
description: Gate 2 of a Cantonese reel - find real reference photos, cast the faces, lock every costume, place, prop and voice, and get the user's approval of each.
---

# Gate 2: lock

Done when: every character has a locked face and body picture, every location has real photos and a master, every prop has a picture, `check lock` passes, and the user has said the lock is OK.

This gate takes two or three rounds with the user. That is expected: what they approve here is what every later frame is held to.

Commands are `tools/reels.ps1 <command>` on Windows and `tools/reels <command>` on macOS/Linux.

## 0. First run of the engine only: the voice test

If `docs/DECISIONS.md` has no verdict yet on Cantonese speech:

1. `reels voice-test <episode>` then `collect`. It is paid from the `prep` budget.
2. Give the user the full path of `episodes/<episode>/voice-test/voice-test.mp4` and ask one question: is this natural Hong Kong Cantonese?
3. Write their verdict, dated, into `docs/DECISIONS.md` under "Your standing decisions".
4. If they say no: stop this gate. Tell them the fallback (silent video plus a separate voice track) is not built, and ask how they want to go on.

## 1. Bible and real photos

Brief the `art` subagent: write `bible.json` from the approved `story.json`, then find and file real photos for each location (`find-photos`, `use-photo`). Clear it to run those photo commands only.

When Art reports a place it could not find: ask the user for a photo, saying exactly what is needed in their terms. File what they send with `add-photo` (source "user's phone", author their name, licence "own photo"). Leave the author as "user" if they prefer not to give a name.

## 2. Casting round

1. Have Art run `cast <episode> <character> --n 4` for each fictional role, then `reels collect <episode>`.
2. `reels review <episode> lock` and show the user the PDF. The last page asks which face for each role (they answer like "1B, 2D") and whether each place matches its real photos.
3. They want other faces: `cast` again with a `--note` in their words. The new candidates get the next letters.

Roles using a real person: do not cast. Follow "Real person" in `docs/craft/art.md`. No consent note, no upload.

## 3. Lock round

For each role, with the user's choice: `pick <episode> <character> <letter>`, then `body <episode> <character>`, then `turn <episode> <character>` for the five face angles (front, left 45, left 90, right 45, right 90). `turn` runs in two steps: collect the side views, then run it again to build the sheet.
For each location: `place <episode> <location> --view "..."` (add `--reverse-view "..."` when two people face each other there), or `adopt` a real photo as the master. Lock one view for every direction the cameras will look (see "Lock a place from every side the film looks" in `docs/craft/art.md`).
For each prop: `prop <episode> <prop>` (with `--photo` when a real photo exists).
For each speaking role: `voice <episode> <character> --line "<a line in their manner>"`. Only for characters who speak in the film.

Then `collect`, and have Art look at every result and redo what is plainly wrong (twice at most per picture).

## 4. Check and show the user

1. `reels check <episode> lock`. Fix every ERROR through Art.
2. `reels review <episode> lock`. Show the user the PDF and give them the full paths of the voice clips to listen to (send the files if they are remote).
3. For each voice they approve: `voice-lock <episode> <character> <number>`. A voice they reject: `voice` again with a different line or a changed `voice` description in `bible.json`.
4. Anything they want changed: back to Art with their words, redo, rebuild the book.

## 5. Record

When the user says the lock is OK (the book asks them to say 「鎖定」 or "lock"):

```
reels approve <episode> lock --text "<the user's words>"
```

From here `bible.json` and its pictures are frozen. Changing any of them reopens this gate.

Next: `reels-gate-3-angles`.
