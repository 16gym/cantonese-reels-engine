---
name: reels-gate-1-story
description: Gate 1 of a Cantonese reel - interview the user grill-style, have the Scriptwriter write the story and dialogue, get approval of the script and of the picture budget.
---

# Gate 1: story

Done when: `story.json` passes its check, the user has approved it in their own words, and the `prep` budget is approved.

Commands are `tools/reels.ps1 <command>` on Windows and `tools/reels <command>` on macOS/Linux.

## 1. Interview the user, grill-style

Interview before the Scriptwriter drafts anything. One question at a time. Each question comes with your recommended answer and the reason for it. (The user may also have the open-source "grill-me" skill installed; it works the same way.)

Ask only what the Scriptwriter cannot decide:

1. The idea, if `brief.md` does not already say it. Offer three pitches if they have none.
2. The tone: comedy, drama, or a twist.
3. The length. Recommend 30 to 45 seconds for a first full episode. Tell them what a second costs: `reels quote <episode> prep` and the draft quote show the number in the episode's unit (credits or US$).
4. Whether the episode carries a product or call to action. If they say none, it is none.
5. Whether any role uses a real person's likeness, or any place is one they can photograph.

Stop asking as soon as you have these. Write the answers into `brief.md`.

## 2. Pitch, then write

1. Brief the `scriptwriter` subagent: the episode name, `brief.md`, and "three pitches only".
2. Show the user the three loglines in chat, each with its hook. They pick or redirect.
3. Brief the `scriptwriter` again with their pick and their exact words: write `story.json`.

## 3. Check

`reels check <episode> story`

- ERROR: back to the Scriptwriter with the message. Never edit the story yourself.
- WARNING: have it fixed, or be ready to tell the user why it stays.
- Read the dialogue once yourself. If a line reads like written Chinese or like nobody would say it, send it back.

## 4. Show the user

1. `reels review <episode> story` builds `review/1-story.pdf`.
2. Tell the user: the story is ready, the full path of the PDF, and the two questions on its last page (is the story OK, and do they approve the picture budget shown).
3. Changes: back to the Scriptwriter with their words, check, rebuild the book, ask again.

## 5. Record

Only when the user has said yes to each in their own words:

```
reels approve <episode> story --text "<the user's words about the story>"
reels quote <episode> prep
reels money <episode> prep --text "<the user's words about the budget>"
```

If they approve the story but not the budget, record the story only and stop. Nothing in gate 2 can be generated without the `prep` budget.

Next: `reels-gate-2-lock`.
