# Break It: Testing with lavfi

## Challenge 1: Mutation test the server

Edit `06-the-mcp-wrapper/main.py` and change `0.95` in `plan_compress` to `1.2`. Run this module.
Then revert it, and break something else (drop `-maxrate`, return a wrong error text).

**Hint:** `compress_hits_the_size...` should go red when the budget is inflated. If a change you
make does *not* turn any check red, you have found a gap: write the check that would catch it.

## Challenge 2: A fixture that proves nothing

In `make_fixtures` remove `-vf noise=...` so the source is a clean test card, and rerun.

**Hint:** The fixture becomes tiny (and the size assertion `> 2 MiB` in `make_fixtures` fires).
Without it, "compress to 1.5 MiB" might pass because the file was already under 1.5 MiB. A
test needs input that forces the behaviour under test.

## Challenge 3: A tolerance of zero

Set `tol=0.0` in `assert_duration`.

**Hint:** Checks that pass today fail: audio frames and container timestamps make exact
equality unreachable. Tolerances are part of the test design; too tight is flaky, too loose
hides bugs. A good one is a fraction of the smallest bug you care about.

## Challenge 4: Assert only the upper bound

Delete the lower bound (`> 0.5 * 1.5 * MIB`) in the compress check. Then change the server to
encode at a ridiculously low bitrate.

**Hint:** The test stays green for a server that returns a smudge. Size targets need a window:
at or under the limit *and* a reasonable share of it.

## Challenge 5: Trust the server's own report

Rewrite one check to assert only that the tool's text contains `"met"`, with no ffprobe call.
Introduce a bug where the server always prints "met".

**Hint:** The test passes. Reports are claims; files are facts. Assert on the file.

## Challenge 6: Leak a process

Remove the `cancel.set()` line in Module 06, run its demo, and look at your process list after
it fails.

**Hint:** The demo fails (the "ffmpeg survived the cancel" or the leftover-output assertion),
because the encode keeps running to completion after the client walked away, and even writes its
output. Tests that spawn processes need to prove they clean up, and your CI machine will thank you.
