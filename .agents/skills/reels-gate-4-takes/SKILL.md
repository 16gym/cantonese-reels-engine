---
name: reels-gate-4-takes
description: Gate 4 of a Cantonese reel - shoot the 480p draft takes, have QA reject the broken ones, retake inside the allowance, let the user pick a take per clip, then choose the route to the finished film.
---

# Gate 4: takes

Done when: every clip has a take that passed QA and that the user picked, the takes gate is approved, and the user has chosen route A or B for the finished film (route A also needs the `final` budget approved).

Commands are `tools/reels.ps1 <command>` on Windows and `tools/reels <command>` on macOS/Linux.

## 1. Shoot

```
reels shoot <episode>
reels collect <episode>
```

Two takes per clip by default. Clips take minutes to render: run `collect` again until `still_running` is empty. Never run `shoot` a second time because something is slow.

`collect` reports `failed` (the provider made nothing and charged nothing) and `unknown` (it may have been charged: do not resubmit, tell the user).

## 2. QA

1. `reels qa prepare <episode> takes`. When the Cantonese listener is installed this also checks each scripted line was spoken.
2. Brief the `qa` subagent: check every take's sheets and fill each verdict.
3. `reels qa record <episode> takes/<clip>/t<N>.mp4` for each take.

## 3. Retakes

For a clip with no passing take:

1. Brief the `director`: turn QA's `fix` list for that clip into `retakes.json` corrections.
2. `reels shoot <episode> --clip <clip> --takes 1`, `collect`, QA the new take.
3. Two retake rounds at most per clip. Still nothing passing: show the user what exists and say what keeps failing. They can accept a take (`qa override ... --text "<their words>"`), change the plan, or stop.

Retakes spend the allowance inside the draft cap. A `STOP` about the budget means the allowance is gone: tell the user how much was used and what is still failing.

## 4. Show the user

1. `reels review <episode> takes` builds `review/4-takes.pdf` and `review/4-takes.mp4`, one video with every passing take back to back, named in the corner.
2. Tell the user: the full path of the video to watch first, then the PDF (send the files if they are remote). Ask the two questions on its last page: which take for each clip, and whether the voice or the Cantonese sounds wrong anywhere.
3. QA cannot hear. If the user says a line sounds wrong: have the Director add a correction about the delivery and retake that clip. If the wording itself is the problem, the line changes in `story.json`, which reopens gate 1: tell them that before doing it.

## 5. Record the picks

```
reels select <episode> c01=2 c02=1 c03=2
reels approve <episode> takes --text "<the user's words>"
```

## 6. Choose the route to the finished film

Present both routes with your recommendation. The user decides.

**Route A: Higgsfield 1080p.** `reels quote <episode> final` gives the price for the picked takes (about 16 credits per second on the CLI; a 60-second film is about 1,000 credits, most of a Plus month). Then `reels money <episode> final --text "<the user's words>"`. Optional 4K on top, in gate 5.

**Route B: upscale the picked 480p takes to 4K on Kie AI (cheapest).** Skip the `final` budget and `finalize`. `reels upscale <episode>` works straight from the picked takes (about US$0.03 a second) and needs `KIE_API_KEY` in `.env`. Gate 5 has the steps.

Recommend route B unless the user wants Higgsfield's own 1080p. Tell the user the number for the route they pick in one line, then ask.

A picked draft can be turned into its 1080p version by Higgsfield for about 6 days. If the user will not decide soon and might want route A, tell them that date.

Next: `reels-gate-5-final`.
