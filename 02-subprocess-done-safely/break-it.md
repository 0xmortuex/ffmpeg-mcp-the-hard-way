# Break It: Subprocess done safely

## Challenge 1: Kill only the parent

In `kill_tree`, replace the platform branches with `proc.kill()` and run the file.

**Hint:** The grandchild assertion fails: the child dies, but the sleeping grandchild is
orphaned and keeps running (check Task Manager or `ps`). With real ffmpeg jobs that means a
cancelled encode that still eats a CPU core.

## Challenge 2: Forget `stdin`

Remove `stdin=subprocess.DEVNULL` and run a child that reads stdin, such as
`[sys.executable, "-c", "import sys; sys.stdin.read()"]`, with a 3 s timeout.

**Hint:** It inherits the parent's stdin and waits for input that never comes. In an MCP stdio
server the parent's stdin is the JSON-RPC stream, so the child could even steal protocol bytes.

## Challenge 3: Unbounded stderr

Change `deque(maxlen=20)` to a plain list and let the child write 500 MB of stderr (loop
`sys.stderr.write("x" * 1000 + "\n")`). Watch memory.

**Hint:** Memory grows without bound. A malformed input that makes a tool spew warnings can take
your server down. Keep the tail.

## Challenge 4: Use the wall clock

Replace `time.monotonic()` with `time.time()`, then change your system clock back an hour while a
job runs (or simulate it by subtracting 3600 from the deadline calculation).

**Hint:** Deadlines computed from the wall clock fire early or never when the clock is adjusted
(NTP sync, DST handling bugs, a laptop waking up). Monotonic time only moves forward.

## Challenge 5: The injection that survives quoting

Build the command with `shlex.quote` on POSIX or `list2cmdline` on Windows and keep `shell=True`.
Find a file name that still breaks it.

**Hint:** Quoting rules differ between `cmd.exe`, PowerShell and `sh`, and `cmd.exe` expands
`%VAR%` even inside quotes. Every escaping scheme has an edge case; the argument list has none
because there is nothing to parse.
