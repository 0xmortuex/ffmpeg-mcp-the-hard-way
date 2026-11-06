# Module 07: Testing with lavfi

## The concept

A media server is easy to get subtly wrong: the file exists but has no audio, the duration is 4
seconds off, the "10 MB" output is 10.4 MB. Mocks cannot catch any of that, because the bugs live
in what ffmpeg actually produced. The tests here generate real media, run the real server, and
measure the real output.

## No fixtures in git

`lavfi` virtual devices generate inputs:

- `testsrc2`: a moving test card, with size, rate and duration you choose
- `sine`: a tone
- add `-vf noise=alls=25:allf=t+u` to make the picture incompressible, so a "compress to
  1.5 MiB" test starts from a 20 MB file and has to do real work

Generated at test time, the inputs are small to store (nothing), legal, and exactly known: a
6-second source is 6 seconds, so the expectations are not guesses. The module also builds the
**bad** inputs deliberately: a file of junk bytes (corrupt), and the first 3000 bytes of a real
mp4 (truncated).

## Measure with ffprobe

Assertions use the ground truth tools, not the server's own report:

| Claim | Check |
|-------|-------|
| "The output is under the target" | `path.stat().st_size <= limit` |
| "The trim is 2 seconds" | ffprobe duration within a tolerance |
| "It's H.264/AAC" | ffprobe `codec_name` of each stream |
| "The GIF has 20 frames, 320 px wide" | `ffprobe -count_frames`, `width` |
| "Silent in, silent out" | the set of stream types |
| "No debris" | no `*.partial.*`, no pass logs left |

**Tolerances.** Durations never match to the millisecond (audio frame size, keyframes, container
rounding). Choose a tolerance that catches a real bug, such as a lost second, but is not zero.
For size, assert both bounds: under the target *and* above half of it, otherwise a server that
returns a one-pixel video passes.

## Test the error paths as hard as the happy ones

Every case an agent will hit is a test:

- file missing, a directory, corrupt, truncated
- no audio stream where audio is needed
- target size impossible, start past the end, fps out of range
- output already exists, then `overwrite=true`
- dry run leaves the folder byte-for-byte unchanged

and each asserts on the **message**, because the message is the product: "overwrite=true" must
appear in the exists error, "too small" in the size error.

## Test through the real interface

The harness starts the server as a subprocess and talks MCP over stdio, exactly like a client.
This catches things in-process tests cannot: output polluting stdout, errors that are not
`ToolError`s (the client sees a generic message), missing tool descriptions, schema problems.

## Prove the tests can fail

The module first points its assertions at a file that *should* violate them (the 20 MB source
against a 1 MiB limit, a 6 s file against 60 s) and requires them to raise. A test that cannot
fail is not a test. This is a tiny version of mutation testing: break the code on purpose and
confirm something goes red (the break-it files do this at scale).

## Slow and cancelled jobs

Module 03's `-re` trick yields a job slow enough to time out or cancel. The finished project's
tests start a long job through the MCP interface, cancel the request, and assert that ffmpeg is
gone (by searching the process list for the job's directory name) and the partial output
disappeared. The Module 06 demo already contains one such check; the project has more.

## Run it

```bash
python 07-testing-with-lavfi/main.py
```

(It launches `06-the-mcp-wrapper/main.py --serve` itself.)

## Key takeaways

- Generate inputs with lavfi; make them noisy when size matters; build corrupt ones on purpose.
- Verify outputs with ffprobe, with sensible tolerances and two-sided size bounds.
- Test error messages, not just error occurrence.
- Test through stdio, the way a client connects.
- Make sure each assertion can fail.
