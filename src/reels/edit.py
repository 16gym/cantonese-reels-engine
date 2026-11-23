"""Cutting with FFmpeg: join clips, level the sound, burn captions. No agent, no model."""
import json
import subprocess
from pathlib import Path

from . import config


def run(arguments: list[str], cwd: Path | None = None) -> None:
    result = subprocess.run(["ffmpeg", "-v", "error", "-y", *arguments], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.strip()[-800:]}")


def probe(path: Path) -> dict:
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height,r_frame_rate", "-of", "json", str(path)],
                            capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), {})
    return {"duration": float(data["format"]["duration"]), "audio": any(s["codec_type"] == "audio" for s in data["streams"]),
            "width": video.get("width"), "height": video.get("height"), "fps": video.get("r_frame_rate", "24/1")}


def loudness(path: Path) -> float | None:
    """Integrated loudness in LUFS, or None for silence."""
    result = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "loudnorm=print_format=json", "-f", "null", "-"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        value = float(json.loads(result.stderr[result.stderr.rindex("{"):])["input_i"])
    except (ValueError, KeyError):
        return None
    return value if value > -70 else None


def frame(video: Path, seconds: float, target: Path, width: int = 480) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    run(["-ss", f"{max(0, seconds):.2f}", "-i", str(video), "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "3", str(target)])
    return target


def join(parts: list[dict], out: Path, size: tuple[int, int], captions: Path | None = None, music: Path | None = None) -> float:
    """Joins clips into one file. parts: {"path", "start"?, "end"?, "label"? (png drawn top-left)}. Returns the duration."""
    if not parts:
        raise RuntimeError("Nothing to join")
    width, height = size
    info = [probe(Path(p["path"])) for p in parts]
    fps = info[0]["fps"]
    inputs, graph, total = [], [], 0.0
    for part in parts:
        inputs += ["-i", str(Path(part["path"]).resolve())]
    labels = {}
    for index, part in enumerate(parts):
        if part.get("label"):
            labels[index] = len(inputs) // 2
            inputs += ["-i", str(Path(part["label"]).resolve())]
    for index, (part, meta) in enumerate(zip(parts, info)):
        start, end = part.get("start") or 0.0, min(part.get("end") or meta["duration"], meta["duration"])
        total += end - start
        graph.append(f"[{index}:v]trim=start={start}:end={end},setpts=PTS-STARTPTS,scale={width}:{height}:force_original_aspect_ratio=decrease,"
                     f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p[s{index}]")
        if index in labels:
            graph.append(f"[s{index}][{labels[index]}:v]overlay=24:24[v{index}]")
        else:
            graph.append(f"[s{index}]null[v{index}]")
        level = loudness(Path(part["path"])) if meta["audio"] else None
        if level is None:  # no sound at all: keep it silent rather than amplify nothing
            graph.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={end - start}[a{index}]")
        else:
            gain = max(-config.MAX_GAIN_DB, min(config.MAX_GAIN_DB, config.TARGET_LUFS - level))
            graph.append(f"[{index}:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS,aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,volume={gain:.2f}dB[a{index}]")
    graph.append("".join(f"[v{i}][a{i}]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=1:a=1[vc][ac]")
    graph.append("[ac]alimiter=limit=0.84[an]")  # catches peaks after the gain, about -1.5 dB
    audio = "[an]"
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(Path(music).resolve())]
        graph.append(f"[{len(inputs) // 2 - 1}:a]volume={config.MUSIC_VOLUME},aresample=48000[mu];[an][mu]amix=inputs=2:duration=first:normalize=0[am]")
        audio = "[am]"
    video = "[vc]"
    cwd = None
    if captions:
        # The ass filter mangles Windows drive letters, so run inside the captions folder and name the file bare.
        cwd = captions.parent
        graph.append(f"[vc]ass={captions.name}[vo]")
        video = "[vo]"
    out.parent.mkdir(parents=True, exist_ok=True)
    run([*inputs, "-filter_complex", ";".join(graph), "-map", video, "-map", audio, "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-t", f"{total:.3f}", "-movflags", "+faststart", str(out.resolve())], cwd=cwd)
    return round(total, 3)
