"""Review books: one PDF per gate, written for the user to read on a phone and answer by number.

Text rules (the user's standing rules for anything read on a screen): one idea per line,
numbers and codes never split across lines, plain Cantonese with English terms kept.
"""
import re
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import checks, config, edit, plan, prompts, qa
from .ledger import fmt
from .episode import Episode, read_json

W, H, M = 1240, 1754, 80
INK, GREY, RULE, ACCENT = (24, 24, 24), (110, 110, 110), (215, 215, 215), (176, 58, 46)
TOKEN = re.compile(r"[A-Za-z0-9$%.,:/'#@&+\-–()]+|\s+|.", re.S)
NO_START = "，。！？、；：」』）)…"
SIZE_NAME = {"ECU": "大特寫", "CU": "近鏡", "MCU": "中近鏡", "MS": "半身", "MLS": "七分身", "LS": "全身遠鏡", "INSERT": "物件特寫", "WIDE": "環境鏡"}


def typeface(size: int, bold: bool = False):
    path = config.font(bold)
    return ImageFont.truetype(path, size) if path else ImageFont.load_default()


def wrap(text: str, font, width: int) -> list[str]:
    """Wraps mixed Chinese and English. A number, price or code is one token and never splits."""
    lines, line = [], []
    for token in TOKEN.findall(text):
        if token.isspace() and not line:
            continue
        if line and font.getlength("".join(line) + token) > width:
            # A closing mark may not start a line: it takes the character before it down with it.
            carry = [line.pop()] if token in NO_START and len(line) > 1 else []
            lines.append("".join(line).rstrip())
            line = carry + ([] if token.isspace() else [token])
        else:
            line.append(token)
    if "".join(line).strip():
        lines.append("".join(line).rstrip())
    return lines or [""]


class Book:
    def __init__(self, episode: str, gate: str):
        self.episode, self.gate, self.pages = episode, gate, []
        self._page()

    def _page(self):
        self.image = Image.new("RGB", (W, H), "white")
        self.draw = ImageDraw.Draw(self.image)
        self.pages.append(self.image)
        self.draw.text((M, 36), f"{self.episode} · {self.gate}", fill=GREY, font=typeface(24))
        number = f"第 {len(self.pages)} 頁"
        self.draw.text((W - M - typeface(24).getlength(number), 36), number, fill=GREY, font=typeface(24))
        self.y = M + 20

    def room(self, height: int):
        if self.y + height > H - M:
            self._page()

    def text(self, text: str, size: int = 34, bold: bool = False, fill=INK, indent: int = 0, after: int = 10):
        font = typeface(size, bold)
        for paragraph in str(text).split("\n"):
            for line in wrap(paragraph, font, W - 2 * M - indent):
                self.room(int(size * 1.5))
                self.draw.text((M + indent, self.y), line, fill=fill, font=font)
                self.y += int(size * 1.5)
        self.y += after

    def title(self, text: str):
        self.text(text, 58, True, after=4)
        self.text(f"出冊時間：{datetime.now():%m月%d日 %H:%M}", 24, fill=GREY, after=24)

    def heading(self, text: str):
        self.room(520)  # a heading never sits alone at the foot of a page
        self.y += 18
        self.draw.line((M, self.y, W - M, self.y), fill=RULE, width=2)
        self.y += 22
        self.text(text, 42, True, after=12)

    def note(self, text: str):
        self.text(text, 26, fill=GREY, after=8)

    def ask(self, questions: list[str]):
        self.heading("你要答")
        for number, question in enumerate(questions, 1):
            self.text(f"{number}. {question}", 34, fill=ACCENT, after=14)

    def pictures(self, items: list[tuple[str, Path, str]], columns: int = 2, tallest: int = 620):
        """items: (badge, path, caption). Badges are what the user quotes back, e.g. 1A."""
        gap = 24
        cell = (W - 2 * M - gap * (columns - 1)) // columns
        for start in range(0, len(items), columns):
            row, heights = items[start:start + columns], []
            tiles = []
            for badge, path, caption in row:
                picture = Image.open(path).convert("RGB") if Path(path).is_file() else Image.new("RGB", (cell, cell // 2), (238, 238, 238))
                picture.thumbnail((cell, tallest))
                lines = [l for part in caption.split("\n") for l in wrap(part, typeface(24), cell)] if caption else []
                tiles.append((badge, picture, lines))
                heights.append(picture.height + len(lines) * 34 + 16)
            self.room(max(heights) + 20)
            for column, (badge, picture, lines) in enumerate(tiles):
                x = M + column * (cell + gap)
                self.image.paste(picture, (x, self.y))
                if badge:
                    font = typeface(30, True)
                    box = int(font.getlength(badge)) + 24
                    self.draw.rectangle((x, self.y, x + box, self.y + 46), fill=(20, 20, 20))
                    self.draw.text((x + 12, self.y + 5), badge, fill="white", font=font)
                for index, line in enumerate(lines):
                    self.draw.text((x, self.y + picture.height + 8 + index * 34), line, fill=GREY, font=typeface(24))
            self.y += max(heights) + 20

    def row(self, badge: str, path: Path, lines: list[tuple[str, int, bool, tuple]], picture_width: int = 330):
        """A picture on the left, its facts on the right. lines: (text, size, bold, colour)."""
        picture = Image.open(path).convert("RGB") if Path(path).is_file() else Image.new("RGB", (picture_width, picture_width), (238, 238, 238))
        picture.thumbnail((picture_width, 640))
        column = W - 2 * M - picture_width - 36
        wrapped = [(line, size, bold, fill) for text, size, bold, fill in lines for line in wrap(text, typeface(size, bold), column)]
        height = max(picture.height, sum(int(size * 1.5) for _, size, _, _ in wrapped)) + 36
        self.room(height)
        self.image.paste(picture, (M, self.y))
        font = typeface(30, True)
        self.draw.rectangle((M, self.y, M + int(font.getlength(badge)) + 24, self.y + 46), fill=(20, 20, 20))
        self.draw.text((M + 12, self.y + 5), badge, fill="white", font=font)
        y = self.y
        for line, size, bold, fill in wrapped:
            self.draw.text((M + picture_width + 36, y), line, fill=fill, font=typeface(size, bold))
            y += int(size * 1.5)
        self.y += height

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.pages[0].save(path, "PDF", save_all=True, append_images=self.pages[1:], resolution=150)
        return path


# ---- floor map ----------------------------------------------------------------------
def floor_map(location, clips=(), names=None) -> Image.Image:
    """Top view of a location: fixtures, marks, and for the given clips the cameras and the eyeline."""
    names = names or {}
    width = 1000
    height = int(width / location.map.aspect)
    image = Image.new("RGB", (width, height), (248, 248, 246))
    draw, font = ImageDraw.Draw(image), typeface(24)
    def at(mark):
        x, y = location.map.marks[mark]
        return x * width, y * height
    draw.rectangle((2, 2, width - 3, height - 3), outline=INK, width=4)
    for fixture in location.map.fixtures:
        box = (fixture.x * width, fixture.y * height, (fixture.x + fixture.w) * width, (fixture.y + fixture.h) * height)
        draw.rectangle(box, fill=(224, 224, 220), outline=GREY, width=2)
        draw.text((box[0] + 8, box[1] + 6), fixture.name, fill=GREY, font=font)
    cameras, people = {}, {}
    for clip in clips:
        for shot in clip.shots:
            cameras.setdefault((shot.camera.at, shot.camera.look_at if shot.camera.look_at in location.map.marks else shot.positions.get(shot.camera.look_at)), []).append(shot.id)
            people.update({mark: name for name, mark in shot.positions.items()})
        if clip.axis:
            first = next((s for s in clip.shots if set(clip.axis) <= set(s.positions)), None)
            if first:
                draw.line((*at(first.positions[clip.axis[0]]), *at(first.positions[clip.axis[1]])), fill=ACCENT, width=3)
    for mark in location.map.marks:
        x, y = at(mark)
        if mark in people:
            draw.ellipse((x - 16, y - 16, x + 16, y + 16), fill=INK)
            draw.text((x + 22, y - 20), names.get(people[mark], people[mark]), fill=INK, font=typeface(30, True))
        elif not clips:  # the lock book shows every spot; the angles book only what the clip uses
            draw.ellipse((x - 12, y - 12, x + 12, y + 12), fill=(170, 170, 170))
            draw.text((x + 18, y - 16), mark, fill=GREY, font=font)
    blue, bold = (40, 90, 160), typeface(26, True)
    for (camera, target), shot_ids in cameras.items():
        if target is None:
            continue
        (cx, cy), (tx, ty) = at(camera), at(target)
        length = max(1.0, ((tx - cx) ** 2 + (ty - cy) ** 2) ** 0.5)
        ux, uy = (tx - cx) / length, (ty - cy) / length
        draw.polygon([(cx + ux * 46, cy + uy * 46), (cx - uy * 22, cy + ux * 22), (cx + uy * 22, cy - ux * 22)], fill=blue)
        label = "機位 " + " ".join(shot_ids)
        left = min(max(8, cx - bold.getlength(label) / 2), width - bold.getlength(label) - 8)
        draw.text((left, min(height - 40, cy + 30)), label, fill=blue, font=bold)
    return image


def _map_file(ep: Episode, location, clips, name: str, names=None) -> Path:
    path = ep.path("review", "maps", f"{name}.png")
    path.parent.mkdir(parents=True, exist_ok=True)
    floor_map(location, clips, names).save(path)
    return path


# ---- the five books -------------------------------------------------------------------
def story_book(ep: Episode) -> Path:
    story, report = plan.story(ep), checks.check_story(ep)
    cost, book = report.info["cost"], Book(ep.name, "第 1 關 · 故事")
    book.title(story.title)
    book.text(story.logline, 36)
    book.heading("幾長、幾多錢")
    book.text(f"片長：約 {report.info['seconds']} 秒\n對白：{report.info['lines']} 句\n預計總成本：約 {fmt(cost['total'], cost['unit'])}", 36)
    book.note(f"圖（選角、角色表、場景圖、定位畫面、試聲）：約 {fmt(cost['prep'], cost['unit'])}\n" + (f"720p 拍攝，連重拍額度：約 {fmt(cost['draft_cap'], cost['unit'])}\n揀中嗰個 take 就係成片，冇 1080p 嗰筆" if ep.state.get("quality") == "720p" else f"480p 試片，連重拍額度：約 {fmt(cost['draft_cap'], cost['unit'])}\n1080p 成片：約 {fmt(cost['final'], cost['unit'])}") + "\n以上係估算，每次批錢之前會再報實數。")
    book.heading("頭 2 秒（Hook）")
    book.text(story.hook)
    book.heading("人物")
    for role in story.characters:
        book.text(f"{role.name}（{role.id}）", 36, True, after=2)
        book.text(f"{role.who}\n想要：{role.want}", after=16)
    book.heading("地點同道具")
    for place in [*story.locations, *story.props]:
        book.text(f"{place.name}（{place.id}）", 34, True, after=2)
        if place.why:
            book.text(place.why, after=12)
    book.heading("分段")
    for beat in story.beats:
        book.text(f"{beat.id} · {beat.seconds} 秒", 34, True, after=2)
        book.text(beat.what, after=14)
    book.heading("對白稿")
    names = {r.id: r.name for r in story.characters}
    for line in story.lines:
        book.text(f"{line.id}　{names.get(line.speaker, line.speaker)}", 28, True, GREY, after=0)
        book.text(f"「{line.text}」", 38, after=2)
        if line.delivery:
            book.note(line.delivery)
        book.y += 8
    book.heading("結尾")
    book.text(story.ending)
    if story.brand:
        book.text(f"要帶出：{story.brand}")
    if report.errors or report.warnings:
        book.heading("要留意")
        for item in report.errors:
            book.text(f"未過檢查：{item}", 28, fill=ACCENT)
        for item in report.warnings:
            book.text(item, 28)
    book.ask(["個故事同對白 OK 嗎？\n要改就講編號，例如「L03 改做……」。",
              f"批唔批出圖嘅預算 {fmt(cost['prep'], cost['unit'])}？\n包選角、角色表、場景圖、定位畫面同試聲。"])
    return book.save(ep.path("review", "1-story.pdf"))


def lock_book(ep: Episode) -> Path:
    bible, book = plan.bible(ep), Book(ep.name, "第 2 關 · 鎖定")
    licences = {r.file: r for r in plan.real_refs(ep)}
    book.title("鎖定人物、場景、道具")
    book.note("呢一關揀定之後，之後每一格都要跟返呢度啲圖。")
    questions = []
    for number, character in enumerate(bible.characters, 1):
        book.heading(f"人物 {number}：{character.name}")
        folder = ep.path("bible", "characters", character.id)
        if ep.exists(character.refs.get("face", "")):
            sheet = [("樣", ep.path(character.refs["face"]), "")]
            if ep.exists(character.refs.get("body", "")):
                sheet.append(("全身", ep.path(character.refs["body"]), ""))
            book.pictures(sheet)
            views = [(prompts.TURN[v][0], folder / f"turn-{v}.png", "") for v in ("l90", "l45", "r45", "r90") if (folder / f"turn-{v}.png").exists()]
            if views:
                book.pictures(views, columns=4, tallest=420)
                questions.append(f"人物 {number}（{character.name}）四個側面同正面係咪同一個人？")
            book.text(character.zh, 30)
            voices = sorted(folder.glob("voice-*.mp4"))
            for clip in voices:
                book.note(f"試聲片（要聽）：\n{clip.resolve()}")
            if (folder / "voice.wav").exists():
                book.note("把聲已鎖定。")
            elif voices:
                questions.append(f"人物 {number} 把聲用邊條試聲片？廣東話自然嗎？")
            if character.real_person:
                book.note(f"用真人樣：{character.real_person.person}（有同意記錄）")
        else:
            candidates = plan.candidates(ep, character.id)
            book.pictures([(f"{number}{chr(65 + i)}", path, "") for i, path in enumerate(candidates)])
            book.text(character.zh, 30)
            questions.append(f"人物 {number}（{character.name}）揀邊個樣？\n答編號，例如「{number}B」，或者講要點改。")
    for number, location in enumerate(bible.locations, 1):
        book.heading(f"場景 {number}：{location.name}")
        book.text(location.zh, 30)
        real = []
        for ref in location.real_refs:
            source = licences.get(ref)
            real.append(("真實相", ep.path(ref), f"{source.author} · {source.licence}" if source else "未記出處"))
        book.pictures(real, columns=3, tallest=360)
        labels = {"master": "主視角", "reverse": "反方向", "front": "向前望", "doorway": "由門口望入", "dooropen": "門打開"}
        built = [(labels.get(slot, slot), ep.path(file), "") for slot, file in location.refs.items() if ep.exists(file)]
        if built:
            book.pictures(built, tallest=420)
            if len(built) > 1:
                questions.append(f"場景 {number}（{location.name}）每個視角係咪同一個地方、同一款？左右有冇調轉？")
        book.pictures([("俯視走位圖", _map_file(ep, location, (), f"lock-{location.id}"), "黑點係可以企人或者擺機嘅位")], columns=1, tallest=560)
        questions.append(f"場景 {number}（{location.name}）個樣同真實相似唔似？格局啱唔啱？")
    if bible.props:
        book.heading("道具")
        book.pictures([(f"道具 {i}", ep.path(p.refs.get("sheet", "")), f"{p.name}\n{p.zh}") for i, p in enumerate(bible.props, 1)], columns=3, tallest=360)
        questions.append("道具個樣啱唔啱？")
    questions.append("全部 OK 就講「鎖定」。\n鎖定之後人、場景、道具唔會再變。")
    book.ask(questions)
    return book.save(ep.path("review", "2-lock.pdf"))


def angles_book(ep: Episode) -> Path:
    story, bible, shots, book = plan.story(ep), plan.bible(ep), plan.shots(ep), Book(ep.name, "第 3 關 · 角度")
    lines = {l.id: l for l in story.lines}
    names = {c.id: c.name for c in bible.characters}
    book.title("每個鏡頭嘅角度")
    book.note("每張圖係該鏡頭第一格嘅構圖。片會跟住呢啲圖拍。")
    for clip in shots.clips:
        location = bible.location(clip.location)
        book.heading(f"{clip.id} · {location.name} · {clip.duration} 秒")
        book.text(clip.zh, 30)
        book.pictures([("機位圖", _map_file(ep, location, [clip], f"angles-{clip.id}", names), "藍色三角係機位，尖嘅一邊係望嘅方向。\n紅線係兩個人嘅視線，機位全部要喺同一邊。")], columns=1, tallest=460)
        for shot in clip.shots:
            order = checks.screen_order(location, shot)
            facts = [(f"{shot.start}–{shot.end} 秒 · {SIZE_NAME[shot.size]}", 28, True, GREY), (shot.zh, 32, False, INK)]
            if len(order) > 1:
                facts.append(("畫面左至右：" + "、".join(names.get(n, n) for n in order), 26, False, GREY))
            for key in shot.lines:
                who = names.get(lines[key].speaker, lines[key].speaker) + ("（畫外音）" if key in shot.offscreen else "")
                facts.append((f"{who}：「{lines[key].text}」", 34, True, INK))
            book.row(shot.id, ep.path(plan.anchor_path(clip.location, shot.setup)), facts)
    questions = ["每個鏡嘅角度同構圖 OK 嗎？\n要改就講鏡號，例如「s03 要近啲」。"]
    quote = ep.path("money", "draft.json")
    if quote.exists():
        data = read_json(quote)
        questions.append(f"批唔批試片預算 {fmt(data['cap'], data['unit'])}？\n{ep.state.get('quality') == '720p' and '720p' or '480p'}，每段 {data['takes']} 個 take 係 {fmt(data['base'], data['unit'])}，另加三成重拍額度。")
    book.ask(questions)
    return book.save(ep.path("review", "3-angles.pdf"))


def takes_video(ep: Episode) -> Path | None:
    """All passing takes back to back, each stamped with its name, so the user watches one file."""
    shots, parts = plan.shots(ep), []
    for clip in shots.clips:
        for video in sorted(ep.path("takes", clip.id).glob("t*.mp4")):
            media = f"takes/{clip.id}/{video.name}"
            if qa.result(ep, media) != "pass":
                continue
            label = ep.path("review", "labels", f"{clip.id}-{video.stem}.png")
            label.parent.mkdir(parents=True, exist_ok=True)
            text = f"{clip.id} {video.stem.upper()}"
            badge = Image.new("RGB", (int(typeface(44, True).getlength(text)) + 32, 68), (20, 20, 20))
            ImageDraw.Draw(badge).text((16, 8), text, fill="white", font=typeface(44, True))
            badge.save(label)
            parts.append({"path": video, "label": label})
    if not parts:
        return None
    out = ep.path("review", "4-takes.mp4")
    edit.join(parts, out, config.DRAFT_SIZE)
    return out


def takes_book(ep: Episode) -> Path:
    bible, shots, book = plan.bible(ep), plan.shots(ep), Book(ep.name, "第 4 關 · 揀 take")
    book.title("揀 take")
    video = takes_video(ep)
    if video:
        book.text("先睇呢條片，入面每個 take 左上角有名：", 32, after=4)
        book.note(str(video.resolve()))
    failed, picks = [], []
    for clip in shots.clips:
        book.heading(f"{clip.id} · {bible.location(clip.location).name} · {clip.duration} 秒")
        passing = 0
        for take in sorted(ep.path("takes", clip.id).glob("t*.mp4")):
            media = f"takes/{clip.id}/{take.name}"
            verdict = read_json(qa.verdict_path(ep, media)) if qa.verdict_path(ep, media).exists() else {}
            if verdict.get("result") != "pass":
                failed.append(f"{clip.id} {take.stem.upper()}：{verdict.get('summary') or '、'.join(verdict.get('failed', [])) or 'QA 未驗'}")
                continue
            passing += 1
            frames = [(f"{take.stem.upper()} · {s.id}", take.with_suffix(".qa") / f"{s.id}-1.jpg", "") for s in clip.shots]
            book.pictures(frames, columns=min(4, len(frames)), tallest=420)
            if verdict.get("summary"):
                book.note(f"QA：{verdict['summary']}")
            if verdict.get("overridden_by_user"):
                book.note(f"QA 本來唔過，你話可以：「{verdict['overridden_by_user']}」")
        if not passing:
            book.text("呢段暫時冇 take 過到 QA。", fill=ACCENT)
        picks.append(clip.id)
    if failed:
        book.heading("QA 篩走咗嘅 take")
        for item in failed:
            book.text(item, 28)
    book.ask(["每段揀邊個 take？\n例如「" + "、".join(f"{c} T1" for c in picks[:3]) + "」。", "邊段把聲或者廣東話唔自然？\n（QA 聽唔到聲，呢樣靠你。）"])
    return book.save(ep.path("review", "4-takes.pdf"))


def final_book(ep: Episode) -> Path:
    shots, book = plan.shots(ep), Book(ep.name, "第 5 關 · 成片")
    book.title("成片")
    final = ep.path("out", "final.mp4")
    if final.exists():
        info = edit.probe(final)
        book.text("睇呢條片：", 32, after=4)
        book.note(str(final.resolve()))
        book.text(f"片長：{info['duration']:.1f} 秒\n尺寸：{info['width']}×{info['height']}", 30)
        frames = [(c.id, edit.frame(final, start + 0.5, ep.path("review", "frames", f"{c.id}.jpg")), "") for c, start in zip(shots.clips, _starts(ep, shots))]
        book.pictures(frames, columns=3, tallest=520)
    else:
        book.text("成片未剪。", fill=ACCENT)
    quote = ep.path("money", "final.json")
    if quote.exists():
        book.note(f"1080p 已批預算：{fmt(read_json(quote)['cap'], read_json(quote)['unit'])}")
    book.ask(["成片 OK 嗎？\n要改就講秒數同問題，例如「0:12 字幕早咗」。"])
    return book.save(ep.path("review", "5-final.pdf"))


def _starts(ep: Episode, shots) -> list[float]:
    starts, clock = [], 0.0
    for clip in shots.clips:
        starts.append(clock)
        source = ep.path("finals", f"{clip.id}.mp4")
        clock += edit.probe(source)["duration"] if source.exists() else clip.duration
    return starts


BOOKS = {"story": story_book, "lock": lock_book, "angles": angles_book, "takes": takes_book, "final": final_book}
