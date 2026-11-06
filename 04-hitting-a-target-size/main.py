"""Module 04: hitting a target file size.

Run:  python main.py

"Make this fit in 10 MB" is arithmetic first and encoding second:

    file size  =  (video bitrate + audio bitrate)  x  duration  / 8

so you pick the bitrates, not the quality. CRF ("constant quality") cannot do this:
it spends whatever the picture needs and tells you the size afterwards.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"
MIB = 1024 * 1024

# ---------------------------------------------------------------------------
# The maths
# ---------------------------------------------------------------------------

SAFETY = 0.95          # container overhead + rate-control error: aim 5% under
MIN_VIDEO_BPS = 60_000 # below this there is no picture left to save
BPP_FLOOR = 0.045      # bits per pixel per frame below which H.264 turns to mush
LADDER = (2160, 1440, 1080, 720, 480, 360, 240, 144)


@dataclass
class Budget:
    video_bps: int
    audio_bps: int
    height: int


def plan(target_mb: float, duration_s: float, has_audio: bool, w: int, h: int, fps: float) -> Budget:
    total_bps = target_mb * MIB * 8 * SAFETY / duration_s       # the whole bit budget per second
    audio = 0
    if has_audio:
        audio = 32_000
        for step in (128_000, 96_000, 64_000, 32_000):          # audio may take at most 1/4
            if step <= total_bps / 4:
                audio = step
                break
    video = int(total_bps - audio)
    if video < MIN_VIDEO_BPS:
        need = (MIN_VIDEO_BPS + audio) * duration_s / 8 / MIB / SAFETY
        raise ValueError(f"{target_mb:g} MB is too small for {duration_s:.0f}s (needs ~{need:.2f} MB)")
    chosen = LADDER[-1]
    for cand in [h] + [x for x in LADDER if x < h]:             # shrink until the bits are enough
        if video / ((w * cand / h) * cand * fps) >= BPP_FLOOR:
            chosen = cand
            break
    return Budget(video, audio, chosen)


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------


def ff(*args: str) -> None:
    subprocess.run([FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error", "-y", *args],
                   check=True, stdin=subprocess.DEVNULL)  # fmt: skip


def probe(path: Path) -> dict:  # type: ignore[type-arg]
    out = subprocess.run([FFPROBE, "-v", "error", "-print_format", "json", "-show_format",
                          "-show_streams", str(path)], capture_output=True, text=True, check=True)  # fmt: skip
    return json.loads(out.stdout)  # type: ignore[no-any-return]


def two_pass(src: Path, dst: Path, b: Budget, capped: bool = True) -> None:
    """Pass 1 analyses the whole video (output thrown away: `-f null -`), pass 2 spends the
    bit budget where the picture needs it. The log files tie the two passes together."""
    log = str(dst.with_name(f"pass-{uuid.uuid4().hex[:8]}"))
    scale = ["-vf", f"scale=-2:{b.height}"]
    rate = ["-b:v", str(b.video_bps), "-pix_fmt", "yuv420p"]
    if capped:  # VBV: forbid long stretches above the average. Cuts the overshoot noticeably.
        rate += ["-maxrate", str(b.video_bps), "-bufsize", str(b.video_bps * 2)]
    enc = ["-c:v", "libx264", "-preset", "medium", *rate]
    try:
        ff("-i", str(src), "-map", "0:v:0", *scale, *enc, "-pass", "1", "-passlogfile", log, "-an", "-f", "null", "-")
        ff("-i", str(src), "-map", "0:v:0", "-map", "0:a:0?", *scale, *enc, "-pass", "2", "-passlogfile", log,
           "-c:a", "aac", "-b:a", str(b.audio_bps), "-movflags", "+faststart", str(dst))  # fmt: skip
    finally:
        for f in dst.parent.glob(Path(log).name + "*"):  # x264 leaves .log and .mbtree files
            f.unlink()


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        src = d / "src.mp4"
        # Noisy on purpose: a clean test card compresses to nothing and proves nothing.
        ff("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=6",
           "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=6",
           "-vf", "noise=alls=25:allf=t+u", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-shortest", str(src))  # fmt: skip
        info = probe(src)
        duration = float(info["format"]["duration"])
        print(f"source: {int(info['format']['size']) / MIB:.2f} MiB, {duration:.1f}s")

        # 1. The formula, by hand: 1 MiB over 6 s.
        b = plan(1.0, duration, True, 640, 360, 30)
        total_bits = b.video_bps + b.audio_bps
        print(f"1. budget for 1 MiB: video {b.video_bps // 1000} kb/s + audio {b.audio_bps // 1000} kb/s "
              f"= {total_bits * duration / 8 / MIB:.3f} MiB expected (aim: 0.95)")
        assert abs(total_bits * duration / 8 / MIB - 0.95) < 0.01

        # 2. Two passes land under the target.
        out = d / "out.mp4"
        two_pass(src, out, b)
        mib = out.stat().st_size / MIB
        print(f"2. two-pass + VBV cap: {mib:.3f} MiB")
        assert 0.6 < mib <= 1.0, mib
        assert abs(float(probe(out)["format"]["duration"]) - duration) < 0.3
        assert not list(d.glob("pass-*")), "temporary pass logs must be cleaned up"

        # 3. For comparison: the same bitrate WITHOUT the cap (informational: it can overshoot).
        out2 = d / "uncapped.mp4"
        two_pass(src, out2, b, capped=False)
        print(f"3. two-pass, no cap  : {out2.stat().st_size / MIB:.3f} MiB   <- this is why the cap exists")

        # 4. And CRF: quality-constant, size is whatever it turns out to be.
        crf = d / "crf.mp4"
        ff("-i", str(src), "-c:v", "libx264", "-crf", "23", "-preset", "medium", str(crf))
        print(f"4. CRF 23            : {crf.stat().st_size / MIB:.3f} MiB   <- no way to ask for 1.0")

        # 5. A tiny target shrinks the picture instead of smearing it.
        tiny = plan(0.3, duration, True, 640, 360, 30)
        assert tiny.height < 360
        out3 = d / "tiny.mp4"
        two_pass(src, out3, tiny)
        v = next(s for s in probe(out3)["streams"] if s["codec_type"] == "video")
        assert v["height"] == tiny.height and out3.stat().st_size <= 0.3 * MIB
        print(f"5. 0.3 MiB target -> {v['width']}x{v['height']}, {out3.stat().st_size / MIB:.3f} MiB")

        # 6. An impossible target is an error with a number in it, not a silent miss.
        try:
            plan(0.01, 3600, True, 1920, 1080, 30)
        except ValueError as e:
            print("6.", e)
        else:
            raise AssertionError("expected ValueError")
    print("module 04 OK")


if __name__ == "__main__":
    main()
