# Module 03: Parsing progress

## The concept

A two-minute encode with no feedback looks like a hung server. MCP lets a tool send progress
notifications while it works, so the client can show a bar. ffmpeg can describe its progress in
a machine-readable way; this module turns that into a number between 0 and 1.

## Why not parse the usual status line?

The line ffmpeg prints on a terminal (`frame=  42 fps= 25 q=28.0 size=  256kB time=00:00:01.68
bitrate=1248.8kbits/s speed=1.01x`) is for humans. It is redrawn with carriage returns, its
spacing changes, and `-loglevel error` hides it entirely.

`-progress pipe:1 -nostats` writes clean `key=value` blocks to **stdout** instead (stderr stays
for errors). Each block ends with `progress=continue`, or `progress=end` on the last one:

```
frame=50
fps=25.00
out_time_us=2000000
out_time_ms=2000000
out_time=00:00:02.000000
speed=1.01x
progress=continue
```

(`pipe:2` would write to stderr, `pipe:1` to stdout. Using stdout keeps the two streams
separate, so error text never gets parsed as progress.)

## Three things that bite

**`out_time_ms` is microseconds.** A long-standing misnomer: despite the name, the value is in
microseconds, same as `out_time_us`. Use `out_time_us` and divide by 1,000,000.

**`N/A` shows up.** Before the first frame is written, `out_time_us` can be the literal string
`N/A`. `int("N/A")` is a crash on the very first block. Check with `isdigit()` and skip.

**Progress can overshoot.** The last block can report slightly more output time than your
estimate (an audio frame past the end). Clamp to 1.0.

## From output time to a fraction

`fraction = out_time / total_seconds`, where `total_seconds` is the **expected output duration**:
the input duration for a transcode, `end - start` for a trim, `duration / speed` for a speed
change. That is why the planner (Module 05) records it alongside the command.

## Throttling

ffmpeg emits a block about twice a second, which is fine, but a fast encode can burst, and each
MCP notification is a message over the pipe to the client. Report at most every 0.5 s. Always
send the final `1.0` yourself after the process exits successfully: the last throttled update
may have been 0.97.

## Multi-step jobs

A two-pass encode (Module 04) is two ffmpeg runs. Step *i* of *n* reports
`(i + fraction) / n`, so the bar moves 0 to 1 once instead of twice. The demo runs two steps and
checks the sequence is continuous and ends at exactly 1.0.

## Reading without a busy loop

`for line in proc.stdout:` blocks until ffmpeg writes. The stderr pipe still needs its own
reader thread (Module 02) or the child can deadlock on a full buffer while you wait on stdout.

## Reproducing slow jobs in tests

`-re` makes ffmpeg read its input at native speed, so `testsrc ... duration=3` really takes 3 s.
That gives a test an encode that is slow enough to observe, to time out, and to cancel, with no
huge files.

## Run it

```bash
python 03-parsing-progress/main.py
```

## Key takeaways

- `-progress pipe:1 -nostats`: stdout for progress, stderr for errors.
- Use `out_time_us`; tolerate `N/A`; clamp to 1.0.
- Progress needs an *expected* duration, so planning must produce one.
- Throttle updates; always finish with an explicit 1.0.
- `-re` + `lavfi` = a slow job on demand.
