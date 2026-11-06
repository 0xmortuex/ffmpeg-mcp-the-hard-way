# Break It: The MCP wrapper

## Challenge 1: Print to stdout

Add `print("planning compress")` at the top of `plan_compress` and run the demo.

**Hint:** In `--serve` mode stdout carries JSON-RPC. Your line is not valid JSON-RPC, so
depending on the SDK version the client skips it, errors, or desynchronizes. Use
`print(..., file=sys.stderr)` for diagnostics.

## Challenge 2: A plain exception

Change `MediaError` to inherit from `Exception` instead of `ToolError`, and rerun the demo.

**Hint:** The checks for "overwrite=true" and "too small" fail: the client now receives only
`Error executing tool compress`. The text you wrote is in the server's stderr, which the agent
never sees. This is the single most common mistake in `mcp >= 2` servers.

## Challenge 3: Block the event loop

In `run_plan`, replace the `await anyio.to_thread.run_sync(...)` with a direct call:
`return execute(plan, timeout_s, cancel, progress)`. Call `media_info` while a `compress` runs.

**Hint:** The event loop is stuck inside the blocking call, so nothing else is served, progress
notifications cannot be sent (the reader thread's `from_thread.run` waits for the loop), and
cancellation cannot even be received.

## Challenge 4: Lose the loop token

Remove `token=token` from the `anyio.from_thread.run` call and run the demo.

**Hint:** The progress callback runs on a reader thread that the runner started, not on an anyio
worker thread, so `from_thread.run` raises "Not running inside an AnyIO worker thread". That
exception kills the reader thread (look for the traceback in the server's stderr), so progress
silently stops: only the final 100% arrives, because that one is sent from the worker thread.
The demo asserts at least three updates to catch exactly this. The finished mediakit-mcp goes
further and turns a failing progress callback into a visible error instead of a silent stall.

## Challenge 5: Cancel without the event

Delete `cancel.set()` from the `except` branch and cancel a call.

**Hint:** The client moves on but ffmpeg runs to completion in the background, then renames
`slow.partial.mp4` into place as if someone had asked for it. The cancel check in the demo
catches this: it asserts no ffmpeg survives and no output appears.

## Challenge 6: One tool to rule them all

Add a tool `ffmpeg(args: list[str])` that runs whatever arguments it is given. What can an agent
now do that it could not before?

**Hint:** Anything ffmpeg can do: write to arbitrary paths (`-y` overwrites), read any file the
user can read into an output, use network protocols as inputs and outputs, run filters that
open files. The narrow tools enforce overwrite rules, naming and limits; a pass-through tool
throws all of it away.
