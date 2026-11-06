"""Module 07: testing a media server with real media.

Run:  python main.py

This tests the server built in Module 06 (it launches ../06-the-mcp-wrapper/main.py --serve).
No mocks and no checked-in video files: ffmpeg's `lavfi` virtual devices generate the inputs,
the server does real work on them, and ffprobe measures the results.

The checks are plain functions so the file has no dependency beyond `mcp`; the real project
(mediakit-mcp) uses the same ideas under pytest.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import anyio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

HERE = Path(__file__).resolve().parent
SERVER = HERE.parent / "06-the-mcp-wrapper" / "main.py"
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"
MIB = 1024 * 1024

# ---------------------------------------------------------------------------
# 1. Fixtures from thin air
# ---------------------------------------------------------------------------


def ff(*args: str) -> None:
    subprocess.run([FFMPEG, "-v", "error", "-y", *args], check=True, stdin=subprocess.DEVNULL)


def make_fixtures(d: Path) -> None:
    # Noisy so the file is several MB: compressing a clean test card proves nothing.
    ff("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=6",
       "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=6",
       "-vf", "noise=alls=25:allf=t+u", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p",
       "-c:a", "aac", "-shortest", str(d / "video.mp4"))  # fmt: skip
    ff("-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25:duration=3",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", str(d / "silent.mp4"))  # fmt: skip
    (d / "corrupt.mp4").write_bytes(b"this is not an mp4" * 100)
    (d / "truncated.mp4").write_bytes((d / "video.mp4").read_bytes()[:3000])
    assert (d / "video.mp4").stat().st_size > 2 * MIB, "fixture should be big enough to matter"


# ---------------------------------------------------------------------------
# 2. Measuring with ffprobe: assertions that explain themselves
# ---------------------------------------------------------------------------


def probe(path: Path, frames: bool = False) -> dict[str, Any]:
    cmd = [FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams"]
    if frames:
        cmd.append("-count_frames")  # decodes everything: only when you need exact frame counts
    out = subprocess.run([*cmd, str(path)], capture_output=True, text=True, check=True)
    data: dict[str, Any] = json.loads(out.stdout)
    return data


def stream(info: dict[str, Any], kind: str) -> dict[str, Any]:
    return next(s for s in info["streams"] if s["codec_type"] == kind)


def assert_duration(path: Path, expected: float, tol: float = 0.3) -> None:
    """Durations never match exactly: audio frames, keyframes and container rounding all add a
    little. Pick a tolerance that is tight enough to catch a real bug (a lost second), not zero."""
    got = float(probe(path)["format"]["duration"])
    assert abs(got - expected) <= tol, f"{path.name}: duration {got:.2f}s, expected {expected}s +/- {tol}"


def assert_size_at_most(path: Path, limit_bytes: float) -> None:
    size = path.stat().st_size
    assert size <= limit_bytes, f"{path.name}: {size} bytes exceeds the limit of {int(limit_bytes)}"


# ---------------------------------------------------------------------------
# 3. A tiny harness around an MCP client
# ---------------------------------------------------------------------------


class Client:
    def __init__(self, session: ClientSession) -> None:
        self.s = session

    async def call(self, tool: str, **args: Any) -> tuple[bool, str]:
        res = await self.s.call_tool(tool, args)
        return bool(res.is_error), res.content[0].text  # type: ignore[attr-defined]


Check = Callable[[Client, Path], Awaitable[None]]
CHECKS: list[Check] = []


def check(fn: Check) -> Check:
    CHECKS.append(fn)
    return fn


# ---------------------------------------------------------------------------
# 4. The checks: happy paths, then every error path
# ---------------------------------------------------------------------------


@check
async def compress_hits_the_size_and_keeps_the_duration(c: Client, d: Path) -> None:
    err, text = await c.call("compress", input=str(d / "video.mp4"), target_mb=1.5)
    assert not err, text
    out = d / "video.compressed.mp4"
    assert_size_at_most(out, 1.5 * MIB)
    assert out.stat().st_size > 0.5 * 1.5 * MIB, "should use most of the budget"
    assert_duration(out, 6.0)
    info = probe(out)
    assert stream(info, "video")["codec_name"] == "h264" and stream(info, "audio")["codec_name"] == "aac"


@check
async def trim_is_frame_exact(c: Client, d: Path) -> None:
    err, text = await c.call("trim", input=str(d / "video.mp4"), start=1.5, duration=2.0)
    assert not err, text
    assert_duration(d / "video.trimmed.mp4", 2.0, tol=0.1)


@check
async def gif_has_the_right_frame_count_and_width(c: Client, d: Path) -> None:
    err, text = await c.call("make_gif", input=str(d / "video.mp4"), start=1, duration=2, fps=10, width=320)
    assert not err, text
    info = probe(d / "video.gif", frames=True)
    v = stream(info, "video")
    assert v["codec_name"] == "gif" and v["width"] == 320
    assert abs(int(v["nb_read_frames"]) - 20) <= 2, v["nb_read_frames"]  # 2 s x 10 fps


@check
async def silent_input_stays_silent(c: Client, d: Path) -> None:
    err, text = await c.call("compress", input=str(d / "silent.mp4"), target_mb=0.2)
    assert not err, text
    kinds = [s["codec_type"] for s in probe(d / "silent.compressed.mp4")["streams"]]
    assert kinds == ["video"], kinds


@check
async def dry_run_writes_nothing_and_shows_the_command(c: Client, d: Path) -> None:
    before = sorted(p.name for p in d.iterdir())
    err, text = await c.call("trim", input=str(d / "video.mp4"), start=0, duration=1, output=str(d / "dry.mp4"), dry_run=True)
    assert not err and "-ss 0.000" in text and "-t 1.000" in text, text
    assert sorted(p.name for p in d.iterdir()) == before


@check
async def existing_output_is_refused_then_allowed(c: Client, d: Path) -> None:
    args = dict(input=str(d / "video.mp4"), start=0, duration=1, output=str(d / "once.mp4"))
    assert not (await c.call("trim", **args))[0]
    first = (d / "once.mp4").read_bytes()
    err, text = await c.call("trim", **args)
    assert err and "overwrite=true" in text and (d / "once.mp4").read_bytes() == first
    assert not (await c.call("trim", **args, overwrite=True))[0]


@check
async def missing_corrupt_and_truncated_inputs_have_readable_errors(c: Client, d: Path) -> None:
    err, text = await c.call("media_info", input=str(d / "nope.mp4"))
    assert err and "not found" in text, text
    for name in ("corrupt.mp4", "truncated.mp4"):
        err, text = await c.call("media_info", input=str(d / name))
        assert err and "ffprobe could not read" in text, (name, text)
        err, text = await c.call("compress", input=str(d / name), target_mb=1)
        assert err and "ffprobe could not read" in text, (name, text)


@check
async def impossible_requests_explain_themselves(c: Client, d: Path) -> None:
    err, text = await c.call("compress", input=str(d / "video.mp4"), target_mb=0.001, output=str(d / "n.mp4"))
    assert err and "too small" in text, text
    err, text = await c.call("trim", input=str(d / "video.mp4"), start=100, duration=1)
    assert err and "outside the media" in text, text
    err, text = await c.call("make_gif", input=str(d / "video.mp4"), fps=99)
    assert err and "limits" in text, text


@check
async def no_leftovers(c: Client, d: Path) -> None:
    assert not list(d.glob("*.partial.*")), "partial files left behind"
    assert not list(d.glob("*.log")) and not list(d.glob("*.mbtree"))


# ---------------------------------------------------------------------------
# 5. Can these tests fail? (a test that can't fail isn't a test)
# ---------------------------------------------------------------------------


def prove_the_assertions_can_fail(d: Path) -> None:
    try:
        assert_size_at_most(d / "video.mp4", 1 * MIB)  # the 20 MB source is NOT under 1 MiB
    except AssertionError as e:
        print("   size assertion fails on a too-big file, as it should:", str(e)[:60], "...")
    else:
        raise SystemExit("the size assertion cannot fail: the tests prove nothing")
    try:
        assert_duration(d / "video.mp4", 60.0)
    except AssertionError:
        print("   duration assertion fails on a wrong duration, as it should")
    else:
        raise SystemExit("the duration assertion cannot fail: the tests prove nothing")


async def run_all() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        make_fixtures(d)
        print("fixtures generated with lavfi:", ", ".join(sorted(p.name for p in d.iterdir())))
        prove_the_assertions_can_fail(d)

        params = StdioServerParameters(command=sys.executable, args=[str(SERVER), "--serve"])
        failures = 0
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            client = Client(session)
            for fn in CHECKS:
                t0 = time.monotonic()
                try:
                    await fn(client, d)
                except Exception:
                    failures += 1
                    print(f"FAIL {fn.__name__}\n{traceback.format_exc()}")
                else:
                    print(f"PASS {fn.__name__} ({time.monotonic() - t0:.1f}s)")
    return failures


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    bad = anyio.run(run_all)
    if bad:
        sys.exit(f"{bad} check(s) failed")
    print("module 07 OK")
