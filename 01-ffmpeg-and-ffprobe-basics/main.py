"""Module 01: ffmpeg and ffprobe basics.

Run:  python main.py

Everything an MCP wrapper needs to know before it writes a line of server code:
how to find the binaries, how to make test media out of thin air, how to read
a file's facts as JSON, and what a minimal, well-behaved transcode looks like.
The script checks its own results with assert.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

INSTALL_HINT = (
    "Install ffmpeg: Windows `winget install Gyan.FFmpeg`, macOS `brew install ffmpeg`, "
    "Debian/Ubuntu `sudo apt install ffmpeg`; or set FFMPEG_PATH / FFPROBE_PATH."
)


# ---------------------------------------------------------------------------
# Part 1: finding the binaries
# ---------------------------------------------------------------------------


def find_tool(name: str) -> str:
    """An explicit override beats PATH, and a missing tool is an error with a fix."""
    override = os.environ.get(f"{name.upper()}_PATH")
    if override:
        if not os.path.isfile(override):
            raise FileNotFoundError(f"{name.upper()}_PATH={override!r} does not exist. {INSTALL_HINT}")
        return override
    found = shutil.which(name)
    if found is None:
        raise FileNotFoundError(f"`{name}` is not on PATH. {INSTALL_HINT}")
    return found


# ---------------------------------------------------------------------------
# Part 2: media out of thin air (lavfi)
# ---------------------------------------------------------------------------


def generate_clip(path: Path, seconds: int = 3) -> None:
    """A test card with a 440 Hz tone. No camera, no downloads, same bytes every run."""
    cmd = [
        find_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"testsrc2=size=320x240:rate=25:duration={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
    ]  # fmt: skip
    subprocess.run(cmd, check=True, stdin=subprocess.DEVNULL)


# ---------------------------------------------------------------------------
# Part 3: ffprobe as a JSON API
# ---------------------------------------------------------------------------


def probe(path: Path) -> dict:  # type: ignore[type-arg]
    """-show_format gives container facts, -show_streams gives one object per stream."""
    out = subprocess.run(
        [find_tool("ffprobe"), "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )  # fmt: skip
    if out.returncode != 0:
        raise ValueError(f"ffprobe could not read {path.name}: {out.stderr.strip()}")
    return json.loads(out.stdout)  # type: ignore[no-any-return]


def summarize(info: dict) -> str:  # type: ignore[type-arg]
    fmt = info["format"]
    lines = [f"{fmt['format_name']}  {float(fmt['duration']):.2f}s  {int(fmt['size'])} bytes"]
    for s in info["streams"]:
        if s["codec_type"] == "video":
            lines.append(f"  video: {s['codec_name']} {s['width']}x{s['height']} {s['avg_frame_rate']}")
        elif s["codec_type"] == "audio":
            lines.append(f"  audio: {s['codec_name']} {s['sample_rate']} Hz, {s['channels']} ch")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Part 4: a minimal, well-behaved transcode
# ---------------------------------------------------------------------------


def transcode(src: Path, dst: Path) -> None:
    cmd = [
        find_tool("ffmpeg"),
        "-hide_banner",       # no version banner
        "-nostdin",           # never wait for a keypress: we are not a terminal
        "-loglevel", "error", # only real problems on stderr
        "-y",                 # we decided about overwriting before getting here
        "-i", str(src),
        "-map", "0:v:0", "-map", "0:a:0?",  # first video, first audio IF it exists ('?')
        "-c:v", "libx264", "-crf", "28", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "96k",
        str(dst),
    ]  # fmt: skip
    subprocess.run(cmd, check=True, stdin=subprocess.DEVNULL)


def main() -> None:
    print("ffmpeg :", find_tool("ffmpeg"))
    print("ffprobe:", find_tool("ffprobe"))
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        clip = d / "clip.mp4"
        generate_clip(clip, seconds=3)

        info = probe(clip)
        print(summarize(info))
        video = next(s for s in info["streams"] if s["codec_type"] == "video")
        audio = next(s for s in info["streams"] if s["codec_type"] == "audio")
        assert video["codec_name"] == "h264" and (video["width"], video["height"]) == (320, 240)
        assert audio["codec_name"] == "aac" and audio["sample_rate"] == "48000"
        assert abs(float(info["format"]["duration"]) - 3.0) < 0.2

        # ffprobe reports numbers as STRINGS in JSON (sample_rate, duration, size): convert.
        assert isinstance(info["format"]["duration"], str)

        small = d / "small.mp4"
        transcode(clip, small)
        assert abs(float(probe(small)["format"]["duration"]) - 3.0) < 0.2

        # A video with no audio: '-map 0:a:0?' makes the audio optional instead of fatal.
        silent = d / "silent.mp4"
        subprocess.run(
            [find_tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i",
             "testsrc2=size=320x240:rate=25:duration=1", "-pix_fmt", "yuv420p", str(silent)],
            check=True, stdin=subprocess.DEVNULL,
        )  # fmt: skip
        transcode(silent, d / "silent-small.mp4")
        kinds = [s["codec_type"] for s in probe(d / "silent-small.mp4")["streams"]]
        assert kinds == ["video"], kinds

        # A file that is not media: ffprobe fails, and we turn that into a readable error.
        junk = d / "junk.mp4"
        junk.write_bytes(b"not media at all" * 100)
        try:
            probe(junk)
        except ValueError as e:
            print("junk ->", str(e)[:90])
        else:
            raise AssertionError("junk should not probe")

        # No ffmpeg on PATH: the error says what to do.
        old = os.environ["PATH"]
        os.environ["PATH"] = str(d)
        os.environ.pop("FFMPEG_PATH", None)
        try:
            find_tool("ffmpeg")
        except FileNotFoundError as e:
            assert "winget install" in str(e)
        else:
            raise AssertionError("expected FileNotFoundError")
        finally:
            os.environ["PATH"] = old
    print("module 01 OK")


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        sys.exit(str(e))
