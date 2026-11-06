# Module 04: Hitting a target size

## The concept

"Make this fit under 10 MB" is the most common reason people compress video: Discord, email,
WhatsApp all have limits. It is also the request ffmpeg's friendliest option cannot satisfy.

## CRF cannot do it

`-crf 23` means "constant quality": spend whatever bits each scene needs to look the same. The
size is an outcome. In the demo a CRF 23 encode of a 1 MiB budget clip comes out near 5 MiB,
and there is no CRF value that reliably gives 1 MiB for different inputs.

To hit a size you fix the *bitrate* and let quality vary.

## The arithmetic

```
size (bits) = (video_bps + audio_bps) x duration
```

Solve for video:

```
total_bps = target_MiB x 1024 x 1024 x 8 x 0.95 / duration
video_bps = total_bps - audio_bps
```

Notes on each piece:

- **MiB, not MB.** Discord's "10 MB" is mebibytes in practice. The tools use 1024-based units.
- **The 0.95** is a safety margin for container overhead (headers, indexes) and for rate control
  not being exact. Missing a limit by 1% is a failure for the user, so aim under.
- **Audio first.** Take 128 kb/s, or 96/64/32 if 128 would be more than a quarter of the whole
  budget. At tiny budgets audio must not starve the video.
- **Impossible targets are errors.** If the video share drops below ~60 kb/s there is no picture
  left to save. The error includes the number the user needs ("needs about 41 MB"), so the agent
  can offer a fix.

## Two passes

A single pass with `-b:v 1200k` has to guess the future: it cannot know a calm scene is coming
and bits can be saved for an action scene. **Pass 1** reads the whole video and records how
hard each part is to encode (`-pass 1 -passlogfile P -an -f null -`; the output is thrown
away). **Pass 2** (`-pass 2`) spends the bit budget using that log. Result: a much more accurate
size and better quality for the same bytes.

Details that matter:

- The pass log files (`P-0.log`, `P-0.log.mbtree`) must be cleaned up afterwards, and named
  uniquely per job so two concurrent jobs do not trample each other.
- Pass 1 needs no audio (`-an`); pass 2 adds it.
- Progress for this job is two steps (Module 03).

## The VBV cap

Even two-pass average-bitrate mode can overshoot by several percent on noisy material: the
average is met but individual stretches run hot, and a short clip has little room to average
out. Adding `-maxrate <video_bps> -bufsize <2 x video_bps>` constrains how far above the average
the encoder may go. In the demo the same budget comes out around 0.92 MiB with the cap and over
1.0 MiB without it, which is the difference between "fits" and "rejected by the upload form".

(VP9 behaves differently: its rate control wandered further, so the finished server uses a 10%
margin for `.webm`.)

## Shrink, don't smear

2 MB for 20 s at 1080p is possible only as a blocky mess. Rather than produce one, estimate
*bits per pixel per frame* = `video_bps / (width x height x fps)`. Below roughly 0.045 H.264 looks
terrible. Walk down a ladder of heights (1080, 720, 480, 360, 240, 144), scaling width to keep
the aspect ratio, until the ratio is acceptable. The demo's 0.3 MiB target lands on 426x240.
The result is reported ("scaled to 240p so the bitrate is enough") so the user knows.

## Always report the outcome

Rate control is not exact, so the final report says whether the target was met and, if not, by how
much and what to do ("re-run with a target 10% lower"). Do not claim success you did not check.

## Run it

```bash
python 04-hitting-a-target-size/main.py
```

It builds a noisy 6 s source, computes the budget, runs two-pass with and without the cap,
shows CRF for contrast, downscales for a tiny target, and checks the impossible-target error.

## Key takeaways

- To hit a size, fix the bitrate: `size = bitrate x duration`.
- Reserve audio, keep a safety margin, use MiB.
- Two passes for accuracy; `-maxrate/-bufsize` to cap overshoot; clean up the pass logs.
- Lower the resolution when bits per pixel get too low.
- Reject impossible targets with a useful number; always verify and report the result.
