"""The whole five-gate flow, rehearsed for free with the mock provider."""
import pytest

from conftest import add_real_refs, edit_json
from reels import checks, cli, edit, plan, qa
from reels.episode import GateError, read_json, write_json
from reels.ledger import MoneyError
from reels.studio import Studio


def fill(ep, media, fail=None):
    """Plays the QA agent: answers every check, optionally failing one."""
    path = qa.verdict_path(ep, media)
    verdict = read_json(path)
    for shot, answers in verdict["shots"].items():
        for name in answers:
            if name != "notes":
                answers[name] = "pass"
    if fail:
        first = next(iter(verdict["shots"]))
        verdict["shots"][first][fail] = "fail"
        verdict["fix"] = ["Keep the blouse pale blue with sleeves pushed to the elbow."]
        verdict["summary"] = "衫變咗色"
    write_json(path, verdict)
    return qa.record(ep, media)


def test_whole_flow_rehearsal(ep):
    name = ep.name

    # Gate 1: story. Nothing can be generated before the user approves a budget.
    assert checks.check_story(ep).ok
    with pytest.raises(GateError):
        cli.cast(name, "yan", n=1, note="")  # story not approved
    cli.review_book(name, "story")
    assert ep.path("review", "1-story.pdf").stat().st_size > 10_000
    cli.approve(name, "story", text="OK，個故事得")
    with pytest.raises(MoneyError):
        cli.cast(name, "yan", n=1, note="")  # picture budget not approved
    with pytest.raises(GateError):
        cli.anchor(name, only="", note="")  # lock gate not passed
    cli.quote(name, "prep", takes=2)
    cli.money(name, "prep", text="批")

    # Gate 2: lock people, places, props.
    add_real_refs(ep)
    for person in ("yan", "keung"):
        cli.cast(name, person, n=2, note="")
    cli.collect(name, wait=5)
    cli.review_book(name, "lock")  # casting round
    for person in ("yan", "keung"):
        cli.pick(name, person, "B")
        cli.body(name, person, note="")
        cli.turn(name, person, redo="", note="")
    for spot in ("booth", "bar"):
        cli.place(name, spot, view="From the aisle looking at the booth.", reverse_view="", note="")
    cli.prop(name, "tea", photo="", note="")
    cli.collect(name, wait=5)
    # A face is locked from five angles: the sheet is built once the four side views are in.
    assert any("five-angle" in e for e in checks.check_bible(ep).errors)
    for person in ("yan", "keung"):
        cli.turn(name, person, redo="", note="")
    assert checks.check_bible(ep).ok, checks.check_bible(ep).errors
    # "Keep it, change one thing" remakes the same file and keeps the old one beside it.
    cli.revise(name, "props", "tea", "sheet", note="two lemon slices instead of three", photo="")
    cli.collect(name, wait=5)
    assert ep.path("bible", "props", "tea", "sheet.prev.png").exists()
    cli.review_book(name, "lock")
    cli.approve(name, "lock", text="鎖定")

    # Gate 3: angles. Anchor frames must pass QA before the user sees them.
    cli.anchor(name, only="", note="")
    cli.collect(name, wait=5)
    assert all("has not passed QA" in e for e in checks.check_shots(ep).errors) and checks.check_shots(ep).errors
    cli.qa_prepare(name, "anchors", redo=False)
    for setup in ("booth__yan-mcu", "booth__keung-ots", "booth__yan-cu", "bar__bar-ms"):
        assert ep.path("anchors", f"{setup}.qa.jpg").exists()
        fill(ep, f"anchors/{setup}.png")
    assert checks.check_shots(ep).errors == []
    # A redone anchor loses its pass until QA has looked at the new picture.
    cli.anchor(name, only="bar/bar-ms", note="lower the camera")
    cli.collect(name, wait=5)
    assert qa.result(ep, "anchors/bar__bar-ms.png") is None and ep.path("anchors", "bar__bar-ms.prev.png").exists()
    cli.qa_prepare(name, "anchors", redo=False)
    fill(ep, "anchors/bar__bar-ms.png")
    cli.quote(name, "draft", takes=2)
    quote = read_json(ep.path("money", "draft.json"))
    assert float(quote["cap"]) == pytest.approx(float(quote["base"]) * 1.3, abs=0.02)
    cli.review_book(name, "angles")
    with pytest.raises(GateError):
        cli.shoot(name, clip="", takes=2)  # angles not approved yet
    cli.approve(name, "angles", text="角度 OK")
    with pytest.raises(MoneyError):
        cli.shoot(name, clip="", takes=2)  # draft budget not approved yet
    cli.money(name, "draft", text="批試片")

    # Gate 4: drafts, QA, the user picks.
    cli.shoot(name, clip="", takes=2)
    cli.collect(name, wait=5)
    cli.qa_prepare(name, "takes", redo=False)
    assert fill(ep, "takes/c01/t1.mp4", fail="wardrobe")["result"] == "fail"
    for media in ("takes/c01/t2.mp4", "takes/c02/t1.mp4", "takes/c02/t2.mp4", "takes/c03/t1.mp4", "takes/c03/t2.mp4"):
        assert fill(ep, media)["result"] == "pass"
    cli.review_book(name, "takes")
    assert ep.path("review", "4-takes.mp4").exists()
    cli.select(name, ["c01=1", "c02=T1", "c03=2"])
    with pytest.raises(GateError):
        cli.approve(name, "takes", text="揀好")  # c01 take 1 failed QA
    cli.select(name, ["c01=2"])
    cli.approve(name, "takes", text="c01 T2、c02 T1、c03 T2")

    # A retake stays inside the approved cap, then the allowance runs out.
    studio = Studio(ep)
    studio.shoot("c01")
    summary = studio.ledger.summary(name)["draft"]
    assert summary["into_retake_allowance"] and float(summary["used"]) <= float(summary["cap"])
    with pytest.raises(MoneyError):
        for _ in range(5):
            studio.shoot("c03")
    cli.collect(name, wait=5)

    # Gate 5, cheapest route: 4K copies of the picked 480p takes (stand-ins here for Kie's output), no 1080p pass.
    import shutil
    for clip, take in {"c01": 2, "c02": 1, "c03": 2}.items():
        ep.path("upscale").mkdir(exist_ok=True)
        shutil.copyfile(ep.path("takes", clip, f"t{take}.mp4"), ep.path("upscale", f"{clip}.mp4"))
    cli.cut(name, draft=False, upscaled=True)
    info = edit.probe(ep.path("out", "final-4k.mp4"))
    assert (info["width"], info["height"]) == (2160, 3840) and info["audio"]

    # Gate 5: finals and the cut.
    cli.quote(name, "final", takes=2)
    cli.money(name, "final", text="批 1080p")
    cli.finalize(name)
    cli.collect(name, wait=5)
    cli.qa_prepare(name, "finals", redo=False)
    for clip in ("c01", "c02", "c03"):
        fill(ep, f"finals/{clip}.mp4")
    cli.cut(name, draft=False)
    info = edit.probe(ep.path("out", "final.mp4"))
    assert (info["width"], info["height"]) == (1080, 1920) and info["audio"]
    assert info["duration"] == pytest.approx(15, abs=0.3)
    assert "我叫少甜喎" in ep.path("out", "final.srt").read_text(encoding="utf-8")
    cli.review_book(name, "final")
    cli.approve(name, "final", text="出得")
    assert set(ep.summary().values()) == {"approved"}


def test_changing_a_locked_file_reopens_the_gate(ep):
    cli.quote(ep.name, "prep", takes=2)
    cli.money(ep.name, "prep", text="批")
    cli.approve(ep.name, "story", text="OK")
    ep.require("story")
    edit_json(ep.path("story.json"), lambda d: d["lines"][0].update(text="我叫走甜喎。"))
    assert ep.gate_status("story") == ("stale", ["story.json"])
    with pytest.raises(GateError, match="re-approve"):
        ep.require("story")
    with pytest.raises(GateError):  # money approved against the old story no longer counts either
        Studio(ep).approve_money("prep", "批")


def test_approval_needs_the_users_words_and_a_clean_check(ep):
    with pytest.raises(GateError):
        ep.approve("story", "  ", ["story.json"])
    edit_json(ep.path("story.json"), lambda d: d["beats"][0].update(seconds=5))
    with pytest.raises(GateError):
        cli.approve(ep.name, "story", text="OK")
    assert plan.story(ep).beats[0].seconds == 5
