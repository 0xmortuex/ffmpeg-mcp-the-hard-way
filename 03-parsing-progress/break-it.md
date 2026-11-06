# Break It: Parsing progress

## Challenge 1: Trust the name

In `out_seconds`, read `out_time_ms` and divide by 1000 (milliseconds, as the name says). Run the
live test.

**Hint:** The value is in microseconds, so your "seconds" are 1000 times too large and every
fraction clamps to 1.0 immediately. Progress jumps to 100% on the first block.

## Challenge 2: Crash on the first block

Remove the `isdigit()` check and call `int(block["out_time_us"])` directly. Feed the parser the
`N/A` block from `SAMPLE_BLOCK`.

**Hint:** `ValueError: invalid literal for int()`. In a real server this happens on a reader
thread, so the thread dies and nobody is told why: progress just stops. The finished
mediakit-mcp makes such failures loud instead of swallowing them.

## Challenge 3: Drop the stderr reader

Delete the `threading.Thread(target=lambda: err.extend(...))` line and make ffmpeg produce a lot
of stderr (remove `-loglevel error` and use `-loglevel debug`).

**Hint:** stdout is being drained but stderr's pipe fills, ffmpeg blocks writing to it, and your
`for line in proc.stdout` never sees another block. Everything stalls. Both pipes need a reader.

## Challenge 4: Report everything

Set `min_interval_s=0` and print how many notifications a 3 s job sends. Then imagine it is a
2-hour video.

**Hint:** Each notification is a JSON-RPC message the client has to render. Throttle by time, not
by count, so a fast job and a slow job both stay cheap.

## Challenge 5: A progress bar for `-c copy`

Run a stream-copy trim with `-progress pipe:1`. What do the blocks look like, and what does your
fraction do?

**Hint:** Copying is nearly instant, so you may get one or two blocks, possibly just `end`. That
is why the explicit final `on_progress(1.0)` exists: a job that finishes before the first
throttled update must still end at 100%.
