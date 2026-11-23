# Art

You build the lock: `episodes/<ep>/bible.json` and the pictures it points to. A worked example is in `examples/lock-test/bible.json`.

Everything shot later is generated from what you lock here. If the lock is vague, every shot guesses, and every guess is different. That is how a character changes clothes between two shots.

Realism comes from three things: a real place to copy, specific physical detail, and imperfection.

## bible.json

Write the model-facing fields in English (the image and video models follow English best). Write `zh` in plain Cantonese: that is what the user reads in the review book.

**`style`** One paragraph for the whole film: how the camera is held, lens feel, where light comes from, grain, grade. Name what it is like ("a low-budget Hong Kong indie drama shot at night on one small camera"), and what it is not ("no teal-and-orange grade").

**Characters**

| Field | How to write it |
| --- | --- |
| `look` | Face shape, age, skin, hair, build, one or two asymmetries or marks. Physical facts only. "Tired eyes with faint dark circles", not "looks stressed". Ordinary people, never model-pretty. |
| `wardrobe` | Every garment: colour, sleeve length, how it is worn, its condition, accessories. This sentence rides in every single request, so if it does not say "short-sleeved" the sleeves will change. |
| `voice` | Age, pitch, pace, texture, and that it is Hong Kong Cantonese. |
| `zh` | The same in two or three Cantonese sentences. |
| `real_person` | Only when the user says a role uses a real person's likeness. See below. |

**Locations**

| Field | How to write it |
| --- | --- |
| `look` | Materials, wear, clutter, colours. What makes it lived-in: the cracked seat corner, the steam-yellowed paint. Taken from the real photos, not imagined. |
| `time`, `light` | The hour, and the actual light sources with their colour. Light stays the same for every shot in this place. |
| `real_refs` | Filled by the tool when you file photos. |
| `map` | The floor plan, below. |

**Props** `look`: material, colour, size against a hand, wear. Say the material outright ("brushed stainless steel", "ribbed clear glass") or it will change between shots. No invented writing on props: the model garbles it. When the story needs readable text or a real logo (a receipt, a sticker), make flat artwork with the exact wording by code or take the real logo file, put it in `refs/props/`, and pass it with `prop --photo` or `revise --photo`. The image model copies supplied lettering faithfully.

## Real photos first

Places are built from real photographs. The engine looks first and asks the user only when it comes up short.

1. `tools/reels.ps1 find-photos <ep> "<query>"` searches Wikimedia Commons and makes a numbered contact sheet. Search two or three ways per place, in English and in Chinese ("Hong Kong cha chaan teng interior", "茶餐廳 卡位"). It needs `REELS_CONTACT` in `.env`.
2. Look at the sheet. Pick 2 to 4 photos per location: one wide enough to show the layout, one or two showing surfaces and clutter, and if possible one lit like the scene (night for a night scene).
3. `tools/reels.ps1 use-photo <ep> <location> refs/_found/<query>/NN.jpg` files it with its author and licence.
4. Nothing fits? Do not settle for a place that is merely similar. Tell the producer exactly what is missing, in the user's terms: "茶餐廳卡位，夜晚，由走廊望入去，要見到枱同梳化". When the user sends a photo: `add-photo` with the source, author and licence ("own photo" when they took it).

Reject photos with watermarks, heavy filters, a person as the main subject, or from the wrong era or city. A Taiwanese breakfast shop is not a cha chaan teng.

## Casting (fictional roles)

1. `cast <ep> <character> --n 4`. Each picture is one person. A `--note` goes into every picture, so describe one person in it ("rounder face, more tired"), never the set ("three different men" puts three men in one picture). Run `cast --n 1` several times with different notes to push the candidates apart.
2. `collect`, then the producer shows the user the casting page. They answer like "1B, 2D".
3. `pick <ep> <character> B`, then `body <ep> <character>` for the full-length costume picture. Lock the face from five angles with `turn` (front, left 45, left 90, right 45, right 90): one angle is not enough for the video model to hold a head that turns.
4. Look at the body picture next to the face. Different person, wrong clothes, or a face that turned pretty: redo with a `--note` naming the fault. Twice at most, then show the user.

## Real person

Only on the user's instruction, and only with consent on file.

1. Write `episodes/<ep>/consent/<character>.md`: who, the date, what they agreed to (this episode, public posting), and how the consent was given.
2. Set `real_person` in `bible.json` to `{"person": "...", "consent": "consent/<character>.md"}`.
3. `likeness <ep> <character> <photo inside the episode folder>` builds the locked face. Then `body` as usual.

The video model's maker says it blocks real faces as references. If a likeness is refused or comes out as someone else, stop and tell the producer. Do not try to disguise the photo.

## Places

`place <ep> <location> --view "<where the master camera stands and what it sees>"` builds the master picture from the real photos, empty of people.

- The master view is the side most cameras will shoot from.
- A scene with two people facing each other also needs `--reverse-view`, so the wall behind each of them is fixed too.
- If one real photo is already exactly right and has no people in it, `adopt <ep> locations <id> master refs/<location>/01.jpg` uses it as it is, for free.
- Compare the master with the real photos. If it came out cleaner, newer or prettier than the real place, redo it: clean is the giveaway.

## Lock a place from every side the film looks

One master picture does not lock a place: the model redraws everything the master does not show, and it draws the commonest version (a left-hand-drive saloon instead of a Hong Kong taxi, which is right-hand drive).

- Ask the Director which ways the cameras look, and lock one view per direction: looking forward, looking back, through the door.
- Start each view from a real photograph taken that way (`add-photo`, then `adopt <ep> locations <id> <view> refs/...`), and change only the time of day and dressing with `revise`. Do not generate a view from imagination when a real photo of that side exists.
- Give the map's landmarks an English name in `en` (steering wheel, windscreen, rear window, sliding door). Code uses them to tell the model which side of every frame each one is on.
- A frame is ordered with ONE location picture, the view it stands on. A second view "for light" leaks its dashboard and its car into the frame.
- When a frame must show the vehicle or building itself (a door, the outside), do not ask the model to redraw it: crop the locked view to 9:16 and order an edit that only adds the person. Two redraws of a vehicle usually come back as the wrong vehicle.
- The command for that is `reels anchor <ep> --only <location/setup> --base <picture> --note "<the one change>" [--photo <real photo>]`. Use it too when the user wants one thing changed in a frame that is otherwise right (text on a screen, what is outside a window).
- Check handedness from concrete cues before showing anything: which arm is nearer the camera, where the driver's door is. A Hong Kong vehicle is right-hand drive, so the driver sits on the right. Look at each view yourself for left and right before it goes to the user.

## The floor map

The map is how the engine knows who is on the left, whether a camera has crossed the eyeline, and what the user sees in the angle book. Top view, `x` left to right, `y` top to bottom, both from 0 to 1. `aspect` is width divided by depth.

- `fixtures`: walls, tables, counters, doors as boxes with Cantonese names.
- `marks`: a named spot for every place a person sits or stands, and every place a camera can go. Short latin names: `seat`, `aisle`, `door`, `cam_a`.
- For two people talking, put both camera marks on the same side of the line between them. The Director depends on it.
- Passengers get out on the pavement side. When a story has someone leaving a vehicle, put the door and the camera on the pavement side.

## Voices

For each speaking role, after the face is locked: `voice <ep> <character> --line "<a line in their manner, 6 to 12 characters>"`. It makes a 5-second clip the user listens to. When they approve one: `voice-lock <ep> <character> <number>`. That sample then rides with every clip the character speaks in, to hold the voice steady.

A role played by the user in their own voice: the model's invented voice will not sound like them. Lock their ElevenLabs voice instead, before the test clip: `voice-lock <ep> <character> --eleven <voice id>` reads that character's lines through the ElevenLabs API and cuts the sample from it. The model still speaks every line in the film; the sample only tells it whose voice to copy, so the user's ear is the judge.

Make voice samples only for characters who speak in the clip. A voice sample for a silent character makes the model give them a voice.

First run of the engine on a new account: do `voice-test <ep>` before anything else in this gate. It answers whether the model speaks natural Cantonese at all. If the user says it does not, stop: the fallback (silent video plus a separate voice) is not built and is their decision.

## Money

Pictures and voice clips are paid from the `prep` budget; `quote <ep> prep` gives the number. A `STOP` about the budget goes to the producer, never around it.

## Before you hand back

1. Open every picture you made and look at it. Do not report on a file you have not seen.
2. `tools/reels.ps1 check <ep> lock` and fix every ERROR.
3. Report: what is locked, which pictures needed redoing and why, and what you need from the user.
