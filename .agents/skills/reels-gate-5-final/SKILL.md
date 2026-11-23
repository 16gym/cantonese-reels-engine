---
name: reels-gate-5-final
description: Gate 5 of a Cantonese reel - make the finished clips by the route the user chose (Higgsfield 1080p or Kie 4K upscale), QA them, cut the film with captions, optional finishing, and get the user's approval.
---

# Gate 5: final

Done when: every clip has a finished version, the film is cut with captions (`out/final.mp4`, or `out/final-4k.mp4` on route B), and the user has approved the film.

Commands are `tools/reels.ps1 <command>` on Windows and `tools/reels <command>` on macOS/Linux.

The user chose a route at the end of gate 4. Follow that one.

## Route A: Higgsfield 1080p

1. `reels finalize <episode>` then `reels collect <episode>`. The 1080p version is made from the picked draft, but small details can still shift, so it is checked again.
2. QA again:
   - `reels qa prepare <episode> finals`
   - Brief the `qa` subagent: check every final against the locked pictures, and against the draft the user picked (`takes/<clip>/t<N>.qa/`). Read that take's `t<N>.request.json` for what was planned.
   - `reels qa record <episode> finals/<clip>.mp4` for each.
   - A failed final: stop. The `final` budget has no retake allowance. Show the user the frames and what changed from the draft they picked, and ask. They can accept it (`qa override` with their words) or approve money for another attempt.
3. `reels cut <episode>` joins the clips in order, levels the sound and burns the captions (1080p). It writes `out/final.mp4`, `out/final.ass` and `out/final.srt`.

## Route B: Kie 4K upscale from the picked drafts

1. `reels upscale <episode>` prints a quote (about US$0.03 a second) and spends nothing. It needs `KIE_API_KEY` in `.env`.
2. Show the user the number. When they approve in their own words: `reels upscale <episode> --text "<the user's words>"`, then rerun it until every clip is done. Kie sometimes answers "service is busy"; rerunning resubmits only the clips that failed.
3. `reels cut <episode> --upscaled` writes the 4K film with captions burned in.

## Optional 4K on top of route A

The same two upscale steps, then `reels cut <episode> --upscaled`.

## Cut notes

- Captions come from `story.json`, so every character is right. Timing comes from the actual speech when the Cantonese listener is installed, otherwise from the shot plan. The command says which.
- A file named `music.mp3` (or `.wav`, `.m4a`) placed in the episode folder is mixed in quietly under the whole film. There is no music otherwise; the engine does not generate any.
- To preview before spending on finals: `cut <episode> --draft` cuts the picked 480p takes into `out/draft.mp4`.
- Watch for: a caption that appears before or after its line, a cut that lands mid-word, a clip that is much louder than its neighbours.

## Optional finishing: end card and sound effects

Make them with HyperFrames (`npx hyperframes`; use the agent's HyperFrames skill if it has one). Always work on a COPY of the cut and keep the un-finished cut file as it is.

## Show the user

1. `reels review <episode> final` builds `review/5-final.pdf`.
2. Tell the user the full path of the film (`out/final.mp4` or `out/final-4k.mp4`; send the file if they are remote) and ask the one question: is the film OK. They answer with a time and a problem ("0:12 字幕早咗").
3. What a fix costs, so you can tell them before doing it:
   - Caption timing or cut points: free, recut.
   - A clip that looks wrong: a new take and a new finished version, with new money approvals.
   - A line or an angle: back to gate 1 or gate 3.

## Record

```
reels approve <episode> final --text "<the user's words>"
```

Then tell them where the film and the `.srt` are (full paths) and what the episode cost in total (`reels status <episode>`).

Publishing is the user's. Do not post, upload or schedule anything.
