"""Module 02: running a process safely.

Run:  python main.py

Four things go wrong when you launch ffmpeg from a server, and this file shows
each one failing and then the fix:

  1. a shell turns a file name into commands          -> pass an argument list
  2. a full stderr pipe freezes the child             -> drain pipes on threads
  3. a stuck job never returns                        -> poll a deadline
  4. killing the parent leaves grandchildren running  -> kill the process tree
"""

from __future__ import annotations

import collections
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import IO, Any

# ---------------------------------------------------------------------------
# 1. Shell injection
# ---------------------------------------------------------------------------


def shell_injection_demo(tmp: Path) -> None:
    """File names come from an agent, which got them from a web page, an email, a zip...

    A file called `a.mp4 & echo pwned > marker` is a perfectly legal name on every OS.
    """
    sep = "&" if sys.platform == "win32" else ";"
    marker = tmp / "marker.txt"
    evil = f"a.mp4 {sep} echo pwned > {marker}"

    # WRONG: build one string, let a shell parse it.
    subprocess.run(f"{sys.executable} -c pass {evil}", shell=True, capture_output=True)
    assert marker.exists(), "the shell ran our 'file name' as a command"
    marker.unlink()

    # RIGHT: an argument list. There is no shell, so there is nothing to inject into.
    # The whole string arrives as ONE argv entry, spaces and ampersands included.
    out = subprocess.run(
        [sys.executable, "-c", "import sys; print(sys.argv[1])", evil],
        capture_output=True, text=True,
    )  # fmt: skip
    assert out.stdout.strip() == evil
    assert not marker.exists()
    print("1. argument lists: the hostile file name stayed one harmless argument")


# ---------------------------------------------------------------------------
# 2. The pipe that fills up
# ---------------------------------------------------------------------------

CHATTY = "import sys; sys.stderr.write('x' * 1_000_000); sys.stderr.flush()"


def pipe_deadlock_demo() -> None:
    # WRONG: pipe stderr but only look at it after the child exits. A pipe holds ~64 KB;
    # the child blocks on write, we block on wait. Neither moves.
    p = subprocess.Popen([sys.executable, "-c", CHATTY], stderr=subprocess.PIPE)
    try:
        p.wait(timeout=2)
    except subprocess.TimeoutExpired:
        print("2. wait() hung: the child is stuck writing to a full stderr pipe")
    else:
        raise AssertionError("expected a deadlock")
    finally:
        p.kill()
        p.wait()


class Drain(threading.Thread):
    """Read a pipe line by line on its own thread so the child never blocks."""

    def __init__(self, stream: IO[str], handle: Callable[[str], None]) -> None:
        super().__init__(daemon=True)
        self.stream, self.handle = stream, handle

    def run(self) -> None:
        for line in self.stream:
            self.handle(line)


# ---------------------------------------------------------------------------
# 3 + 4. A runner with a deadline and a tree kill
# ---------------------------------------------------------------------------


class JobError(Exception):
    pass


def kill_tree(proc: subprocess.Popen[str]) -> None:
    """Kill the process AND whatever it started. ffmpeg can spawn helpers; shells always do."""
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        # /T = the whole tree, /F = force. proc.kill() would only end the top process.
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        os.killpg(proc.pid, signal.SIGKILL)  # needs start_new_session=True at launch
    proc.wait(timeout=10)


def run(argv: list[str], timeout_s: float, on_spawn: Callable[[int], None] | None = None) -> str:
    """Run argv, return the tail of stderr. Raises JobError on failure or timeout."""
    popen_kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        popen_kwargs["start_new_session"] = True  # own process group, so killpg works
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,  # a child that reads stdin would otherwise wait for us forever
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",  # never crash on odd bytes
        **popen_kwargs,
    )  # fmt: skip
    assert proc.stdout and proc.stderr
    if on_spawn:
        on_spawn(proc.pid)
    tail: collections.deque[str] = collections.deque(maxlen=20)  # keep the end, not the novel
    readers = [Drain(proc.stdout, lambda _: None), Drain(proc.stderr, lambda ln: tail.append(ln[-300:]))]  # cap one line too
    for r in readers:
        r.start()
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            try:
                proc.wait(timeout=0.1)  # short waits so we can notice the deadline
                break
            except subprocess.TimeoutExpired:
                if time.monotonic() > deadline:
                    kill_tree(proc)
                    raise JobError(f"did not finish within {timeout_s:g}s and was stopped") from None
    except BaseException:
        kill_tree(proc)  # Ctrl-C, cancellation, anything: never leave it running
        raise
    finally:
        for r in readers:
            r.join(timeout=5)
    if proc.returncode != 0:
        raise JobError(f"exit code {proc.returncode}: " + "".join(tail).strip()[-200:])
    return "".join(tail)


def pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                             capture_output=True, text=True).stdout  # fmt: skip
        return f'"{pid}"' in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def wait_dead(pid: int, seconds: float = 10) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if not pid_alive(pid):
            return True
        time.sleep(0.1)
    return False


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        shell_injection_demo(d)
        pipe_deadlock_demo()

        # The drained version handles the same chatty child without a hitch.
        t0 = time.monotonic()
        tail = run([sys.executable, "-c", CHATTY], timeout_s=30)
        assert time.monotonic() - t0 < 10 and len(tail) < 2000
        print("2. drained pipes: 1 MB of stderr handled, kept only", len(tail), "bytes")

        # A failing child reports the end of its stderr.
        try:
            run([sys.executable, "-c", "import sys; sys.stderr.write('boom: bad input\\n'); sys.exit(3)"], 10)
        except JobError as e:
            assert "exit code 3" in str(e) and "boom: bad input" in str(e)
        else:
            raise AssertionError("expected JobError")

        # Deadline + tree kill. The child starts a grandchild, like a shell or a helper would.
        pidfile = d / "grandchild.pid"
        script = (
            "import subprocess, sys, time\n"
            "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])\n"
            "open(sys.argv[1], 'w').write(str(c.pid))\n"
            "time.sleep(300)\n"
        )
        pids: list[int] = []
        t0 = time.monotonic()
        try:
            run([sys.executable, "-c", script, str(pidfile)], timeout_s=3, on_spawn=pids.append)
        except JobError as e:
            assert "did not finish within 3s" in str(e)
        else:
            raise AssertionError("expected a timeout")
        assert time.monotonic() - t0 < 20
        grandchild = int(pidfile.read_text())
        assert wait_dead(pids[0]), "child survived"
        assert wait_dead(grandchild), "grandchild survived: that is the bug taskkill /T and killpg fix"
        print("3+4. deadline enforced; child AND grandchild are gone")
    print("module 02 OK")


if __name__ == "__main__":
    main()
