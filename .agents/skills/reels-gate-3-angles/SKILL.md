---
name: reels-gate-3-angles
description: Gate 3 of a Cantonese reel - have the Director plan every shot and camera angle, generate and QA the anchor frames, and get the user's approval of the angles and of the draft budget.
---

# Gate 3: angles

Done when: `shots.json` passes its check, every camera setup has an anchor frame that passed QA, the user has approved the angles, and the `draft` budget is approved.

Commands are `tools/reels.ps1 <command>` on Windows and `tools/reels <command>` on macOS/Linux.

## 1. Shot plan

Brief the `director` subagent: read `story.json` and `bible.json` in full, write `shots.json`. Pass on anything the user has said about how they want it shot.

`reels check <episode> angles`

- At this point "No anchor frame yet" errors are expected. Every other ERROR goes back to the Director.
- Read the WARNINGS with care: they are the habits that make AI film look fake (one angle carrying the film, no close shots on the dialogue).

## 2. Anchor frames

1. `reels anchor <episode>` then `collect`. One picture per camera setup, paid from `prep`.
2. `reels qa prepare <episode> anchors`.
3. Brief the `qa` subagent: check every anchor sheet (`episodes/<episode>/anchors/*.qa.jpg`) and fill each `*.qa.json`.
4. `reels qa record <episode> anchors/<location>__<setup>.png` for each.
5. A failed anchor: `anchor <episode> --only <location>/<setup> --note "<QA's fix>"`, `collect`, `qa prepare <episode> anchors` (a redone picture loses its old verdict by itself), QA again. Twice at most; after that show the user the best one and let them decide (`qa override` with their words if they accept it).

## 3. Read the requests

`reels prompt <episode> <clip>` for every clip. It is free. Check that each clip lists the right reference pictures and that the text says what the Director meant. A wrong request found here costs nothing; found after shooting it costs a take.

## 4. Quote and show the user

1. `reels quote <episode> draft`. The cap includes 30% for retakes.
2. `reels review <episode> angles` builds `review/3-angles.pdf`: for each clip the floor map with cameras, then every shot with its anchor frame, what happens and the line.
3. Tell the user the full path and the two questions on the last page: are the angles OK, and do they approve the draft budget (give the number and its unit).
4. They want a shot changed ("s03 要近啲"): back to the Director with their words. A changed setup needs a new anchor and QA. Rebuild the book and requote, because the price follows the plan.

## 5. Record

```
reels approve <episode> angles --text "<the user's words about the angles>"
reels money <episode> draft --text "<the user's words about the budget>"
```

From here `shots.json` and the anchors are frozen.

Next: `reels-gate-4-takes`.
