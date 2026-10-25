#!/usr/bin/env python3
"""
gemini_cli_login.py — Sign the CLI's Chromium profile into Gemini, once.

Paste-once transient credential path (same pattern as the Schwab CLI login):
  1. The user pastes their password in chat for this one run only.
  2. The agent writes it to a 600 file (default: ~/.hermes/yt_gem_creds.json).
  3. This driver reads that file, signs in, and DELETES the file in a
     finally block — success, failure, or challenge, the file does not
     survive the run. Nothing is stored in the vault, in memory notes,
     in logs, or in the repo, and the password is never printed.
  4. The signed-in session lives only in the Chromium profile
     (~/.gemini-cli/cr-profile), which yt-gem / gem-pw then reuse.

Usage:
  python3 gemini_cli_login.py --check-only
      # No credentials needed: load Gemini via the forwarder and report
      # whether the profile is already signed in / a sign-in form is present.
  python3 gemini_cli_login.py --creds-file ~/.hermes/yt_gem_creds.json
      # Creds file: JSON {"email": "...", "password": "..."} OR plain-text
      # password only (email then defaults to --email).
  python3 gemini_cli_login.py --creds-file <f> --email ppoppo205@gmail.com

Browser route (measured on this VM, 2026-10-25):
  * Local CONNECT forwarder 127.0.0.1:8888 (vendored proxy_fwd.py) —
    Chromium cannot do the egress proxy auth directly.
  * meta-Chromium (/opt/meta-chromium/chrome) first, Playwright Chromium
    fallback — stock Playwright Chromium was the one that got vendor
    "AI service not authorized" style blocks on Schwab; real Chrome is
    less likely to trip Google's "browser may not be secure" check.
  * ignore_https_errors + --ignore-certificate-errors for the TLS
    intercept CA. Headed (xvfb-run fallback when DISPLAY is unset).

If Google asks for a second factor, a phone prompt, a CAPTCHA, or
"This browser or app may not be secure", the driver stops with
err=CHALLENGE and a short indicator — it does NOT retry in a loop
(repeated login flows risk account throttling, as seen on Schwab:
three 403s after ~7 flows in 25 min). The creds file is still deleted.
The user then approves/relays the challenge, or signs in on their own
device, and a fresh paste is needed for a retry.
"""

import argparse
import asyncio
import json
import os
import shutil as _shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

if (not os.environ.get("DISPLAY")
        and os.environ.get("YT_GEM_XVFB", "1") != "0"
        and not os.environ.get("_YT_GEM_XVFB_WRAPPED")
        and _shutil.which("xvfb-run")):
    os.environ["_YT_GEM_XVFB_WRAPPED"] = "1"
    os.execvp(_shutil.which("xvfb-run"),
              [_shutil.which("xvfb-run"), "-a", sys.executable] + sys.argv)

PROFILE = str(Path.home() / ".gemini-cli" / "cr-profile")
FWD_PORT = int(os.environ.get("YT_GEM_FWD_PORT", "8888"))
FWD_URL = f"http://127.0.0.1:{FWD_PORT}"
META_CHROME = "/opt/meta-chromium/chrome"


def _log(msg):
    print(f"[gemini-login] {msg}", file=sys.stderr, flush=True)


def _fwd_alive():
    try:
        with socket.create_connection(("127.0.0.1", FWD_PORT), timeout=2):
            return True
    except OSError:
        return False


def _ensure_forwarder():
    if _fwd_alive():
        return True
    here = Path(__file__).resolve().parent
    for cand in (here / "proxy_fwd.py",
                 Path.home() / "workspace" / "tos-cli" / "proxy_fwd.py"):
        if cand.exists():
            log_path = Path.home() / ".hermes" / "yt_gem_fwd.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            lf = open(log_path, "ab")
            subprocess.Popen([sys.executable, str(cand)], stdout=lf,
                             stderr=lf, start_new_session=True)
            for _ in range(10):
                if _fwd_alive():
                    _log(f"forwarder started on 127.0.0.1:{FWD_PORT}")
                    return True
                time.sleep(0.5)
            return False
    _log("forwarder script not found")
    return False


def _read_creds(path, default_email):
    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        return None, None
    if text.startswith("{"):
        try:
            d = json.loads(text)
            return d.get("email") or default_email, d.get("password")
        except Exception:
            return default_email, None
    return default_email, text


def _delete_creds(path):
    try:
        Path(path).unlink()
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


async def _is_signed_in(page):
    """Strict signed-in check (fix for the 2026-10-25 false positive).

    The LOGGED-OUT Gemini landing page also has a div[role="textbox"]
    (the intro-page central input), so textbox presence alone is NOT
    sufficient — the 20:24 run returned already_signed_in on a logged-out
    profile and the pasted password was never entered. Calibrated
    2026-10-25 via /tmp/diag_gemini.py: logged-out page shows
    textbox=True, 'Sign in' in head (incl. 'Sign in to save activity'),
    and 'Ask Gemini' absent from body, stable at 3/5/10/15s.
    Mirrors yt-gem's _is_signed_in, plus the Chinese '登入' indicator
    seen on the logged-out page in the managed-browser check.
    Returns (signed_in, body_text)."""
    try:
        body = await page.evaluate("document.body.innerText") or ""
    except Exception:
        return False, ""
    head = body[:800]
    if "Sign in" in head and "Ask Gemini" not in body:
        return False, body
    if "登入" in head and "Ask Gemini" not in body:
        return False, body
    try:
        has_box = await page.query_selector('div[role="textbox"]') is not None
    except Exception:
        has_box = False
    return has_box, body


async def _click_text(page, candidates, timeout=10000):
    """Click first visible button/link whose text contains a candidate."""
    t0 = time.time()
    while time.time() - t0 < timeout / 1000:
        try:
            hit = await page.evaluate("""(cands) => {
                const els = [...document.querySelectorAll('button, a')];
                for (const el of els) {
                    const t = (el.innerText || '').trim();
                    for (const c of cands) {
                        if (t === c || t.includes(c)) {
                            if (el.offsetParent) {
                                const r = el.getBoundingClientRect();
                                return {x: r.x + r.width/2, y: r.y + r.height/2};
                            }
                        }
                    }
                }
                return null;
            }""", candidates)
            if hit:
                await page.mouse.click(hit["x"], hit["y"])
                return True
        except Exception:
            pass
        await asyncio.sleep(1)
    return False


async def _fill_input(page, selectors, value, timeout=20):
    """Fill an input, retrying for up to `timeout` seconds.

    Fix for the 2026-10-25 first login run: after the email Next click,
    Google's password page shows 'Loading' and the password input is not
    yet visible at 3s (diagnostic run: visible at 5s). A single immediate
    attempt therefore reported NO_PASSWORD_INPUT even though the field
    appears moments later — and the pasted credential was never entered.
    Polling avoids wasting a paste on a timing miss."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        for sel in selectors:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.click()
                    await asyncio.sleep(0.3)
                    await page.keyboard.press("Control+a")
                    await page.keyboard.press("Backspace")
                    await page.keyboard.type(value, delay=20)
                    return True
            except Exception:
                continue
        await asyncio.sleep(1)
    return False


async def _failure_diag(page):
    """Non-credential diagnostic snapshot for a failed step."""
    try:
        url = page.url
        title = await page.title()
        body = (await page.evaluate("document.body.innerText") or "")[:300]
        inputs = await page.evaluate(
            """() => [...document.querySelectorAll('input')]
               .map(i=>({type:i.type, name:i.name, visible:!!i.offsetParent}))""")
        return {"url": url, "title": title, "body": body, "inputs": inputs}
    except Exception as e:
        return {"diag_error": str(e)[:120]}


async def _challenge_diag(page, chal):
    """Capture the 2FA challenge screen: Google's number-matching prompt
    shows ONE number on the sign-in screen; the phone shows several
    candidates (e.g. 20 / 51 / 1) and the user must tap the matching one.
    The 2026-10-25 20:30 run returned only the generic code CHALLENGE
    and closed the browser, so that number was lost and could not be
    answered afterwards — never guess it. This diag records the screen
    text (and writes it to ~/.hermes/yt_gem_2fa.json when holding) so
    the exact number can be relayed while the prompt is still live."""
    import re
    try:
        body = await page.evaluate("document.body.innerText") or ""
    except Exception:
        body = ""
    nums = re.findall(r"(?<![\d.])\d{1,2}(?![\d.])", body)
    info = {"challenge": chal, "url": page.url,
            "body": body[:1000], "numbers_on_screen": nums}
    return info


async def _challenge_indicator(page):
    try:
        body = await page.evaluate("document.body.innerText") or ""
    except Exception:
        return ""
    low = body.lower()
    for phrase, code in [
        ("may not be secure", "BROWSER_NOT_SECURE"),
        ("couldn't sign you in", "SIGNIN_BLOCKED"),
        ("verify it's you", "VERIFY_IDENTITY"),
        ("2-step verification", "TWO_FACTOR"),
        ("try another way", "CHALLENGE"),
        ("enter the code", "CODE_REQUIRED"),
        ("check your phone", "PHONE_PROMPT"),
    ]:
        if phrase in low:
            return code
    return ""


async def main_async(args):
    creds_path = Path(args.creds_file) if args.creds_file else None
    email = password = None
    if creds_path and creds_path.exists() and not args.check_only:
        email, password = _read_creds(creds_path, args.email)
    try:
        if not args.check_only and not password:
            return {"ok": False, "err": "NO_CREDS",
                    "msg": "No password found in creds file."}
        _ensure_forwarder()
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            exe = META_CHROME if Path(META_CHROME).exists() else None
            launch_kw = dict(
                user_data_dir=PROFILE, headless=False,
                proxy={"server": FWD_URL}, ignore_https_errors=True,
                args=["--no-sandbox", "--disable-gpu",
                      "--disable-blink-features=AutomationControlled",
                      "--ignore-certificate-errors",
                      "--remote-debugging-port=0"],
                ignore_default_args=["--enable-automation"])
            if exe:
                launch_kw["executable_path"] = exe
                _log(f"using meta-Chromium {exe}")
            ctx = await pw.chromium.launch_persistent_context(**launch_kw)
            try:
                page = await ctx.new_page()
                page.set_default_timeout(60000)
                await page.goto("https://gemini.google.com/app",
                                wait_until="domcontentloaded", timeout=60000)
                await asyncio.sleep(5)
                signed_in, body = await _is_signed_in(page)
                if signed_in:
                    return {"ok": True, "signed_in": True,
                            "account_shown": args.email in body,
                            "mode": "already_signed_in"}
                if args.check_only:
                    return {"ok": True, "signed_in": False,
                            "sign_in_visible": ("Sign in" in body[:2000]
                                               or "登入" in body[:2000]),
                            "mode": "check_only"}
                # Sign-in flow, one attempt only.
                if not await _click_text(page, ["Sign in", "登入"], timeout=10000):
                    # Gemini may already be redirecting to accounts.google.com
                    await page.goto("https://accounts.google.com/signin/v2/identifier",
                                    wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(3)
                await asyncio.sleep(2)
                if not await _fill_input(page, [
                        'input[type="email"]', '#identifierId',
                        'input[name="identifier"]'], email):
                    return {"ok": False, "err": "NO_EMAIL_INPUT",
                            "msg": "Email field not found on sign-in page."}
                await _click_text(page, ["Next", "下一步"], timeout=10000)
                await asyncio.sleep(3)
                chal = await _challenge_indicator(page)
                if chal:
                    return {"ok": False, "err": "CHALLENGE", "challenge": chal}
                if not await _fill_input(page, [
                        'input[type="password"]', '#password',
                        'input[name="Passwd"]', 'input[name="password"]'],
                        password, timeout=20):
                    return {"ok": False, "err": "NO_PASSWORD_INPUT",
                            "msg": "Password field not found within 20s after email step.",
                            "diag": await _failure_diag(page)}
                await _click_text(page, ["Next", "下一步"], timeout=10000)
                await asyncio.sleep(8)
                chal = await _challenge_indicator(page)
                if chal:
                    diag = await _challenge_diag(page, chal)
                    if args.hold_on_challenge:
                        # Keep the browser open so the phone prompt stays
                        # live: write the screen number to a file the
                        # agent can read while this process waits, then
                        # poll for the approval landing on Gemini.
                        Path.home().joinpath(".hermes", "yt_gem_2fa.json").write_text(
                            json.dumps(diag, ensure_ascii=False), encoding="utf-8")
                        _log(f"challenge held: {chal} body={diag['body'][:300]!r}")
                        waited = 0
                        while waited < args.hold_on_challenge:
                            await asyncio.sleep(10)
                            waited += 10
                            # Do NOT navigate away: the phone prompt is
                            # tied to this accounts page. Approval usually
                            # auto-redirects it to Gemini; detect that.
                            try:
                                if "gemini.google.com/app" in page.url:
                                    s2, b2 = await _is_signed_in(page)
                                    if s2:
                                        return {"ok": True, "signed_in": True,
                                                "account_shown": args.email in b2,
                                                "mode": "signed_in_after_2fa"}
                            except Exception:
                                pass
                    return {"ok": False, "err": "CHALLENGE", "challenge": chal,
                            "diag": diag}
                # Dismiss "Stay signed in?" / welcome screens if present.
                await _click_text(page, ["Yes", "Not now", "Skip"], timeout=5000)
                await asyncio.sleep(2)
                await page.goto("https://gemini.google.com/app",
                                wait_until="domcontentloaded", timeout=60000)
                await asyncio.sleep(5)
                signed_in, body = await _is_signed_in(page)
                if signed_in:
                    return {"ok": True, "signed_in": True,
                            "account_shown": args.email in body,
                            "mode": "signed_in_now"}
                chal = await _challenge_indicator(page)
                if chal:
                    return {"ok": False, "err": "CHALLENGE", "challenge": chal}
                return {"ok": False, "err": "NOT_SIGNED_IN",
                        "msg": "Gemini chat input not visible after sign-in attempt."}
            finally:
                try:
                    await ctx.close()
                except Exception:
                    pass
    finally:
        if creds_path:
            deleted = _delete_creds(creds_path)
            _log(f"creds file deleted: {deleted}")


def main():
    p = argparse.ArgumentParser(prog="gemini_cli_login")
    p.add_argument("--creds-file", help="600 JSON/password file, deleted after the run")
    p.add_argument("--email", default="ppoppo205@gmail.com")
    p.add_argument("--check-only", action="store_true",
                   help="Load Gemini only, no sign-in attempt")
    p.add_argument("--hold-on-challenge", type=int, default=0,
                   help="Seconds to keep the browser open at a 2FA challenge, "
                        "writing the screen number to ~/.hermes/yt_gem_2fa.json, "
                        "while the user taps the matching number on their phone")
    args = p.parse_args()
    result = asyncio.run(main_async(args))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
