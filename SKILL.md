---
name: yt-gem
description: AI-agent-native YouTube distiller via free Gemini web — detailed timestamped markdown on disk, JSON pointer on stdout, cached, with follow-ups. No API key.
version: 1.0.0
author: Peter (lesterppo)
tags: [youtube, gemini, cli, playwright, distillation, video, no-api-key, free]
platforms: [linux, macos, wsl]
metadata:
  hermes:
    category: automation
    related_skills: [gem-pw, gem-cli]
    config:
      yt_gem_output_dir: "$HERMES_HOME/.hermes/yt_gem_output"
---

# yt-gem — YouTube distillation via free Gemini web

One command, one video, one detailed markdown file. Stdout is only a
JSON pointer — read the file (or one section of it, via the sidecar's
`section_index`) instead of loading a video into context.

## When to use

- Someone shares a YouTube link and asks what is in it, what was said
  about X, or for chapters / claims from it.
- You need detail (chronology, numbers, names, resources, caveats),
  not a one-paragraph summary.
- You will ask more than one question about the same video.

## Quick reference

| Need | Command |
|------|---------|
| Detailed distillation | `yt-gem <url>` |
| TL;DR + takeaways | `yt-gem <url> --brief` |
| Chapter breakdown | `yt-gem <url> --chapters` |
| Verifiable claims | `yt-gem <url> --claims` |
| One question | `yt-gem <url> "question"` |
| Follow-up (no re-watch) | `yt-gem --followup -c sess.json "question"` |
| Validate URL / see prompt | `yt-gem <url> --dry-run [--print-prompt]` |
| Re-distill (ignore cache) | `yt-gem <url> --force` |
| Long video | `yt-gem <url> -t 600` |
| Via a specific Gem | `yt-gem <url> --gem <gem-id>` |

## Output format

Success: `{"ok": true, "f": "…/<video_id>.<mode>.md", "s": 8421,
"t": 87.3, "video_id": "…", "mode": "detail", "sections": […],
"timestamps": 24, "cached": false}`

Sidecar `<file>.json` holds `section_index` with byte offsets per
section — slice one section instead of reading the whole file.

## Error codes

`NOT_SIGNED_IN` (run `yt-gem-login`), `BAD_URL` (channel/playlist, not
a video), `VIDEO_NOT_ACCESSIBLE` (Gemini cannot play it — do not
summarise the title instead), `NETWORK` (this network cannot reach
Gemini — move the run, do not loop retries), `EMPTY` (retry with
longer `-t`), `LOCKED` (another gem-pw/yt-gem run holds the profile).

## Pitfalls

- **Not a verbatim transcript.** Quotes/timestamps are Gemini's and
  unverified — check the video at the cited timestamp before citing
  them as fact.
- **One browser at a time.** Concurrent yt-gem/gem-pw runs collide on
  the shared profile; the second gets `LOCKED`.
- **Long videos take minutes.** Default timeout is 300 s.
- **Connection via the localhost forwarder is verified on the
  reference VM** (Playwright loads gemini.google.com/app; yt-gem
  reaches Gemini and reports NOT_SIGNED_IN). A full distillation
  still needs a signed-in session first — do not call distillation
  "proven" until a signed-in run succeeds.
- **Headless blocked by Google.** Headed Chromium is used;
  `xvfb-run` is the fallback on headless boxes.

## Verification

```bash
yt-gem --help
yt-gem <url> --dry-run
yt-gem <url> --brief -o /tmp/yt-test.md   # then read /tmp/yt-test.md
```

## License

MIT
