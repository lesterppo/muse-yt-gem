# AGENTS.md — Agent Guide for yt-gem

## What this tool does

`yt-gem` distills one YouTube video through free Gemini web into a
detailed, timestamped markdown file. It exists because an agent
"watching" a video the hard way (download, frames, transcription, huge
context) is expensive and usually still ends in a thin summary, while
Gemini web already watches the video natively from its URL.

## When to use it

- A user (or another agent) shares a YouTube link and asks what is in it,
  what was said about X, or for chapters/claims from it.
- You need more than a summary: a chronological breakdown, exact numbers
  and names, resources mentioned, and what the video does NOT cover.
- You need to ask several questions about the same video: distill once,
  then follow up in the same conversation.

## When NOT to use it

- You need a verbatim transcript. yt-gem is a distillation, not a
  transcript. For exact wording, open the video at the cited timestamp
  (captions on).
- The link is a channel, playlist, or search page. yt-gem rejects these
  with `BAD_URL`; pick one video first.
- You need a verified timestamp or quote for publication. Timestamps
  and quotes in a distillation are Gemini's, unverified — check them
  against the video before citing them as fact.

## How to invoke

```bash
yt-gem <url>                              # detail (default)
yt-gem <url> --brief | --chapters | --claims
yt-gem <url> "question about the video"   # ask mode
yt-gem <url> -c sess.json "first question"   # saves conversation for follow-ups
yt-gem --followup -c sess.json "next question"
yt-gem <url> --dry-run                    # validate URL + prompt, no browser
yt-gem <url> -o out.md -t 600             # custom output / long video
yt-gem <url> --force                      # ignore cache, re-distill
```

## Output contract (do not re-invent it)

Stdout is ALWAYS a single JSON object. Success:

```json
{"ok": true, "f": "<path>.md", "s": 8421, "t": 87.3,
 "video_id": "dQw4w9WgXcQ", "url": "https://www.youtube.com/watch?v=…",
 "mode": "detail", "title": "…", "sections": ["TL;DR", …],
 "timestamps": 24, "cached": false}
```

Read the file at `f`, not the stdout. Use the sidecar `<path>.json`
(`section_index: [{section, start, chars}]`) to read only the section
you need. Do not paste the whole distillation into your context when
one section answers the question.

Failure: `{"ok": false, "err": "CODE", "msg": "…"}` — see README's
error table. The important ones:

- `VIDEO_NOT_ACCESSIBLE` — Gemini could not play the video. Do NOT
  fall back to summarising the title/description and presenting it as
  the video's content. Tell the user the video could not be accessed.
- `NETWORK` — this network cannot reach Gemini. Do NOT retry in a loop
  here; move the run to a network that reaches Gemini.
- `EMPTY` — retry once with a longer `-t` for long videos.
- `LOCKED` — another gem-pw/yt-gem run is using the profile; wait.

## Workflow rules

1. Distill once per video+mode. The cache makes a repeat free — but
   check `cached: true` in the pointer so you know you are reading an
   older distillation, and `--force` when the user wants a fresh one.
2. Follow-ups go through `-c sess.json`, never through a second
   distillation of the same video.
3. Present timestamps as "around 12:34 (per the distillation)" unless
   you verified them in the video.
4. If a distillation's "What is NOT in the video / uncertainties"
   section says a point could not be verified, say that to the user
   instead of smoothing it over.

## Setup (one time)

```bash
bash install.sh    # playwright + chromium + ~/.local/bin/yt-gem
yt-gem-login       # or gem-pw-login — same profile family
```

On a VM behind a TLS-intercepting egress proxy, yt-gem starts a
localhost CONNECT forwarder (`proxy_fwd.py`, `127.0.0.1:8888`) and
points headed Chromium at it — Chromium cannot do that proxy's auth
directly (`ERR_TUNNEL_CONNECTION_FAILED`). Disable with
`YT_GEM_NO_FWD=1`; force with `YT_GEM_USE_FWD=1`.

## Files

- Profile: `~/.gemini-cli/cr-profile/` (fallback `pw-profile/`)
- Output: `~/.hermes/yt_gem_output/<video_id>.<mode>.md` (+ `.json` sidecar),
  or `-o <file>`; override the dir with `YT_GEM_OUTPUT_DIR`
- Session: wherever `-c` points
- Lock: `~/.hermes/gem_pw.lock` (shared with gem-pw)

## Dependencies

- Python 3.10+
- playwright (with Chromium)
- gemini-webapi (WebAPI backend; bootstrapped into
  `~/.hermes/yt_gem_deps` on first WebAPI run if plain pip refuses)
- yt-dlp (WebAPI caption retry only; same bootstrap if missing)
- An X display, or `xvfb-run` for headless (auto-detected)

## Privacy

No API keys, tokens, cookies, or personal identifiers in this repo.
The browser profile holds the Gemini session — git-ignored, never
committed.
