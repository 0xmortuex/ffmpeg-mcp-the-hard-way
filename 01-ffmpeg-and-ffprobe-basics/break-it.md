# Break It: ffmpeg and ffprobe basics

## Challenge 1: The silent video

Remove the `?` from `-map 0:a:0?` in `transcode()` and run it on the audio-less clip.

**Hint:** Without the `?`, "map the first audio stream" is mandatory, and ffmpeg fails with
"Stream map '0:a:0' matches no streams". Your server would reject every screen recording that
has no sound.

## Challenge 2: A wrong override

Run `FFMPEG_PATH=/nope python main.py` (PowerShell: `$env:FFMPEG_PATH='C:\nope'`). Now change
`find_tool` so that a bad override falls back to PATH. Which behaviour would you rather debug at
2 a.m.?

**Hint:** A silent fallback means the user thinks they are testing ffmpeg 7 and are really on
ffmpeg 4. An error costs ten seconds. A wrong version can cost an afternoon.

## Challenge 3: Believe the strings

Compare `info["format"]["duration"] > 2` with `float(info["format"]["duration"]) > 2`.

**Hint:** On Python 3 the first raises `TypeError` (str vs int). In JavaScript it would quietly
coerce. Either way, ffprobe's JSON numbers are strings; convert at the boundary, once.

## Challenge 4: Odd dimensions

Generate a clip with `testsrc2=size=321x241` and transcode it with `libx264 -pix_fmt yuv420p`.

**Hint:** H.264 in yuv420p stores chroma at half resolution, so width and height must be even:
"width not divisible by 2". The finished server detects odd sizes and adds
`scale=trunc(iw/2)*2:trunc(ih/2)*2`.

## Challenge 5: Does `-ss` position matter?

Trim with `-ss 5 -i in.mp4 -t 2 out.mp4` and with `-i in.mp4 -ss 5 -t 2 out.mp4`. Compare how
long each takes on a long file, and check the durations with ffprobe.

**Hint:** Before `-i`, ffmpeg seeks (fast) and, when re-encoding, decodes forward to the exact
frame. After `-i`, it decodes and throws away everything up to 5 s (slow). With modern ffmpeg
the result is the same; the time is not.
