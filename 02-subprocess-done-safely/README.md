# Module 02: Subprocess done safely

## The concept

Your server will start ffmpeg on behalf of an AI agent whose inputs came from somewhere you do
not control. Four classic mistakes turn that into a security hole or a hang. Each is shown
failing in `main.py`, then fixed.

## 1. Don't use a shell

`subprocess.run(f"ffmpeg -i {path} out.mp4", shell=True)` hands the whole string to `cmd.exe` or
`sh`, which parses it. A file called `a.mp4 & echo pwned > marker` is a legal name on every
operating system; to the shell it is two commands. The demo uses a harmless `echo` and proves the
marker file appears.

The fix is the argument list: `subprocess.run(["ffmpeg", "-i", path, "out.mp4"])`. No shell is
involved, so the name stays one argv entry, spaces and ampersands included. There is nothing to
escape because nothing parses it.

Related: if a path begins with `-`, ffmpeg would read it as an option. The finished server
resolves every path to an absolute path first, so it begins with a drive letter or `/`.

## 2. Drain your pipes

`Popen(..., stderr=PIPE)` and then `proc.wait()` looks right and deadlocks. A pipe buffers about
64 KB. ffmpeg writes more than that, blocks until someone reads, and you block until it exits.
The demo has a child write 1 MB to stderr and shows `wait()` hanging.

The fix is a reader thread per pipe. Each thread reads line by line into a bounded `deque`, so
you keep the *tail* (all an error message needs) and memory stays flat. Cap the length of each
line too: the chatty child writes 1 MB with no newline, and a line-based buffer would keep the
whole megabyte as one "line".

## 3. Every wait has an end

Poll with `proc.wait(timeout=0.1)` in a loop and compare against a monotonic deadline. Short
polls also give you a place to notice a cancel request (Module 06). `time.monotonic()` rather
than `time.time()`: the wall clock can jump.

## 4. Kill the tree, not the parent

`proc.kill()` ends one process. If that process started others (a shell wrapper, a helper
process), they live on, holding CPU and file locks. The demo's child starts a grandchild and the
check is that *both* die.

- **POSIX:** launch with `start_new_session=True` so the child leads its own process group, and
  kill with `os.killpg(proc.pid, SIGKILL)`.
- **Windows:** `taskkill /F /T /PID <pid>`. `/T` is the tree. Launch with
  `CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW` so a GUI client (Claude Desktop) does not flash
  a console window at the user for every encode.

Also: `stdin=subprocess.DEVNULL`. A child that reads stdin would otherwise wait on your server's
stdin, which for an MCP stdio server is the *protocol channel*.

And decode with `text=True, encoding="utf-8", errors="replace"`. A file name or an error message
with a stray byte must not crash the reader thread.

## Run it

```bash
python 02-subprocess-done-safely/main.py
```

## Key takeaways

- Argument lists, never `shell=True`. Resolve paths to absolute.
- Drain stdout and stderr on threads; keep a bounded tail.
- Deadline via short polls and `time.monotonic()`.
- Kill the process tree (`taskkill /T` or `killpg`), and prove it with a grandchild.
- `stdin=DEVNULL`, explicit UTF-8 with `errors="replace"`.
