"""Offline unit tests for yt-gem — no browser, no network, no sign-in.

Run:  python3 -m pytest tests/ -q   (or: python3 tests/test_yt_gem.py)
The yt-gem file has no .py extension, so it is loaded via importlib.
"""
import importlib.util
from importlib.machinery import SourceFileLoader
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
YT_GEM = HERE.parent / "yt-gem"

# yt-gem has no .py extension, so spec_from_file_location cannot guess a
# loader — use SourceFileLoader explicitly.
loader = SourceFileLoader("yt_gem", str(YT_GEM))
spec = importlib.util.spec_from_loader("yt_gem", loader)
yt = importlib.util.module_from_spec(spec)
loader.exec_module(yt)


def test_parse_watch():
    assert yt.parse_youtube_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_parse_watch_with_extra_params():
    assert yt.parse_youtube_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s&list=PL12345678901") == "dQw4w9WgXcQ"


def test_parse_short():
    assert yt.parse_youtube_id("https://youtu.be/dQw4w9WgXcQ?si=abc") == "dQw4w9WgXcQ"


def test_parse_shorts_live_embed():
    assert yt.parse_youtube_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert yt.parse_youtube_id("https://www.youtube.com/live/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert yt.parse_youtube_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_parse_bare_id_and_no_scheme():
    assert yt.parse_youtube_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert yt.parse_youtube_id("youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_parse_rejects_non_video():
    assert yt.parse_youtube_id("https://www.youtube.com/@somechannel") is None
    assert yt.parse_youtube_id("https://www.youtube.com/playlist?list=PL12345678901") is None
    assert yt.parse_youtube_id("https://example.com/watch?v=dQw4w9WgXcQ") is None
    assert yt.parse_youtube_id("not a url") is None
    assert yt.parse_youtube_id("") is None
    assert yt.parse_youtube_id("short") is None  # 5 chars, not an 11-char id


def test_canonical():
    assert yt.canonical_url("dQw4w9WgXcQ") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_detail_prompt_contract():
    p = yt.build_prompt("dQw4w9WgXcQ", mode="detail")
    assert "https://www.youtube.com/watch?v=dQw4w9WgXcQ" in p
    assert "VIDEO_NOT_ACCESSIBLE" in p
    assert "Never invent a timestamp" in p
    assert "Chronological breakdown" in p
    assert "What is NOT in the video" in p


def test_modes_differ():
    brief = yt.build_prompt("dQw4w9WgXcQ", mode="brief")
    chapters = yt.build_prompt("dQw4w9WgXcQ", mode="chapters")
    claims = yt.build_prompt("dQw4w9WgXcQ", mode="claims")
    assert "Takeaways" in brief and "Chronological breakdown" not in brief
    assert "Chapters" in chapters
    assert "Claims" in claims
    for p in (brief, chapters, claims):
        assert "VIDEO_NOT_ACCESSIBLE" in p


def test_ask_prompt():
    p = yt.build_prompt("dQw4w9WgXcQ", mode="detail", question="What about X?")
    assert "Question: What about X?" in p
    assert "does not address the question" in p


def test_parse_sections_and_sidecar():
    md = "# Title\n\n## TL;DR\nhello 12:34\n\n## Chapters\nworld 01:02:03\n"
    secs = yt.parse_sections(md)
    assert [s["section"] for s in secs] == ["TL;DR", "Chapters"]
    assert secs[0]["start"] == md.index("## TL;DR")
    side = yt.build_sidecar("dQw4w9WgXcQ", yt.canonical_url("dQw4w9WgXcQ"),
                            "detail", "pro", md, 12.3)
    assert side["title"] == "Title"
    assert side["timestamps"] == 2
    assert side["words"] == len(md.split())


def test_cache_paths_keep_modes_distinct():
    # Regression: Path.with_suffix would collapse <id>.detail.md to <id>.md.
    yt.OUTPUT_DIR = Path("/tmp/ytcache")
    detail_md, detail_json = yt.cache_paths("dQw4w9WgXcQ", "detail")
    brief_md, _ = yt.cache_paths("dQw4w9WgXcQ", "brief")
    assert str(detail_md).endswith("dQw4w9WgXcQ.detail.md")
    assert str(detail_json).endswith("dQw4w9WgXcQ.detail.json")
    assert detail_md != brief_md


def test_fwd_alive_false_on_closed_port():
    assert yt._fwd_alive(port=59999) is False


def test_fwd_alive_true_on_dummy_listener():
    import socket, threading
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.listen(1)
    try:
        assert yt._fwd_alive(port=port) is True
    finally:
        srv.close()


def test_needs_forwarder_env():
    import os
    saved = {k: os.environ.get(k) for k in
             ("YT_GEM_NO_FWD", "YT_GEM_USE_FWD", "https_proxy", "HTTPS_PROXY")}
    try:
        os.environ["YT_GEM_NO_FWD"] = "1"
        os.environ["https_proxy"] = "http://hatch-egress-proxy:3128"
        assert yt._needs_forwarder() is False
        del os.environ["YT_GEM_NO_FWD"]
        assert yt._needs_forwarder() is True
        os.environ["https_proxy"] = "http://other-proxy:3128"
        os.environ.pop("YT_GEM_USE_FWD", None)
        assert yt._needs_forwarder() is False
        os.environ["YT_GEM_USE_FWD"] = "1"
        assert yt._needs_forwarder() is True
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_fwd_script_exists():
    assert yt._fwd_script_path() is not None
    assert yt._fwd_script_path().name == "proxy_fwd.py"


def test_main_dry_run_and_bad_url(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("YT_GEM_OUTPUT_DIR", str(tmp_path))
    # Re-point module output dir (set at import time from env).
    yt.OUTPUT_DIR = tmp_path
    rc = yt.main(["https://youtu.be/dQw4w9WgXcQ", "--dry-run"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["video_id"] == "dQw4w9WgXcQ" and out["dry_run"]
    rc = yt.main(["https://example.com/nope", "--dry-run"])
    assert rc == 2
    out = json.loads(capsys.readouterr().out)
    assert out["err"] == "BAD_URL"

def test_vtt_to_text_dedupes_and_timestamps():
    vtt = """WEBVTT
Kind: captions

00:00:01.000 --> 00:00:03.000
Hello world

00:00:02.000 --> 00:00:04.000
Hello world

00:00:04.500 --> 00:00:06.000
<b>Second</b> line &amp; more
"""
    out = yt._vtt_to_text(vtt)
    assert out == "[00:01] Hello world\n[00:04] Second line & more"

def test_transcript_prompt_drops_sentinel():
    p = yt._transcript_prompt("dQw4w9WgXcQ", "detail", None, "[00:01] hello")
    assert "VIDEO_NOT_ACCESSIBLE" not in p.split("CAPTION TRANSCRIPT")[0]
    assert "CAPTION TRANSCRIPT" in p
    assert "[00:01] hello" in p

if __name__ == "__main__":
    # Minimal runner without pytest.
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            if "capsys" in fn.__code__.co_varnames:
                print(f"SKIP (needs pytest): {fn.__name__}")
                continue
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    sys.exit(1 if failed else 0)
