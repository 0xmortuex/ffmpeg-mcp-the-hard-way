"""Module 05: dry-run design.

Run:  python main.py

The rule: BUILD the command first, as data, and only then decide whether to run it.
If `dry_run` is just an `if` sprinkled through the code, the preview and the real run
drift apart. If both come from the same Plan object they cannot.

Also here: quoting a command for a human to paste, and writing outputs so that a
failure can never leave a half-written file or destroy an existing one.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
BASE_FLAGS = ["-hide_banner", "-nostdin", "-loglevel", "error", "-y"]


# ---------------------------------------------------------------------------
# Quoting for humans
# ---------------------------------------------------------------------------


def quote_arg(arg: str) -> str:
    """Make one argument safe to paste into a shell.

    POSIX: shlex.quote. Windows: cmd and PowerShell both honour double quotes, but
    subprocess.list2cmdline only quotes spaces. A filter graph like `split[a][b];[a]...`
    contains `;`, which PowerShell would read as "end of command", so we also quote
    anything outside a conservative safe set.
    """
    if sys.platform != "win32":
        import shlex

        return shlex.quote(arg)
    quoted = subprocess.list2cmdline([arg])
    safe = all(c.isalnum() or c in "_@%+=:,./\\-" for c in arg)
    if quoted == arg and not safe:
        return '"' + arg + '"'
    return quoted


def quote_command(argv: list[str]) -> str:
    return " ".join(quote_arg(a) for a in argv)


# ---------------------------------------------------------------------------
# A Plan is the command, as data
# ---------------------------------------------------------------------------


@dataclass
class Plan:
    argv: list[str]
    final: Path                      # where the user will find the result
    partial: Path                    # where ffmpeg actually writes
    overwrite: bool
    notes: list[str] = field(default_factory=list)
    finalize: Callable[[], None] | None = None


def partial_of(final: Path) -> Path:
    return final.with_name(f"{final.stem}.partial{final.suffix}")  # keeps the extension: ffmpeg
    # picks the muxer from it, so `clip.mp4.part` would not work.


def plan_trim(src: Path, start: float, duration: float, output: Path | None, overwrite: bool) -> Plan:
    final = output or src.with_name(f"{src.stem}.trimmed{src.suffix}")  # derived name, next to input
    if final.exists() and not overwrite:  # decided at PLAN time: a dry run reports it too
        raise FileExistsError(f"{final} already exists. Pass overwrite=True to replace it.")
    part = partial_of(final)
    argv = [FFMPEG, *BASE_FLAGS, "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{duration:.3f}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(part)]  # fmt: skip
    return Plan(argv, final, part, overwrite)


def dry_run(plan: Plan) -> str:
    return "\n".join([
        "DRY RUN: nothing was executed. This is what would run:",
        "  " + quote_command(plan.argv),
        f"Result would be written to: {plan.final}",
        "(written to a '.partial' name first, renamed on success)",
    ])  # fmt: skip


def execute(plan: Plan) -> Path:
    """Run the plan. ffmpeg writes to the partial file; only success moves it into place."""
    try:
        subprocess.run(plan.argv, check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if not plan.overwrite and plan.final.exists():  # someone created it while we worked
            raise FileExistsError(f"{plan.final} appeared during the run; not overwriting")
        os.replace(plan.partial, plan.final)  # atomic on the same volume
    except subprocess.CalledProcessError as e:
        raise RuntimeError("ffmpeg failed:\n" + e.stderr.strip()[-300:]) from e
    finally:
        if plan.partial.exists():
            plan.partial.unlink()  # a failed or refused run leaves nothing behind
    return plan.final


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "my clips; with [odd] names"   # spaces, semicolon, brackets: on purpose
        d.mkdir()
        src = d / "src clip.mp4"
        subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=25:duration=4",
                        "-f", "lavfi", "-i", "sine=duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-shortest", str(src)], check=True)  # fmt: skip

        # 1. A dry run prints the command and touches nothing.
        before = sorted(p.name for p in d.iterdir())
        plan = plan_trim(src, 1.0, 2.0, None, overwrite=False)
        text = dry_run(plan)
        print(text)
        assert sorted(p.name for p in d.iterdir()) == before
        assert "src clip.trimmed.partial.mp4" in text

        # 2. The preview IS the command: run the printed text through a real shell.
        if sys.platform == "win32":
            shell = ["powershell", "-NoProfile", "-Command", "& " + quote_command(plan.argv)]
        else:
            shell = ["sh", "-c", quote_command(plan.argv)]
        r = subprocess.run(shell, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert plan.partial.exists() and not plan.final.exists()
        plan.partial.unlink()
        print("2. the printed command line works when pasted into a real shell, odd path and all")

        # 3. Execute for real.
        final = execute(plan)
        assert final.exists() and not plan.partial.exists()
        first = final.read_bytes()

        # 4. Never overwrite by default.
        try:
            plan_trim(src, 1.0, 1.0, None, overwrite=False)
        except FileExistsError as e:
            assert "overwrite" in str(e)
        else:
            raise AssertionError("must refuse")
        assert final.read_bytes() == first
        execute(plan_trim(src, 0.0, 1.0, None, overwrite=True))
        assert final.read_bytes() != first
        print("4. refused without overwrite; replaced with it")

        # 5. A failed run neither leaves a partial file nor harms an existing output.
        keep = final.read_bytes()
        bad = Plan([FFMPEG, *BASE_FLAGS, "-i", str(d / "nope.mp4"), str(partial_of(final))],
                   final, partial_of(final), overwrite=True)  # fmt: skip
        try:
            execute(bad)
        except RuntimeError as e:
            assert "nope.mp4" in str(e)
        else:
            raise AssertionError("expected failure")
        assert final.read_bytes() == keep and not partial_of(final).exists()
        print("5. failed overwrite: original intact, no .partial left")
    print("module 05 OK")


if __name__ == "__main__":
    main()
