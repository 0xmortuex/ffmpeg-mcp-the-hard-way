"""Module 03: progress from `-progress pipe:1`.

Run:  python main.py

ffmpeg's normal progress line (`frame=  42 fps= 25 ... time=00:00:01.68`) is for humans
and is rewritten in place with carriage returns. `-progress pipe:1` instead prints
clean `key=value` blocks to stdout, ending each block with `progress=continue|end`.
That is the machine-readable channel.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"

# What one block looks like (captured from a real run, trimmed):
SAMPLE_BLOCK = """\
frame=50
fps=25.00
stream_0_0_q=-1.0
bitrate=  64.2kbits/s
total_size=12345
out_time_us=2000000
out_time_ms=2000000
out_time=00:00:02.000000
dup_frames=0
drop_frames=0
speed=1.01x
progress=continue
"""


def parse_blocks(text: str) -> list[dict[str, str]]:
    """Split a progress stream into one dict per block (a block ends at `progress=`)."""
    blocks: list[dict[str, str]] = []
    cur: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.strip().partition("=")
        if not sep:
            continue
        cur[key] = value.strip()
        if key == "progress":
            blocks.append(cur)
            cur = {}
    return blocks


def out_seconds(block: dict[str, str]) -> float | None:
    """Seconds of OUTPUT produced so far.

    Two traps: `out_time_ms` is MICROseconds (a long-standing misnomer; use out_time_us),
    and at the very start both can be the string "N/A", which is not an integer.
    """
    raw = block.get("out_time_us", "")
    if not raw.lstrip("-").isdigit():
        return None
    return max(int(raw), 0) / 1_000_000


def fraction(block: dict[str, str], total_s: float) -> float | None:
    s = out_seconds(block)
    if s is None or total_s <= 0:
        return None
    return min(s / total_s, 1.0)  # never above 100% even if the encoder overshoots by a frame


def run_with_progress(
    argv: list[str],
    total_s: float,
    on_progress: Callable[[float], None],
    step: int = 0,
    steps: int = 1,
    min_interval_s: float = 0.5,
) -> None:
    """Run ffmpeg and report overall progress in 0..1 across `steps` consecutive runs."""
    proc = subprocess.Popen(
        argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )  # fmt: skip
    assert proc.stdout and proc.stderr
    err: list[str] = []
    threading.Thread(target=lambda: err.extend(proc.stderr or []), daemon=True).start()

    last = 0.0
    block: dict[str, str] = {}
    for line in proc.stdout:  # blocks until ffmpeg writes: no busy loop
        key, sep, value = line.strip().partition("=")
        if not sep:
            continue
        block[key] = value
        if key == "progress":  # a complete block
            frac = fraction(block, total_s)
            now = time.monotonic()
            if frac is not None and now - last >= min_interval_s:  # throttle: don't flood the client
                last = now
                on_progress((step + frac) / steps)
            block = {}
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed:\n" + "".join(err[-8:]))
    on_progress((step + 1) / steps)  # always finish on exactly this step's share


def realtime_encode(out: Path, seconds: int) -> list[str]:
    """`-re` reads the lavfi source at real-time speed, so a 3 s clip takes 3 s: we can watch it."""
    return [
        FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
        "-progress", "pipe:1", "-nostats",
        "-re", "-f", "lavfi", "-i", f"testsrc=size=160x120:rate=25:duration={seconds}",
        "-c:v", "libx264", "-preset", "ultrafast", str(out),
    ]  # fmt: skip


def main() -> None:
    # 1. Parsing, with no ffmpeg involved.
    blocks = parse_blocks(SAMPLE_BLOCK + SAMPLE_BLOCK.replace("2000000", "N/A").replace("continue", "end"))
    assert len(blocks) == 2 and blocks[0]["progress"] == "continue" and blocks[1]["progress"] == "end"
    assert out_seconds(blocks[0]) == 2.0
    assert out_seconds(blocks[1]) is None  # "N/A" handled, not a crash
    assert fraction(blocks[0], 4.0) == 0.5
    assert fraction(blocks[0], 1.0) == 1.0  # clamped
    print("1. parser handles real blocks, N/A, and clamps to 100%")

    # 2. A live run: the fractions must rise and finish at exactly 1.0.
    seen: list[float] = []
    with tempfile.TemporaryDirectory() as tmp:
        t0 = time.monotonic()
        run_with_progress(realtime_encode(Path(tmp) / "a.mp4", 3), 3.0, seen.append)
        assert time.monotonic() - t0 > 2, "-re should make this take about 3 s"
        assert seen[-1] == 1.0 and seen == sorted(seen), seen
        assert any(0 < f < 1 for f in seen), "we should have seen intermediate progress"
        print(f"2. live run: {len(seen)} updates, e.g. {[round(f, 2) for f in seen[:4]]} ... {seen[-1]}")

        # 3. Two-pass jobs: step 0 of 2 covers 0..0.5, step 1 of 2 covers 0.5..1.0.
        seen2: list[float] = []
        for i in range(2):
            run_with_progress(realtime_encode(Path(tmp) / f"p{i}.mp4", 2), 2.0, seen2.append, step=i, steps=2)
        first_half = [f for f in seen2 if f <= 0.5]
        assert first_half and seen2[-1] == 1.0 and seen2 == sorted(seen2)
        print("3. two steps report one continuous 0..1 progress")

        # 4. A failing run surfaces ffmpeg's last stderr lines, not a stack trace from the parser.
        try:
            run_with_progress(
                [FFMPEG, "-nostdin", "-loglevel", "error", "-progress", "pipe:1", "-i",
                 str(Path(tmp) / "missing.mp4"), str(Path(tmp) / "x.mp4")], 1.0, seen.append)
        except RuntimeError as e:
            assert "missing.mp4" in str(e)
        else:
            raise AssertionError("expected failure")
    print("module 03 OK")


if __name__ == "__main__":
    main()
