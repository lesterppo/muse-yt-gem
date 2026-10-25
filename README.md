# yt-gem — AI-agent-native YouTube distiller via free Gemini web

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-green.svg)](https://www.python.org/)

**One command turns a YouTube video into a detailed, timestamped markdown
distillation — without downloading the video, extracting frames, or paying
for transcription or a video API.**

```text
yt-gem https://www.youtube.com/watch?v=dQw4w9WgXcQ
  → {"ok": true, "f": "~/.hermes/yt_gem_output/dQw4w9WgXcQ.detail.md",
     "video_id": "dQw4w9WgXcQ", "mode": "detail",
     "sections": ["TL;DR", "At a glance", "Chronological breakdown", ...]}
```

The full distillation lives on disk. Stdout is only a JSON pointer, so the
calling agent reads what it needs — the TL;DR, one chapter slice (the
sidecar JSON gives each section's byte offset), or the claims list —
instead of swallowing a whole video's worth of tokens.

## Why Gemini web, and why a browser?

Another AI agent "watching" a video the hard way pays for download +
frames + transcription + a long context, and usually ends up with a thin
summary anyway. Free Gemini web already watches the video natively when
you paste its URL into chat. yt-gem just makes that agent-consumable:
a fixed, detailed output schema, caching, follow-ups, and machine errors.

Gemini's web endpoints are browser-gated (see `hermes-gem-pw` README):
`batchexecute`/`StreamGenerate` silently drop non-browser HTTP clients.
So, like its prototype `gem-pw`, yt-gem originally drove a real headed
Chromium via Playwright — CDP-first (warm browser on `127.0.0.1:9224`),
headed fallback, `xvfb-run` when DISPLAY is unset.

Since 2026-10-25 yt-gem's default backend is WebAPI instead
(`--backend auto`): it reads the signed-in profile's session cookies
in-process via Playwright (never printed, never written to a file),
then calls the same free Gemini web backend over HTTP via
`gemini-webapi` (bootstrapped into `~/.hermes/yt_gem_deps` if the
system Python refuses a plain pip install). The browser UI remains
as fallback on WebAPI failure, and as the only path for `--gem` and
`--followup`. Limits on WebAPI for this account: only one model is
listed (`gemini-自動`, auto), so `-m pro/flash` is honoured only on
the browser path; the WebAPI pointer reports `model: auto`.

**WebAPI caption retry (fixed 2026-10-25, deep-tested live).** A
URL-only WebAPI prompt cannot reliably make Gemini watch an arbitrary
video — it replies `VIDEO_NOT_ACCESSIBLE`, and the same video may
succeed on one run and refuse on the next (measured on
`ad89q4ZlCxY`: refused 21:14, succeeded 21:18, refused again 21:22).
So on a URL refusal, yt-gem fetches the video's captions with yt-dlp
(manual first, then auto-generated; default/Android/iOS player
clients in turn, since YouTube's bot-check is flaky per client) and
re-asks Gemini to distill *from the transcript*. The pointer reports
`"source": "url"` or `"source": "captions:<lang>"` — a transcript
distillation is never passed off as a video watch, and its timestamps
are caption cue times. On the test video the caption path was *more*
accurate than the URL path (Anthropic + Theorem + Rocq, verified
against the real captions, vs the URL path's garbled Relicorp/FUM/Lean).
Videos with no captions at all still fail cleanly with
`VIDEO_NOT_ACCESSIBLE` — yt-gem never hallucinates from a title.

## Install

```bash
git clone https://github.com/lesterppo/muse-yt-gem.git
cd muse-yt-gem
bash install.sh
```

## Setup (one time)

```bash
yt-gem-login   # sign into Gemini once; profile persists
```

yt-gem reuses gem-pw's profile family (`~/.gemini-cli/cr-profile`,
falling back to `pw-profile`), so if you already signed in via
`gem-pw-login`, yt-gem needs no new sign-in — and vice versa. The two
tools also share one profile lock (`~/.hermes/gem_pw.lock`), so they
never collide on the same Chromium profile.

## Quick start

```bash
# Detailed distillation (default): TL;DR, at-a-glance, chronological
# breakdown, claims+evidence, numbers/names/definitions, resources,
# and uncertainties — all timestamped.
yt-gem https://www.youtube.com/watch?v=dQw4w9WgXcQ

# Shorter modes
yt-gem <url> --brief
yt-gem <url> --chapters
yt-gem <url> --claims

# Ask one question about the video (timestamps + caveats, and a plain
# "the video does not address this" instead of general-knowledge filler)
yt-gem <url> "What does the speaker say about pricing?"

# Follow-up without re-watching: resume the same Gemini conversation
yt-gem <url> -c sess.json "Summarise the demo part"
yt-gem --followup -c sess.json "What was the third example?"

# Through a specific Gem, a different model, or a longer timeout
yt-gem <url> --gem <gem-id>
yt-gem <url> -m flash
yt-gem <url> -t 600        # long videos may need this

# Preview without a browser (parses the URL, builds the exact prompt)
yt-gem <url> --dry-run
yt-gem <url> --dry-run --print-prompt
```

Accepted inputs: `watch?v=`, `youtu.be/`, `shorts/`, `live/`, `embed/`,
or a bare 11-character video id. Channel, playlist, and search URLs are
rejected with `BAD_URL` — they contain no single video to distill.

## Output format

Success (stdout, ~200 chars):

```json
{"ok": true, "f": "~/.hermes/yt_gem_output/dQw4w9WgXcQ.detail.md",
 "s": 8421, "t": 87.3, "video_id": "dQw4w9WgXcQ",
 "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "mode": "detail",
 "title": "…", "sections": ["TL;DR", "At a glance", …],
 "timestamps": 24, "cached": false}
```

Alongside every `.md` file sits a `.json` sidecar with the same fields
plus `section_index` (`[{section, start, chars}]`) so an agent can slice
one section out of the file without reading the rest.

Caching: a canonical-mode distillation is cached at
`~/.hermes/yt_gem_output/<video_id>.<mode>.md`. Asking for the same
video + mode again returns the cached pointer in milliseconds and never
re-asks Gemini. Use `--force` to re-distill, `--no-cache` to skip the
cache read. Custom questions and follow-ups are never cached.

## Honesty contract (read this before trusting a distillation)

- **Timestamps are Gemini's, not verified.** Treat them as pointers
  ("look near 12:34"), not ground truth.
- **This is not a verbatim transcript.** Quotes are verbatim only when
  Gemini is confident; otherwise the prompt forces paraphrase without
  quotation marks. For exact wording, watch the captioned segment at
  the cited timestamp.
- **If Gemini cannot access the video** (private, removed, age-gated,
  region-blocked), it must answer with the sentinel
  `VIDEO_NOT_ACCESSIBLE`, and yt-gem turns that into the machine error
  `VIDEO_NOT_ACCESSIBLE` instead of a hallucinated summary. A
  hallucinated summary is worse than no summary.
- **"What is NOT in the video" is a real section**, not an afterthought:
  what Gemini could not hear/see, and what the video does not answer.

## Error codes

| Code | Meaning | Action |
|------|---------|--------|
| `NOT_SIGNED_IN` | No Gemini session in the browser profile | Run `yt-gem-login` |
| `BAD_URL` | Not a YouTube video URL/id | Pass a video URL, not a channel/playlist |
| `VIDEO_NOT_ACCESSIBLE` | Gemini cannot play this video | Check it is public and playable |
| `NETWORK` | Chromium cannot reach gemini.google.com from this network | On the egress-proxy VM this is now handled by the localhost forwarder; elsewhere, run from a network that reaches Gemini (residential IP / own device); do not just relaunch |
| `EMPTY` | No response within timeout | Retry with `-t 600` for long videos |
| `NO_INPUT` / `TYPE_FAILED` | Prompt did not land in the composer | Retry (one automatic retry) |
| `LOCKED` | Another gem-pw/yt-gem run holds the profile lock | Wait; stale locks self-heal from dead PIDs |
| `USAGE` | Missing argument (e.g. follow-up without `-c` + question) | See `yt-gem --help` |

Note on retries: video re-analysis is expensive, so yt-gem retries a
transient failure **once**, not three times like gem-pw's cheap chats.
`NETWORK` and `VIDEO_NOT_ACCESSIBLE` are never retried.

## For AI agents

See [AGENTS.md](AGENTS.md) for the full agent guide and
[SKILL.md](SKILL.md) for the skill-card version. The short version:

1. `yt-gem <url> --dry-run` first if you only need to validate the URL.
2. Read the pointer JSON, then read only the sections you need from
   the `.md` file (use the sidecar's `section_index` offsets).
3. Ask follow-ups with `-c sess.json` — never re-distill to ask a
   second question about the same video.
4. Never present a timestamp or quote from a distillation as verified
   without checking the video at that timestamp.

## Connection on VM egress proxies (fixed 2026-10-25)

Chromium cannot do this VM's egress proxy auth directly
(`ERR_TUNNEL_CONNECTION_FAILED`), while curl/Python through the same
proxy work — and `gemini.google.com` additionally drops HTTP/1.1
requests after a successful CONNECT+TLS (curl default: 000, curl
`--http2`: 200, 829 KB). yt-gem therefore starts a localhost CONNECT
forwarder automatically on such networks (vendored `proxy_fwd.py`,
from tos-cli): it listens on `127.0.0.1:8888`, dials the upstream proxy
at its IPv4 address explicitly, and injects Proxy-Authorization from
`$https_proxy`. Headed Chromium is pointed at the forwarder with
`ignore_https_errors` (intercept CA). Verified on this VM:
Playwright via the forwarder loads `gemini.google.com/app` (title
"Google Gemini"), and yt-gem now reaches Gemini and correctly reports
`NOT_SIGNED_IN` instead of `NETWORK`. Disable with
`YT_GEM_NO_FWD=1`; force on any network with `YT_GEM_USE_FWD=1`.

## Limitations (verified 2026-10-25)

- **A full end-to-end distillation needs a signed-in Gemini
  session.** Sign in once via `yt-gem-login` (needs a display; on a
  headless VM run it where you can see the Chromium window, i.e. your
  own device). Live-tested 2026-10-25 after sign-in: detail, brief,
  chapters, claims, ask, and follow-up all succeed; WebAPI and browser
  backends both proven on real videos.
- **WebAPI URL-only access is nondeterministic.** The same video may
  succeed on one run and refuse on the next. The caption retry (above)
  is the reliability fix for captioned videos; for uncaptioned videos
  the browser path is the only route, and it can refuse too.
- **No captions, no WebAPI distillation.** If a video has neither
  captions nor a successful URL/browser watch, yt-gem returns
  `VIDEO_NOT_ACCESSIBLE`. Downloading + Whisper transcription is a
  known manual workaround, deliberately not bolted into yt-gem (it
  would add a ~450 MB dependency + model download to every install).
- Long videos take minutes (video analysis + generation); the default
  300 s timeout may be too short for them.
- Gemini web's video handling varies by video (captions, length,
  restrictions); results for an unusual video should be spot-checked.

## Files

- `yt-gem` — the CLI (self-contained, Python 3.10+, Playwright)
- `yt-gem-login` — one-time browser sign-in
- `gemini_cli_login.py` — paste-once headless sign-in driver (creds in
  a mode-600 file, deleted in a `finally` block; see its header)
- `proxy_fwd.py` — localhost CONNECT forwarder for TLS-intercepting
  egress proxies (see "Connection on VM egress proxies")
- `install.sh` — installs deps, Chromium, and scripts to `~/.local/bin`
- `AGENTS.md` / `SKILL.md` — agent guide / skill card
- `tests/test_yt_gem.py` — offline unit tests (no browser, no network)

## Prototype

Built from `lesterppo/hermes-gem-pw` (gem-pw / gemini-web) as the
prototype: same CDP-first headed-Chromium approach, same profile
family, same pointer-JSON-on-stdout / full-response-on-disk contract,
same placeholder-guard response polling — specialised for one job
(YouTube distillation) instead of general Gem chat.

## Privacy

No API keys, tokens, cookies, or personal identifiers in this repo.
The browser profile at runtime holds your Gemini session — git-ignored,
never committed.

## License

MIT — see [LICENSE](LICENSE)
