# Module 05: Dry-run design

## The concept

An agent about to re-encode your only copy of a video deserves a chance to say "show me first".
`dry_run=true` returns the exact ffmpeg command line instead of running it. The design question
is how to build it so the preview is *true*.

## Plans are data

The tempting implementation is one function with `if dry_run: print(...) else: subprocess.run(...)`
scattered through it. Over time the print and the run drift: someone adds a flag in one branch
only. The preview then lies, which is worse than having no preview.

Instead, split the work:

1. **Plan**: validate arguments, probe the input, decide the output path, and produce a `Plan`:
   the argument list, the final path, notes for the user, the expected duration.
2. **Show or run**: `dry_run(plan)` formats it; `execute(plan)` runs the same `plan.argv`.

There is no second place to build the command, so they cannot disagree. The module's demo goes
one step further: it takes the *printed text*, pastes it into a real shell, and checks it works.

A dry run still runs `ffprobe` on the input (read-only), because the real command depends on
what the file is (its duration, whether it has audio, odd dimensions). A preview computed
without looking at the file would not be the real command.

## Quoting for humans

The argument list is for the machine. The preview is for a person who may paste it into a
terminal, so it must be quoted for *their* shell:

- POSIX: `shlex.quote` does it.
- Windows: `subprocess.list2cmdline` only adds quotes around spaces. A filter graph such as
  `split[a][b];[a]palettegen[p]` has no spaces but contains `;`, which PowerShell reads as the end
  of the command. So also quote anything outside a conservative safe set
  (letters, digits, `_@%+=:,./\-`).

The demo uses a directory called `my clips; with [odd] names` on purpose and runs the quoted
command through PowerShell (or `sh`) to prove it.

## Never overwrite unless told to

Two layers:

1. **At plan time**, if the output exists and `overwrite` is false, raise an error that names
   the fix ("Pass overwrite=True to replace it"). A dry run reports this too, so the preview does
   not promise something the real run would refuse.
2. **At commit time**, check again. The file could have appeared while a long encode ran.

The same error also covers `output == input`, which would read and write the same file.

ffmpeg itself gets `-y`: it must not stop and ask. The decision was made before ffmpeg started.

## Partial files and atomic rename

ffmpeg is told to write `clip.trimmed.partial.mp4` (the extension stays last because ffmpeg picks
the container from it). Only after a successful exit does `os.replace` move it to
`clip.trimmed.mp4`:

- A crash, timeout or cancel never leaves a half-written file with the real name.
- An *overwrite* that fails leaves the previous file untouched; it is replaced only by a finished
  result. The demo checks both.
- `finally` removes the partial file on every path.

`os.replace` is atomic on the same volume, which is why the partial lives next to the final file
and not in a temp directory somewhere else.

## Derived output names

If the user does not choose an output, derive one next to the input: `clip.mp4` becomes
`clip.trimmed.mp4`. The tag says what happened, and the original is never the target.

## Run it

```bash
python 05-dry-run-design/main.py
```

## Key takeaways

- Build the command as data once; preview and execution share it.
- A dry run probes (reads) but never writes.
- Quote the preview for the human's shell, including `;` and brackets for PowerShell.
- Decide overwrite twice: at plan time and at commit time.
- Write to `.partial`, rename on success, clean up in `finally`.
