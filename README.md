# ffmpeg MCP Server: The Hard Way

Build an MCP server that gives an AI agent everyday media powers: compress a video to fit a
10 MB limit, make a GIF, cut a clip, with previews of the exact command before anything runs.
Start from "what does `ffprobe` print" and end with a server that survives cancellation,
hostile file names and impossible requests. No wrapper libraries, every line explained.

At the end you'll have built a small version of
[mediakit-mcp](https://github.com/0xmortuex/ffmpeg-mcp) yourself.

## Why this exists

Wrapping a command-line tool for an agent looks like a ten-line job: take arguments, run
`ffmpeg`, return the output. Then the real world shows up:

- the agent passes a file called `a.mp4 & del *` and your shell obeys it
- ffmpeg fills its stderr pipe, blocks, and your server hangs forever
- "make it fit in 10 MB" is arithmetic, and CRF cannot do arithmetic
- the user cancels, and a 4-minute encode keeps burning the CPU (and leaves a half-written file)
- a "dry run" flag that is only an `if` statement drifts away from what actually runs

Each module takes one of these and solves it with code you run and a check that proves it works.

## Who this is for

- Developers who've written a "hello world" MCP server and want a tool that touches a real
  process, real files and real failure modes
- Anyone who has called `subprocess.run(..., shell=True)` and wondered whether that was fine
  (it wasn't: Module 02)

**Prerequisites:** Python 3.10+, ffmpeg and ffprobe on PATH, and `pip install -r requirements.txt`.

| OS | Install ffmpeg |
|----|----------------|
| Windows | `winget install Gyan.FFmpeg` |
| macOS | `brew install ffmpeg` |
| Debian/Ubuntu | `sudo apt install ffmpeg` |

Use a full build (libx264, libvpx, libopus, libmp3lame). Windows, macOS and Linux all work.

## Modules

| # | Module | What you'll build |
|---|--------|-------------------|
| 01 | [ffmpeg and ffprobe basics](01-ffmpeg-and-ffprobe-basics/) | Finding the binaries, generating test media with `lavfi`, reading facts as JSON, a well-behaved transcode |
| 02 | [Subprocess done safely](02-subprocess-done-safely/) | Why not to use a shell, the full-pipe deadlock, deadlines, and killing the whole process tree |
| 03 | [Parsing progress](03-parsing-progress/) | `-progress pipe:1`, the `out_time_ms` misnomer, throttling, progress across two-pass jobs |
| 04 | [Hitting a target size](04-hitting-a-target-size/) | Bitrate maths, two-pass encoding, the VBV cap, shrinking instead of smearing |
| 05 | [Dry-run design](05-dry-run-design/) | Plans as data, shell quoting that survives PowerShell, partial files, never overwriting |
| 06 | [The MCP wrapper](06-the-mcp-wrapper/) | A four-tool server: errors as instructions, progress notifications, cancellation |
| 07 | [Testing with lavfi](07-testing-with-lavfi/) | Fixtures from thin air, measuring with ffprobe, error-path tests, tests that can fail |

Each module contains:
- **`README.md`**: the concepts and the design decisions
- **`main.py`**: a working, commented implementation that checks its own results with `assert`
- **`break-it.md`**: challenges that break your own code, with hints

## How to use this course

**Build along.** Read a module, run `python NN-*/main.py`, then do its break-it challenges.

**Reference.** Jump to the module you need. Modules 01-06 stand alone, with no imports between
them. Module 07 tests the server from Module 06 and launches it by path.

**Just use the finished tool.** `uvx mediakit-mcp` is what these modules grow into.

## Every module is verified

```bash
python verify.py          # all modules
python verify.py 04 06    # just these
```

This runs each `main.py` against your ffmpeg and fails if any assertion fails. CI does it on
Linux and Windows on every push and weekly, so the code in this course cannot silently stop
working.

## Architecture overview

```
 AI agent (Claude Code, Claude Desktop, ...)
        |  MCP over stdio: JSON-RPC tool calls, progress notifications   <- Module 06
        v
 +---------------------------------------------------------------+
 | tool: validate arguments, probe the input (ffprobe)           |  <- Module 01
 |   -> build a Plan (argument list + final path + notes)        |  <- Module 04, 05
 |        dry_run? print the Plan.                               |  <- Module 05
 |        else run it:                                           |
 |   runner: no shell, drained pipes, deadline, tree kill        |  <- Module 02
 |           progress parsed from -progress pipe:1               |  <- Module 03
 |           write .partial, rename on success                   |  <- Module 05
 +---------------------------------------------------------------+
        |  argv list
        v
 ffmpeg / ffprobe
```

## Key design principles

**1. Describe intent, hide flags.** "Compress to 10 MB" is one tool call; two-pass logs,
bitrate maths and pixel formats are the server's problem.

**2. Build the command as data, then decide to run it.** One Plan feeds both the preview and
the execution, so they cannot disagree.

**3. Never trust a file name.** Argument lists, absolute paths, no shell.

**4. Every wait has an end.** Deadlines, cancellation, and a process tree that actually dies.

**5. Errors are instructions.** "ffmpeg failed" is a dead end. "10 MB is too small for 3600 s
(needs about 41 MB); trim the clip or raise the target" is the next step.

**6. Test with real media.** `lavfi` makes inputs, ffprobe checks outputs.

## Tech stack

- **Language:** Python 3.10+
- **Protocol:** MCP over stdio
- **Dependencies:** `mcp`, `anyio` (installed with mcp). ffmpeg and ffprobe on PATH.

## License

MIT. Use it, modify it, ship it.

---

Built by [0xmortuex](https://github.com/0xmortuex)
