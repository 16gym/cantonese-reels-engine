# Standing decisions

The engine's design decisions come first. The user's own standing decisions go in the last section.
Episode-level approvals are not kept here: they are in each episode's `state.json` and `log.md`.

## Engine design

1. **Lock first, shoot later.** Faces, clothes, places, props and voices are approved and frozen before any clip is made. A frozen file that changes reopens its gate.
2. **One video model: Seedance 2.5**, through Higgsfield. Dialogue and lip movement come from the model in the same pass. Pictures come from Higgsfield's image models.
3. **Real photos as location references.** The engine searches for real photos first and asks the user only when it comes up short. Source and licence are recorded for every photo.
4. **Three money approvals per episode**: `prep` (pictures and voice tests), `draft` (480p takes, with a retake allowance of 30% of the draft budget; when it is gone, stop and ask), `final` (the 1080p pass, only when that route is chosen). Each is approved in the user's own words.
5. **One PDF review book per gate**, in the episode's `review/` folder. The user answers by number.
6. **The agent builds nothing at runtime.** Cutting, captions, level matching and upscaling are code. Captions are burned in from the script, never generated: large Traditional Chinese, split by clause, only ？ and ！ kept.
7. **Each episode is its own cast.** New faces and places every episode. No cross-episode cast library. A role may use a real person's likeness only with their consent on file.
8. **Hooks are chosen by genre.** The first beat is 3 seconds or less.
9. **Readable writing inside the picture** (signs, receipts, phone screens) is avoided. If a story truly needs it, it is made by code or taken from a real file.
10. **No music in the engine.** A `music.*` file placed in an episode folder is mixed in quietly.
11. **The first proof is a 15-second lock test** (two people, one real place, the camera leaves and comes back) before a full episode.

## Your standing decisions

Append a dated line here when the user makes a decision that should apply to every episode. Do not rewrite old lines.
