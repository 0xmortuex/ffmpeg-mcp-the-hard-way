"""Module 06: the MCP wrapper. A small but complete media server, and a client that drives it.

Two modes in one file:

    python main.py --serve
        Run the MCP server on stdio. This is what Claude Code / Claude Desktop launch.

    python main.py
        Demo and self-test. Spawns `main.py --serve` as a subprocess and talks to it
        over stdio exactly as an agent's client would.

Modules 01-05 built the parts; this file bolts them to MCP. Four tools (media_info, compress,
trim, make_gif), each with dry_run and overwrite. The finished project (mediakit-mcp) has nine.
"""

from __future__ import annotations

import collections
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import anyio
import anyio.from_thread
import anyio.lowlevel
import anyio.to_thread
from mcp.server.mcpserver import Context, MCPServer

# In mcp >= 2 only a ToolError's message reaches the agent; any other exception shows up as
# a bare "Error executing tool X". So every error we MEAN to show derives from ToolError.
from mcp.server.mcpserver.exceptions import ToolError

MIB = 1024 * 1024
INSTALL_HINT = "Install ffmpeg (winget install Gyan.FFmpeg | brew install ffmpeg | apt install ffmpeg)."


class MediaError(ToolError):
    pass


# --------------------------------------------------------------------------- binaries, probing


def find_tool(name: str) -> str:
    found = os.environ.get(f"{name.upper()}_PATH") or shutil.which(name)
    if not found or not os.path.isfile(found):
        raise MediaError(f"`{name}` not found. {INSTALL_HINT}")
    return found


def probe(path: Path) -> dict[str, Any]:
    out = subprocess.run(
        [find_tool("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60,
    )  # fmt: skip
    if out.returncode != 0:
        raise MediaError(f"ffprobe could not read {path.name!r}: corrupt or not media.\n  {out.stderr.strip()[-200:]}")
    data: dict[str, Any] = json.loads(out.stdout)
    return data


def first(info: dict[str, Any], kind: str) -> dict[str, Any] | None:
    return next((s for s in info["streams"] if s["codec_type"] == kind), None)


# --------------------------------------------------------------------------- the runner (Modules 02-03)


def run_steps(
    steps: list[list[str]], timeout_s: float, cancel: threading.Event,
    on_progress: Callable[[float], None], total_s: float,
) -> None:  # fmt: skip
    deadline = time.monotonic() + timeout_s
    for i, argv in enumerate(steps):
        flags = (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW) if sys.platform == "win32" else 0
        proc = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", creationflags=flags,
            start_new_session=sys.platform != "win32",
        )  # fmt: skip
        assert proc.stdout and proc.stderr
        tail: collections.deque[str] = collections.deque(maxlen=20)
        last = [0.0]

        def read_progress(i: int = i) -> None:
            for line in proc.stdout or []:
                k, _, v = line.strip().partition("=")
                if k == "out_time_us" and v.isdigit() and time.monotonic() - last[0] > 0.5:
                    last[0] = time.monotonic()
                    on_progress((i + min(int(v) / 1e6 / total_s, 1.0)) / len(steps))

        threads = [
            threading.Thread(target=read_progress, daemon=True),
            threading.Thread(target=lambda: [tail.append(x[-300:]) for x in proc.stderr or []], daemon=True),
        ]
        for t in threads:
            t.start()
        try:
            while True:
                try:
                    proc.wait(timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    if cancel.is_set():
                        raise MediaError("cancelled") from None
                    if time.monotonic() > deadline:
                        raise MediaError(f"ffmpeg did not finish within {timeout_s:g}s; stopped") from None
        except BaseException:
            kill_tree(proc)
            raise
        finally:
            for t in threads:
                t.join(timeout=5)
        if proc.returncode != 0:
            raise MediaError("ffmpeg failed:\n" + "".join(tail).strip()[-400:])
    on_progress(1.0)


def kill_tree(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is None:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=10)


# --------------------------------------------------------------------------- plans (Modules 04-05)


def ffmpeg(*args: str) -> list[str]:
    return [find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error", "-nostats",
            "-progress", "pipe:1", "-y", *args]  # fmt: skip


class Plan:
    def __init__(self, steps: list[list[str]], final: Path, partial: Path, total_s: float, overwrite: bool,
                 notes: list[str], target_mb: float | None = None, cleanup: list[str] | None = None) -> None:  # fmt: skip
        self.steps, self.final, self.partial = steps, final, partial
        self.total_s, self.overwrite, self.notes = total_s, overwrite, notes
        self.target_mb, self.cleanup = target_mb, cleanup or []


def out_path(src: Path, output: str | None, tag: str, ext: str, overwrite: bool) -> Path:
    default = src.with_suffix(ext) if not tag else src.with_name(f"{src.stem}.{tag}{ext}")
    final = Path(output).resolve() if output else default
    if final == src:
        raise MediaError("output is the same file as the input")
    if final.exists() and not overwrite:
        raise MediaError(f"output {final} already exists. Pass overwrite=true to replace it.")
    return final


def resolve(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise MediaError(f"input file not found: {p}")
    return p


def plan_compress(path: str, target_mb: float, output: str | None, overwrite: bool) -> Plan:
    src = resolve(path)
    info = probe(src)
    v = first(info, "video")
    if v is None:
        raise MediaError(f"{src.name!r} has no video stream")
    duration = float(info["format"]["duration"])
    total_bps = target_mb * MIB * 8 * 0.95 / duration
    audio = 64_000 if first(info, "audio") else 0
    video = int(total_bps - audio)
    if video < 60_000:
        raise MediaError(f"{target_mb:g} MB is too small for {duration:.0f}s of video. Trim it or raise the target.")
    final = out_path(src, output, "compressed", ".mp4", overwrite)
    part = final.with_name(f"{final.stem}.partial{final.suffix}")
    log = str(Path(tempfile.gettempdir()) / f"mini-{os.getpid()}-{time.monotonic_ns()}")
    enc = ["-c:v", "libx264", "-b:v", str(video), "-maxrate", str(video), "-bufsize", str(video * 2),
           "-pix_fmt", "yuv420p", "-passlogfile", log]  # fmt: skip
    steps = [
        ffmpeg("-i", str(src), "-map", "0:v:0", *enc, "-pass", "1", "-an", "-f", "null", "-"),
        ffmpeg("-i", str(src), "-map", "0:v:0", "-map", "0:a:0?", *enc, "-pass", "2",
               *(["-c:a", "aac", "-b:a", str(audio)] if audio else ["-an"]), str(part)),  # fmt: skip
    ]
    return Plan(steps, final, part, duration, overwrite, [f"two-pass: video {video // 1000} kb/s"], target_mb, [log + "*"])


def plan_trim(path: str, start: float, duration: float, output: str | None, overwrite: bool) -> Plan:
    src = resolve(path)
    total = float(probe(src)["format"]["duration"])
    if not 0 <= start < total:
        raise MediaError(f"start={start:g}s is outside the media (0 to {total:.2f}s)")
    if duration <= 0 or start + duration > total + 0.05:
        raise MediaError(f"start + duration runs past the end of the media ({total:.2f}s)")
    final = out_path(src, output, "trimmed", src.suffix, overwrite)
    part = final.with_name(f"{final.stem}.partial{final.suffix}")
    argv = ffmpeg("-ss", f"{start:.3f}", "-i", str(src), "-t", f"{duration:.3f}",
                  "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(part))  # fmt: skip
    return Plan([argv], final, part, duration, overwrite, ["re-encoded, so the cut is frame-exact"])


def plan_gif(path: str, start: float, duration: float, fps: int, width: int, output: str | None, overwrite: bool) -> Plan:  # fmt: skip
    src = resolve(path)
    info = probe(src)
    v = first(info, "video")
    if v is None:
        raise MediaError(f"{src.name!r} has no video stream")
    if not (1 <= fps <= 30 and 16 <= width <= 1280 and 0 < duration <= 30):
        raise MediaError("limits: fps 1-30, width 16-1280, duration 0-30 s")
    final = out_path(src, output, "", ".gif", overwrite)
    part = final.with_name(f"{final.stem}.partial{final.suffix}")
    graph = (f"fps={fps},scale={min(width, v['width'])}:-1:flags=lanczos,split[a][b];"
             "[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5")  # fmt: skip
    argv = ffmpeg("-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(src), "-an", "-vf", graph, str(part))
    return Plan([argv], final, part, duration, overwrite, [])


def quote(argv: list[str]) -> str:
    import shlex

    if sys.platform != "win32":
        return shlex.join(argv)
    return " ".join(f'"{a}"' if not all(c.isalnum() or c in "_@%+=:,./\\-" for c in a) else a for a in argv)


def execute(plan: Plan, timeout_s: float, cancel: threading.Event, on_progress: Callable[[float], None]) -> str:
    t0 = time.monotonic()
    try:
        run_steps(plan.steps, timeout_s, cancel, on_progress, plan.total_s)
        if not plan.overwrite and plan.final.exists():
            raise MediaError(f"{plan.final} appeared during the run; not overwriting it")
        os.replace(plan.partial, plan.final)
    finally:
        if plan.partial.exists():
            plan.partial.unlink()
        import glob

        for pattern in plan.cleanup:
            for f in glob.glob(pattern):
                os.unlink(f)
    size = plan.final.stat().st_size
    lines = [f"Wrote {plan.final}", f"  size: {size / MIB:.2f} MB, took {time.monotonic() - t0:.1f}s"]
    if plan.target_mb is not None:
        ok = size <= plan.target_mb * MIB
        lines.append(f"  target {plan.target_mb:g} MB: " + ("met" if ok else "MISSED, try a smaller target"))
    return "\n".join(lines + [f"  note: {n}" for n in plan.notes])


# --------------------------------------------------------------------------- the MCP server

mcp = MCPServer(
    "mini-mediakit",
    instructions=(
        "Small media toolbox on ffmpeg: media_info first, then compress (to N MB), trim, or make_gif. "
        "Every job tool takes dry_run=true to show the ffmpeg command without running it, and never "
        "overwrites an existing file unless overwrite=true."
    ),
)


async def run_plan(build: Callable[[], Plan], dry_run: bool, timeout_s: int, ctx: Context[Any, Any]) -> str:
    plan = await anyio.to_thread.run_sync(build)  # planning runs ffprobe: keep it off the event loop
    if dry_run:
        return "DRY RUN: nothing executed.\n" + "\n".join(f"  {quote(s)}" for s in plan.steps)
    cancel = threading.Event()
    token = anyio.lowlevel.current_token()  # progress comes from a plain thread: give it the loop

    def progress(frac: float) -> None:
        anyio.from_thread.run(ctx.report_progress, frac * 100, 100.0, "encoding", token=token)

    try:
        # abandon_on_cancel: return to the client at once; the worker sees `cancel`, kills ffmpeg.
        return await anyio.to_thread.run_sync(
            lambda: execute(plan, timeout_s, cancel, progress), abandon_on_cancel=True
        )
    except anyio.get_cancelled_exc_class():
        cancel.set()
        raise


@mcp.tool()
async def media_info(input: str) -> str:
    """Summarize a media file with ffprobe: duration, size, and each stream's codec and size."""

    def job() -> str:
        src = resolve(input)
        info = probe(src)
        fmt = info["format"]
        lines = [f"{src}", f"  {float(fmt['duration']):.2f}s, {int(fmt['size']) / MIB:.2f} MB, {fmt['format_name']}"]
        for s in info["streams"]:
            size = f" {s['width']}x{s['height']}" if s["codec_type"] == "video" else f" {s.get('sample_rate')} Hz"
            lines.append(f"  {s['codec_type']}: {s['codec_name']}{size}")
        return "\n".join(lines)

    return await anyio.to_thread.run_sync(job)


@mcp.tool()
async def compress(input: str, target_mb: float, ctx: Context[Any, Any], output: str | None = None,
                   overwrite: bool = False, dry_run: bool = False, timeout_s: int = 900) -> str:  # fmt: skip
    """Re-encode a video to roughly target_mb megabytes (two-pass H.264, 5% safety margin).

    Errors if the target is too small for the video's length. Output: name.compressed.mp4 next to
    the input unless output is given. overwrite replaces an existing file; dry_run prints the commands.
    """
    return await run_plan(lambda: plan_compress(input, target_mb, output, overwrite), dry_run, timeout_s, ctx)


@mcp.tool()
async def trim(input: str, start: float, duration: float, ctx: Context[Any, Any], output: str | None = None,
               overwrite: bool = False, dry_run: bool = False, timeout_s: int = 900) -> str:  # fmt: skip
    """Cut `duration` seconds starting at `start` seconds (frame-exact, re-encoded). Output: name.trimmed.ext."""
    return await run_plan(lambda: plan_trim(input, start, duration, output, overwrite), dry_run, timeout_s, ctx)


@mcp.tool()
async def make_gif(input: str, ctx: Context[Any, Any], start: float = 0.0, duration: float = 5.0, fps: int = 12,
                   width: int = 480, output: str | None = None, overwrite: bool = False,
                   dry_run: bool = False, timeout_s: int = 900) -> str:  # fmt: skip
    """Make an animated GIF with a proper palette. fps 1-30, width 16-1280, duration up to 30 s."""
    return await run_plan(lambda: plan_gif(input, start, duration, fps, width, output, overwrite), dry_run, timeout_s, ctx)


# --------------------------------------------------------------------------- demo / self-test


def ffmpeg_pids_mentioning(fragment: str) -> list[int]:
    if sys.platform == "win32":
        cmd = ("Get-CimInstance Win32_Process -Filter \"Name='ffmpeg.exe'\" | "
               f"Where-Object {{ $_.CommandLine -like '*{fragment}*' }} | ForEach-Object {{ $_.ProcessId }}")  # fmt: skip
        out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True)
    else:
        out = subprocess.run(["pgrep", "-f", fragment], capture_output=True, text=True)
    return [int(x) for x in out.stdout.split()]


async def demo() -> None:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        subprocess.run(
            [find_tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=854x480:rate=30:duration=20",
             "-f", "lavfi", "-i", "sine=duration=20", "-vf", "noise=alls=25:allf=t+u", "-c:v", "libx264",
             "-crf", "14", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(d / "demo.mp4")], check=True)  # fmt: skip
        src = str(d / "demo.mp4")

        params = StdioServerParameters(command=sys.executable, args=[os.path.abspath(__file__), "--serve"])
        async with stdio_client(params) as (read, write), ClientSession(read, write) as s:
            await s.initialize()
            names = {t.name for t in (await s.list_tools()).tools}
            assert names == {"media_info", "compress", "trim", "make_gif"}, names

            async def call(tool: str, **args: Any) -> tuple[bool, str]:
                res = await s.call_tool(tool, args)
                return bool(res.is_error), res.content[0].text  # type: ignore[attr-defined]

            err, text = await call("media_info", input=src)
            assert not err and "h264" in text and "20.0" in text, text
            print(text)

            err, text = await call("compress", input=src, target_mb=2, dry_run=True)
            assert not err and text.startswith("DRY RUN") and "-pass 2" in text
            assert not (d / "demo.compressed.mp4").exists()
            print("dry run OK, nothing written")

            updates: list[float] = []

            async def on_progress(p: float, total: float | None, msg: str | None) -> None:
                updates.append(p)

            res = await s.call_tool("compress", {"input": src, "target_mb": 2}, progress_callback=on_progress)
            text = res.content[0].text  # type: ignore[attr-defined]
            assert not res.is_error and "target 2 MB: met" in text, text
            assert (d / "demo.compressed.mp4").stat().st_size <= 2 * MIB
            assert len(updates) >= 3, f"expected mid-job progress, got {updates}"  # not just the final 100
            assert updates[-1] == 100.0 and updates == sorted(updates), updates
            print(text, f"\n  ({len(updates)} progress notifications)")

            # Errors are instructions.
            err, text = await call("compress", input=src, target_mb=2)
            assert err and "overwrite=true" in text, text
            err, text = await call("compress", input=src, target_mb=0.001, output=str(d / "x.mp4"))
            assert err and "too small" in text, text
            err, text = await call("media_info", input=str(d / "missing.mp4"))
            assert err and "not found" in text, text
            (d / "bad.mp4").write_bytes(b"junk" * 100)
            err, text = await call("media_info", input=str(d / "bad.mp4"))
            assert err and "corrupt" in text, text
            err, text = await call("make_gif", input=src, duration=2, fps=10)
            assert not err and (d / "demo.gif").exists(), text
            print("error messages reach the agent intact")

            # Cancel mid-job: ffmpeg must die and leave nothing behind.
            marker = d.name
            with anyio.move_on_after(2.0):
                await s.call_tool("compress", {"input": src, "target_mb": 3, "output": str(d / "slow.mp4")})
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and ffmpeg_pids_mentioning(marker):
                await anyio.sleep(0.3)
            assert not ffmpeg_pids_mentioning(marker), "ffmpeg survived the cancel"
            await anyio.sleep(0.5)
            assert not list(d.glob("*.partial.*")) and not (d / "slow.mp4").exists()
            err, text = await call("media_info", input=src)
            assert not err, "server must still be healthy after a cancel"
            print("cancel killed ffmpeg and cleaned up; the server is still serving")
    print("module 06 OK")


if __name__ == "__main__":
    if "--serve" in sys.argv:
        mcp.run()
    else:
        anyio.run(demo)
