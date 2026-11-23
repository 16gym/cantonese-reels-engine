---
name: reels-start
description: Start or resume a Cantonese reel episode - set up a new machine, log in to Higgsfield, run the free checks and rehearsal, open a new episode or find which gate an existing one is in.
---

# Start or resume

Commands below are `tools/reels.ps1 <command>` on Windows and `tools/reels <command>` on macOS/Linux.

## New machine, or the tool is not installed

1. Run `tools/setup.ps1` (Windows) or `tools/setup.sh` (macOS/Linux). It creates `.venv`, installs the package and runs the tests. It calls no paid service.
2. `reels demo`. A free rehearsal of all five gates with placeholder pictures and clips. It proves the install works and leaves a set of review books in `episodes/demo-.../review/` so the user can see what each gate will look like.
3. `reels preflight`. Free: it checks the Higgsfield CLI is installed, you are logged in, the plan is Plus or above (Free cannot use the CLI, Starter has no Seedance 2.5), how many credits are left, and that Higgsfield accepts every request shape the engine sends. Run it again before any paid work in a new session.
4. "Not logged in": run `higgsfield auth login`.
   - The user is at the machine: a browser opens and they click approve.
   - The user is remote: the command prints the path of a local `sign-in.html`. Read it and give the user the `https://clerk.higgsfield.ai/oauth/authorize?...` link inside. They log in on their phone and land on a page that fails to load at `http://localhost:8765/callback?code=...`. They paste that whole URL back. Request it on the machine (`curl` or `Invoke-WebRequest`) to finish the login. The code is single-use and useless without the verifier on the machine.
   - Never ask for passwords or keys in chat.
5. No Higgsfield plan, or the user prefers pay-as-you-go: set `REELS_PROVIDER=rest` in `.env` and ask the user to fill in `HF_API_KEY_ID` and `HF_API_KEY_SECRET` themselves. Never ask for a key in chat and never display the file. Then run `reels preflight` again.
6. If `REELS_CONTACT` is empty in `.env`, tell the user once: photo search on Wikimedia needs a website or email of their choice on that line. Without it, places are built only from photos they supply.
7. `KIE_API_KEY` in `.env` is needed only for the optional 4K upscale at the end. Mention it once, when the user first asks about 4K.

An episode keeps the provider it was created with. Budgets are in credits (CLI) or US$ (REST).

## Resume an episode

`reels status <episode>` shows each gate (open, approved or stale), the money approved and used, and jobs still rendering.

- Jobs in flight: run `reels collect <episode>` first.
- A gate is `stale`: a file changed after the user approved it. Show them what changed and re-approve that gate before anything else.
- Otherwise open the skill for the first gate that is `open`: `reels-gate-1-story` to `reels-gate-5-final`.

Read `episodes/<episode>/log.md` for what has happened so far. Do not rely on memory of an earlier session.

## New episode

1. Ask the user for the idea in one line, or offer to have three pitched. One question, with your recommendation.
2. Pick a short name: lowercase letters, digits and hyphens (`late-night-tea`).
3. `reels new <episode> --brief "<the user's words>"`. Add `--provider rest` for pay-as-you-go. Add `--quality 720p` for a test film that shoots takes at 720p and uses the picked take as the final.
4. Go to `reels-gate-1-story`.

## The very first real episode: the lock test

The first thing a new setup shoots is a 15-second lock test, before any full episode: two people, one real place, the camera leaves and comes back.

- Name it `lock-test`. `examples/lock-test/` holds a proposed story, bible and shot plan for it. Offer that story to the user as the starting point; they may change it.
- It must answer four questions. Write the user's verdict on each into `docs/DECISIONS.md` under "Your standing decisions" when it is done:
  1. Does the model speak natural Hong Kong Cantonese?
  2. Does a character keep the same voice across separate clips?
  3. Are faces, clothes and the prop the same in every clip?
  4. Is the place the same when the camera comes back?
- Quote before every spend as usual.
- If the answer to 1 or 2 is no, stop after the drafts. The fallback (silent video plus a separate voice) is not built and is the user's decision.
- Only after the user calls the lock test a pass does a full episode start.
