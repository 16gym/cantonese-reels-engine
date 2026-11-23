"""Each craft rule fails on the mistake it was written to catch."""
import pytest

from conftest import add_real_refs, edit_json
from reels import captions, checks, plan, prompts, review, speech
from reels.episode import write_json


def errors(ep) -> str:
    return "\n".join(checks.check_shots(ep, anchors=False).errors)


def lock(ep):
    """Fills in reference paths so prompt building has something to point at."""
    add_real_refs(ep)
    def refs(data):
        for person in data["characters"]:
            person["refs"] = {"face": f"bible/characters/{person['id']}/face.png", "turn": f"bible/characters/{person['id']}/turn.png", "body": f"bible/characters/{person['id']}/body.png"}
        for spot in data["locations"]:
            spot["refs"] = {"master": f"bible/locations/{spot['id']}/master.png"}
        for thing in data["props"]:
            thing["refs"] = {"sheet": f"bible/props/{thing['id']}/sheet.png"}
    edit_json(ep.path("bible.json"), refs)


def test_shipped_example_is_clean(ep):
    assert checks.check_story(ep).errors == []
    assert checks.check_story(ep).warnings == []
    lock(ep)
    report = checks.check_shots(ep, anchors=False)
    assert report.errors == [] and report.info["seconds"] == 15


def test_story_rules(ep):
    edit_json(ep.path("story.json"), lambda d: d["lines"][1].update(text="這個是少甜的了，平時我們都是落四羹糖的，你知道嗎。"))
    report = checks.check_story(ep)
    assert any("Beat B2" in e for e in report.errors)  # too long to say in 4 seconds
    assert any("written Chinese" in w and "的→嘅" in w for w in report.warnings)
    assert checks.written_words("搭的士去銅鑼灣，不過好塞車") == []  # real Cantonese words are not flagged


def test_jump_cut_and_one_angle_carrying_the_film(ep):
    lock(ep)
    def same_angle(data):
        for clip in data["clips"]:
            if clip["location"] == "booth":
                for shot in clip["shots"]:
                    shot.update(setup="yan-mcu", size="MCU", camera={"at": "cam_yan", "look_at": "yan", "view": "The camera stands in the aisle and looks at YAN on the bench."}, positions={"yan": "seat", "keung": "aisle"})
    edit_json(ep.path("shots.json"), same_angle)
    text = errors(ep)
    assert "jump cut" in text and "carries" in text


def test_crossing_the_eyeline(ep):
    lock(ep)
    edit_json(ep.path("bible.json"), lambda d: d["locations"][0]["map"]["marks"].update(cam_keung=[0.24, 0.2]))
    assert "both sides" in errors(ep)


def test_return_to_a_location_must_reuse_a_known_angle(ep):
    lock(ep)
    def new_angle(data):
        shot = data["clips"][2]["shots"][0]
        shot.update(setup="yan-wide", size="MS")
    edit_json(ep.path("shots.json"), new_angle)
    assert "returns to 'booth' with a new camera setup" in errors(ep)


def test_lines_must_fit_and_be_spoken_once_in_order(ep):
    lock(ep)
    edit_json(ep.path("shots.json"), lambda d: d["clips"][2]["shots"][1].update(lines=[]))
    assert "missing L05" in errors(ep)
    edit_json(ep.path("shots.json"), lambda d: d["clips"][2]["shots"][0].update(lines=["L04", "L05"]))
    assert "but is not in frame" in errors(ep)  # keung speaks L05 in a shot that only shows yan
    def both_in_the_short_shot(data):
        data["clips"][2]["shots"][0].update(lines=[])
        data["clips"][2]["shots"][1].update(lines=["L04", "L05"])
    edit_json(ep.path("shots.json"), both_in_the_short_shot)
    assert "its lines take about" in errors(ep)  # two lines cannot be said in a 2-second shot


def test_clip_prompt_carries_the_lock(ep):
    lock(ep)
    story, bible, shots = plan.story(ep), plan.bible(ep), plan.shots(ep)
    clip = shots.clip("c01")
    refs = checks.clip_refs(bible, clip)
    assert [path for _, path in refs] == ["anchors/booth__yan-mcu.png", "bible/characters/yan/turn.png", "bible/characters/yan/body.png",
                                          "bible/characters/keung/turn.png", "bible/characters/keung/body.png", "anchors/booth__keung-ots.png", "anchors/booth__yan-cu.png", "bible/props/tea/sheet.png"]
    text = prompts.clip_prompt(story, bible, clip, {"yan": 1}, ["Keep the glass on the table."])
    assert "Image 2 is YAN's head from five angles: one and the same person." in text and "Image 8 is the prop TEA." in text
    assert "Pale blue long-sleeved office blouse" in text  # wardrobe rides in every request
    assert "KEUNG says in Hong Kong Cantonese, 快，理所當然，好似講緊常識: {少甜㗎喇，平時落四羹。}" in text
    assert "In frame left to right: YAN, KEUNG." in text  # worked out from the floor map
    assert "Use the voice timbre of Audio 1." in text and "CORRECTIONS" in text
    assert "Shot 1 (0s-2s)" in text and "Shot 3 (5s-6s)" in text and "No music. No subtitles" in text
    assert prompts.words(text) < 950


def test_screen_order_matches_on_both_sides_of_a_conversation(ep):
    lock(ep)
    bible, shots = plan.bible(ep), plan.shots(ep)
    booth = bible.location("booth")
    two_shots = [s for c in shots.clips for s in c.shots if len(s.positions) == 2]
    assert two_shots and all(checks.screen_order(booth, s) == ["yan", "keung"] for s in two_shots)


def test_caption_rules():
    assert captions.burned("少甜㗎喇，平時落四羹。") == "少甜㗎喇 平時落四羹"
    assert captions.burned("你玩我呀？！") == "你玩我呀？！"
    cues = captions.split_line("八五折仲要正價單加雙蛋，你玩我呀？", 10.0, 14.0)
    assert [c.text for c in cues] == ["八五折仲要正價單加雙蛋，", "你玩我呀？"]
    assert cues[0].start == 10.0 and cues[-1].end == 14.0 and cues[0].end == cues[1].start
    one = captions.split_line("我叫少甜喎。", 0.0, 1.2)
    assert len(one) == 1
    text = captions.ass(one, (1080, 1920))
    assert "PlayResY: 1920" in text and "Dialogue: 0,0:00:00.00,0:00:01.20,Line,,0,0,0,,我叫少甜喎" in text
    assert "00:00:00,000 --> 00:00:01,200" in captions.srt(one)


def test_captions_really_burn(tmp_path):
    """Renders a caption through the real ffmpeg/libass and looks for white pixels where it should be."""
    from PIL import Image
    from reels import edit
    source = tmp_path / "black.mp4"
    edit.run(["-f", "lavfi", "-i", "color=black:size=1080x1920:rate=24:duration=2", "-pix_fmt", "yuv420p", str(source)])
    (tmp_path / "c.ass").write_text(captions.ass([captions.Cue(0.0, 2.0, "三羹都叫少甜咩你講笑呀")], (1080, 1920)), encoding="utf-8")
    edit.join([{"path": source}], tmp_path / "out.mp4", (1080, 1920), captions=tmp_path / "c.ass")
    frame = Image.open(edit.frame(tmp_path / "out.mp4", 1.0, tmp_path / "f.png", width=1080)).convert("L")
    box = frame.point(lambda v: 255 if v > 200 else 0).getbbox()
    assert box, "no caption was drawn: is the caption font installed?"
    left, top, right, bottom = box
    assert left > 40 and right < 1040, "an 11-character caption must fit inside the frame"
    assert 1100 < top and bottom < 1500, "captions sit in the lower-middle, above the platform's own buttons"
    assert right - left > 500, "glyphs are missing: the caption font has no Chinese"


def test_speech_alignment_scores_what_was_heard():
    def heard(text, start=0.0, step=0.2):
        return [(ch, start + i * step, start + (i + 1) * step) for i, ch in enumerate(text)]
    lines = [("L01", "我叫少甜喎。"), ("L02", "少甜㗎喇，平時落四羹。")]
    good = speech.align(lines, heard("我叫少甜喎少甜㗎喇平時落四羹"))
    assert good["L01"]["score"] == 1.0 and good["L02"]["score"] == 1.0
    assert good["L01"]["start"] == 0.0 and good["L02"]["start"] == pytest.approx(1.0)
    mandarin = speech.align(lines, heard("我要少糖這個是少糖的"))
    assert mandarin["L02"]["score"] < 0.7


def test_review_text_never_splits_a_number():
    font = review.typeface(34)
    lines = review.wrap("預計總成本：約 US$46.20，片長約 45 秒，試片預算 US$13.80。" * 2, font, 420)
    assert all(font.getlength(line) <= 420 for line in lines)
    joined = "\n".join(lines)
    assert joined.count("US$46.20") == 2 and joined.count("US$13.80") == 2  # never broken across two lines
    assert not any(line[0] in review.NO_START for line in lines)
