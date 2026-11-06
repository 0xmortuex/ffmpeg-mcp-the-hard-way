# Break It: Hitting a target size

## Challenge 1: Remove the safety margin

Change `SAFETY = 0.95` to `1.0` and rerun with targets of 0.5, 1 and 2 MiB. How many land over?

**Hint:** Container overhead plus rate-control error means some will exceed the target by a few
percent. A 1% overshoot is still a rejected upload.

## Challenge 2: Starve the video

Give `plan()` a long, nearly-empty budget (`plan(1, 600, True, 1280, 720, 30)`) and read the
error. Then change the audio rule so audio always takes 128 kb/s and see what happens at
`plan(1, 120, ...)`.

**Hint:** A fixed audio bitrate eats a bigger and bigger share of small budgets; at 120 s and
1 MiB it would be more than the whole budget. The "at most a quarter" rule is what keeps video
alive.

## Challenge 3: CRF as a size control

Try to hit exactly 1 MiB with CRF only: write a loop that tries CRF 18 to 40 and prints sizes.
Then try a different source clip.

**Hint:** The size-versus-CRF curve is different for every clip, so you would need a search loop
(several full encodes) for each input. Two-pass ABR gets there in two runs.

## Challenge 4: Share a log name

In `two_pass`, replace the `uuid` log name with a constant `"pass"` and start two encodes at
once from two threads.

**Hint:** Both jobs write and read `pass-0.log`. The second pass of one job consumes the other's
statistics, producing wrong sizes or an ffmpeg error. Unique names per job are not optional.

## Challenge 5: Forget the cleanup

Remove the `finally` that deletes the pass files and run the demo, then list the temp folder.

**Hint:** x264 leaves `.log` and `.mbtree` files per job. A server that compresses a hundred
videos leaves two hundred files behind. The tests in the finished project assert none remain.

## Challenge 6: Odd sizes

Source video 641x361 with a tiny target, so the ladder scales it. What dimensions does
`scale=-2:H` produce, and why `-2` instead of `-1`?

**Hint:** `-1` keeps the aspect ratio but may produce an odd width, which H.264 rejects. `-2`
rounds to the nearest even number.
