"""Run every module's main.py against real ffmpeg, the way CI does.

Each main.py checks its own results with assert, so a chapter whose code drifts out of
sync with what its README claims (or with ffmpeg itself) fails here.

Usage: python verify.py            # all modules
       python verify.py 03 04      # just these
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))


def modules() -> list[str]:
    return sorted(d for d in os.listdir(ROOT) if d[:2].isdigit() and os.path.isdir(os.path.join(ROOT, d)))


def main() -> int:
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            sys.exit(f"{tool} not found on PATH - install ffmpeg first (see README)")
    wanted = sys.argv[1:]
    todo = [m for m in modules() if not wanted or m[:2] in wanted]
    if not todo:
        sys.exit(f"no module matches {wanted}")
    failed: list[str] = []
    for m in todo:
        t0 = time.monotonic()
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, m, "main.py")],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, timeout=600,
        )  # fmt: skip
        ok = proc.returncode == 0
        print(f"{'PASS' if ok else 'FAIL'}  {m}  ({time.monotonic() - t0:.1f}s)")
        if not ok:
            failed.append(m)
            print((proc.stdout + proc.stderr)[-3000:])
    if failed:
        print(f"\n{len(failed)} module(s) failed: {', '.join(failed)}")
        return 1
    print(f"\nall {len(todo)} modules verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
