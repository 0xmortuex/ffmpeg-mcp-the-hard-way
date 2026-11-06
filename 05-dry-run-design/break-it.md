# Break It: Dry-run design

## Challenge 1: A lying preview

Change `execute` so it builds its own argument list (copy-paste `plan_trim` into it and tweak a
flag, for example `-crf 18`). Run the demo.

**Hint:** Everything still passes, which is the problem: nothing checks that the preview and the
run agree. That is why the demo pastes the printed command into a shell. Add a check that
compares `plan.argv` with the argv that is actually executed.

## Challenge 2: Quote with list2cmdline only

In `quote_arg` on Windows, return `subprocess.list2cmdline([arg])` and run the demo, which uses
a filter-like argument if you add one (`"split[a][b];[a]null"`).

**Hint:** list2cmdline leaves it unquoted, and PowerShell cuts the command at the `;`. Add the
argument to `plan.argv` and watch the round trip through PowerShell fail.

## Challenge 3: Put the partial file in a temp dir

Create the partial file in `tempfile.gettempdir()` instead of next to the final file. On a
machine where the temp dir is on `C:` and the output is on `D:`, what does `os.replace` do?

**Hint:** Across volumes `os.replace` cannot be an atomic rename; on Windows it raises or copies
depending on the situation. Keeping the partial on the destination volume keeps the rename
atomic.

## Challenge 4: Name it `clip.mp4.part`

Change `partial_of` to append `.part`. Run it.

**Hint:** ffmpeg infers the container from the extension, and `.part` is not one, so it fails
with "Unable to choose an output format". Keep the real extension last.

## Challenge 5: Check overwrite only at the end

Remove the plan-time `final.exists()` check and keep only the commit-time one.

**Hint:** The agent waits through a full encode and *then* is told the file existed. And the dry
run would have promised an output that the real run refuses. Fail early, and check again late.

## Challenge 6: Skip the `finally`

Delete the `finally` block in `execute` and run the failed-overwrite check, then list the
directory.

**Hint:** A `.partial` file is left behind after failures. Over time the folder fills with debris,
and one of them could be mistaken for a real result.
