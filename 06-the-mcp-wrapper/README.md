# Module 06: The MCP wrapper

## The concept

Modules 01 to 05 produced parts: a prober, a safe runner, a progress parser, bitrate maths and
plans. This module attaches them to MCP and makes the decisions that decide whether an agent
can use the result: what the tools are, what their descriptions say, and how errors look.

## What MCP is, for this purpose

The Model Context Protocol is JSON-RPC over a pipe. For a local server, the client (Claude
Code, Claude Desktop) launches your program and talks over stdin/stdout:

```
 client                                   your server (subprocess)
 initialize          ------------------>
                     <------------------ name, capabilities
 tools/list          ------------------>
                     <------------------ [{name, description, inputSchema}]
 tools/call compress {...} ------------->
                     <------------------ notifications/progress ...
                     <------------------ {content: [{type: text, text: ...}]}
```

stdout is the protocol channel. **Never `print()` to stdout** in a server: your text lands in the
JSON-RPC stream. Use stderr for logs.

## A tool is a function plus its docstring

The `mcp` Python SDK builds the input schema from the signature and takes the description from
the docstring. The model reads that description as prose when deciding what to call, so write
it for the model: what the tool does, what each non-obvious argument means, and what it returns.
Defaults matter too: `dry_run: bool = False`, `overwrite: bool = False`, and an `output` that
is optional because a derived name is usually right.

## Granularity: intent, not flags

Four tools (the full project has nine), each an intent a person would say out loud:
`media_info`, `compress`, `trim`, `make_gif`. Not `ffmpeg(args: list[str])`. A single generic
tool would need the model to know every flag and would let it run arbitrary ffmpeg, including
writing wherever it likes. Intent-level tools keep the surface small, safe, and
self-explanatory, and the server stays in charge of the codecs and the maths.

## Errors are instructions

In `mcp >= 2`, the client only sees the message of a **`ToolError`**. Any other exception becomes
a bare "Error executing tool X" with your explanation left in the server log. So every failure
you mean to show derives from `ToolError`:

```python
class MediaError(ToolError): ...
raise MediaError("output ... already exists. Pass overwrite=true to replace it.")
```

Write each message as the next step: not "ffprobe failed" but "ffprobe could not read 'x.mp4':
corrupt or not media". Genuine bugs (anything that is *not* a `MediaError`) stay hidden from the
client, as they should.

## Async tools around blocking work

The runner is blocking (threads, `subprocess`). The tool is `async` so the SDK can keep serving
other requests, and the blocking part moves to a worker thread:

```python
return await anyio.to_thread.run_sync(work, abandon_on_cancel=True)
```

Planning calls `ffprobe`, which is also blocking, so it goes through `to_thread` too.

## Progress notifications

`ctx.report_progress(progress, total, message)` sends a `notifications/progress`. Progress is
parsed on a reader thread (Module 03) and must hop back to the event loop:

```python
token = anyio.lowlevel.current_token()          # capture while ON the loop
anyio.from_thread.run(ctx.report_progress, ..., token=token)   # call from the thread
```

Without the explicit token, `from_thread.run` raises "Not running inside an AnyIO worker thread"
because the reader thread was started by the runner, not by anyio. The demo's client asserts
that updates arrive, rise, and end at 100.

## Cancellation

When the client abandons a call, the SDK cancels the tool's task. With
`abandon_on_cancel=True` the `await` returns immediately, but the worker thread is still
running ffmpeg. The `except anyio.get_cancelled_exc_class()` branch sets a
`threading.Event`; the runner polls it (Module 02), kills the process tree, and `finally`
removes the partial file. The demo cancels a compress mid-flight and checks, by command line, that
no ffmpeg for that job survives, that no `.partial` file is left, and that the server still
answers afterwards.

## Run it

```bash
python 06-the-mcp-wrapper/main.py            # demo and self-test (starts the server itself)
python 06-the-mcp-wrapper/main.py --serve    # the server, for a client to launch
```

To try it in Claude Code:

```bash
claude mcp add mini-mediakit -- python /full/path/to/06-the-mcp-wrapper/main.py --serve
```

## Key takeaways

- stdout is the protocol; never print to it.
- Few tools, named for intent, with prose descriptions and safe defaults.
- Expected failures are `ToolError`s written as next steps.
- `async` tool + `to_thread` for blocking work; capture the loop token for progress from threads.
- Cancellation = event + process-tree kill + cleanup in `finally`.
