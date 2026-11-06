# Module 01: ffmpeg and ffprobe basics

## The concept

An MCP server that wraps ffmpeg is mostly a careful ffmpeg user. Before any server code, four
things need to be solid: finding the programs, getting test media, reading a file's facts, and
running one well-behaved transcode.

## Two programs, two jobs

- **`ffprobe`** reads a file and tells you about it. It never modifies anything. Its
  `-print_format json -show_format -show_streams` output is the API your server will lean on.
- **`ffmpeg`** reads inputs, transforms them, writes outputs.

Both ship together. Your server needs both, so it looks for both and says how to install them
when they are missing. `find_tool` checks an explicit override first (`FFMPEG_PATH`), then PATH.
An override that points at nothing is an error, not a silent fall-through to PATH: if someone
set a variable, they meant it, and quietly using a different ffmpeg hides their typo.

## Media out of thin air: lavfi

`-f lavfi -i testsrc2=size=320x240:rate=25:duration=3` makes a 3-second test card from nothing.
`-f lavfi -i sine=frequency=440:duration=3` makes a tone. This is the single most useful trick
for testing media software: no checked-in binary files, no copyright, no "works on my machine"
clip, and the content is fully known (a 3-second source really is 3 seconds long).

## ffprobe as JSON

`ffprobe -v error -print_format json -show_format -show_streams file` gives:

- `format`: container name, duration, size, bit rate
- `streams[]`: one object per stream with `codec_type` (`video`/`audio`/`subtitle`), codec,
  width/height, frame rate, sample rate, channels

Traps worth learning now:

- **Numbers are strings** (`"duration": "3.000000"`). Convert them.
- Fields vary by stream type; video has no `sample_rate`. Use `.get`.
- A file ffprobe cannot read returns a non-zero exit code and an error on stderr. Turn that into
  a message an agent can use ("the file may be corrupt, truncated, or not media").

## A well-behaved transcode

The flags in `transcode()` each earn their place:

| Flag | Why |
|------|-----|
| `-hide_banner` | The version banner is noise. |
| `-nostdin` | ffmpeg listens for keypresses (`q` quits). A server has no terminal. Without this it can stall or swallow input. |
| `-loglevel error` | You want failures, not a play-by-play. |
| `-y` | Overwriting is decided by *your* code before you get here (Module 05). |
| `-map 0:v:0 -map 0:a:0?` | Choose streams explicitly: first video, first audio *if present*. The `?` makes a missing audio track fine instead of fatal. |
| `-pix_fmt yuv420p` | The pixel format every player understands. |

Explicit `-map` also avoids ffmpeg's guesses: a file with subtitles, data tracks or cover art
can fail to mux into mp4 if you let it pick everything.

## Run it

```bash
python 01-ffmpeg-and-ffprobe-basics/main.py
```

It finds the tools, generates a clip, probes it, transcodes it, handles an audio-less video,
rejects a junk file, and checks the missing-ffmpeg message, all with `assert`.

## Key takeaways

- Look for both binaries; make a missing one an actionable error.
- `lavfi` gives you known media for free.
- ffprobe JSON is typed loosely: convert and use `.get`.
- Choose streams explicitly with `-map`, and make audio optional with `?`.
