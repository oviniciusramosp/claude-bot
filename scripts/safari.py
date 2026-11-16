#!/usr/bin/env python3
"""Drive the user's Safari (with its logins) from scripts and agents.

Replaces PinchTab. Safari already holds the owner's sessions (X, Threads,
banks…), and on macOS it can be scripted with AppleScript once two switches
are on — both one-time, by the owner:

  1. Safari ▸ Settings ▸ Advanced ▸ "Show features for web developers", then
     Develop ▸ "Allow JavaScript from Apple Events".
  2. The first run asks to let the calling app (Terminal / python / the bot)
     control Safari — answer Allow (System Settings ▸ Privacy & Security ▸
     Automation).

Every page is opened in its OWN Safari window and only that window is closed
afterwards, so the owner's tabs are never touched.

Library use (stdlib only):

    sys.path.insert(0, "<repo>/scripts"); import safari
    with safari.open_page("https://x.com/i/lists/123", settle=4) as page:
        posts = page.js("Array.from(document.querySelectorAll('article')).map(a => a.innerText)")
        page.scroll(passes=3, pause=2)
        text = page.text()

CLI:

    python3 scripts/safari.py check
    python3 scripts/safari.py text <url> [--settle 3]
    python3 scripts/safari.py js <url> "<expression>" [--settle 3]
    python3 scripts/safari.py html <url>

Errors raise SafariError with a plain message (CLI: exit 1, message on stderr).
"""
from __future__ import annotations

import argparse
import fcntl
import os
import json
import subprocess
import sys
import time
from typing import Any, Optional

OSASCRIPT = "/usr/bin/osascript"
LOAD_TIMEOUT = 30.0      # seconds to wait for document.readyState == complete
DEFAULT_SETTLE = 2.0     # extra seconds after load for client-side rendering
JS_TIMEOUT = 60          # per osascript call
LOCK_FILE = os.path.expanduser("~/.claude-bot/safari.lock")
LOCK_WAIT = 120.0        # seconds to wait for another script's page to finish

_HOW_TO_ENABLE = (
    "Safari is not accepting JavaScript from scripts. Turn on Safari ▸ Develop ▸ "
    "\"Allow JavaScript from Apple Events\" (Develop menu: Safari ▸ Settings ▸ "
    "Advanced ▸ \"Show features for web developers\") and allow this app under "
    "System Settings ▸ Privacy & Security ▸ Automation ▸ Safari."
)


class SafariError(RuntimeError):
    pass


def _osa(lines: list, *args: str, timeout: float = JS_TIMEOUT) -> str:
    """Run an AppleScript given as lines, passing ``args`` as argv (no quoting
    problems: the script never embeds the values)."""
    cmd = [OSASCRIPT]
    for line in lines:
        cmd += ["-e", line]
    cmd += list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise SafariError(f"Safari did not answer within {timeout:.0f}s")
    except FileNotFoundError:
        raise SafariError("osascript not found — this only works on macOS")
    if r.returncode != 0:
        err = (r.stderr or "").strip()
        low = err.lower()
        if "allow javascript from apple events" in low or "-1743" in low or "not allowed" in low:
            raise SafariError(f"{_HOW_TO_ENABLE} ({err[:160]})")
        raise SafariError(err[:300] or f"osascript exit {r.returncode}")
    return r.stdout.rstrip("\n")


def _window_ids() -> set:
    # Visible windows only: after a close Safari keeps one invisible, tab-less
    # placeholder window, which is not ours and not a leak.
    out = _osa(['tell application "Safari" to get id of every window whose visible is true'],
               timeout=15)
    ids = set()
    for part in out.replace(",", " ").split():
        try:
            ids.add(int(part))
        except ValueError:
            pass
    return ids


def _close_window(window_id: int) -> None:
    _osa([
        "on run argv",
        'tell application "Safari"',
        "set ws to (every window whose id is ((item 1 of argv) as integer))",
        "repeat with w in ws",
        "close w",
        "end repeat",
        "end tell",
        "end run",
    ], str(window_id), timeout=15)


class _MachineLock:
    """One page at a time on this Mac, across every script and agent: parallel
    steps queue instead of piling windows up."""

    def __init__(self) -> None:
        self.fh = None

    def acquire(self, wait: float = LOCK_WAIT) -> None:
        os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)
        self.fh = open(LOCK_FILE, "w")
        deadline = time.time() + wait
        while True:
            try:
                fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                if time.time() >= deadline:
                    self.fh.close()
                    self.fh = None
                    raise SafariError(f"another script is using Safari for more than {wait:.0f}s")
                time.sleep(0.5)

    def release(self) -> None:
        if self.fh:
            try:
                fcntl.flock(self.fh, fcntl.LOCK_UN)
            finally:
                self.fh.close()
                self.fh = None


class SafariPage:
    """One page in its own Safari window, addressed by the window's id."""

    def __init__(self, window_id: int, url: str, lock: Optional[_MachineLock] = None):
        self.window_id = window_id
        self.url = url
        self.closed = False
        self._lock = lock

    # -- JavaScript ---------------------------------------------------------
    def raw_js(self, source: str) -> str:
        """Run ``source`` in the page; returns AppleScript's text of the result."""
        if self.closed:
            raise SafariError("page already closed")
        return _osa([
            "on run argv",
            'tell application "Safari" to do JavaScript (item 1 of argv) '
            "in current tab of (first window whose id is ((item 2 of argv) as integer))",
            "end run",
        ], source, str(self.window_id))

    def js(self, expression: str) -> Any:
        """Evaluate a JS *expression* and return it decoded from JSON
        (strings, numbers, lists, dicts). For a statement block, wrap it:
        ``page.js("(() => { ...; return x; })()")``."""
        wrapped = (
            "(function(){try{return JSON.stringify({ok:true,v:(" + expression + ")});}"
            "catch(e){return JSON.stringify({ok:false,e:String(e)});}})()"
        )
        out = self.raw_js(wrapped)
        try:
            data = json.loads(out) if out else {"ok": True, "v": None}
        except ValueError:
            raise SafariError(f"unexpected JavaScript result: {out[:200]}")
        if not data.get("ok"):
            raise SafariError(f"JavaScript error: {data.get('e')}")
        return data.get("v")

    def js_async(self, expression: str, timeout: float = 30.0, poll: float = 0.5) -> Any:
        """Evaluate an expression that returns a Promise; wait for it."""
        key = f"__safari_py_{int(time.time() * 1000)}"
        self.raw_js(
            f"window['{key}']=null;Promise.resolve(({expression}))"
            f".then(v=>{{window['{key}']=JSON.stringify({{ok:true,v:v}});}})"
            f".catch(e=>{{window['{key}']=JSON.stringify({{ok:false,e:String(e)}});}});'started'"
        )
        deadline = time.time() + timeout
        while time.time() < deadline:
            out = self.raw_js(f"window['{key}']||''")
            if out:
                data = json.loads(out)
                if not data.get("ok"):
                    raise SafariError(f"JavaScript error: {data.get('e')}")
                return data.get("v")
            time.sleep(poll)
        raise SafariError(f"JavaScript promise did not settle within {timeout:.0f}s")

    # -- helpers ------------------------------------------------------------
    def wait_loaded(self, timeout: float = LOAD_TIMEOUT) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.raw_js("document.readyState") == "complete":
                    return
            except SafariError as exc:
                if "allow javascript" in str(exc).lower() or "Automation" in str(exc):
                    raise
            time.sleep(0.5)
        raise SafariError(f"page did not finish loading within {timeout:.0f}s: {self.url}")

    def text(self) -> str:
        return self.js("document.body ? document.body.innerText : ''") or ""

    def html(self) -> str:
        return self.js("document.documentElement.outerHTML") or ""

    def current_url(self) -> str:
        return self.js("location.href") or ""

    def scroll(self, passes: int = 3, pause: float = 2.0) -> None:
        """Scroll to the bottom ``passes`` times (loads infinite feeds)."""
        for _ in range(max(0, passes)):
            self.raw_js("window.scrollTo(0, document.body.scrollHeight); 'ok'")
            time.sleep(pause)

    def inject_file(self, path: str) -> None:
        """Run a local .js file in the page (e.g. a reader script)."""
        with open(path, encoding="utf-8") as fh:
            self.raw_js(fh.read() + "\n;'ok'")

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            _close_window(self.window_id)
            for _ in range(12):      # closing is asynchronous in Safari
                if self.window_id not in _window_ids():
                    break
                time.sleep(0.25)
            else:
                print(f"WARN: Safari window {self.window_id} is still open after close",
                      file=sys.stderr)
        except SafariError as exc:
            print(f"WARN: could not close Safari window {self.window_id}: {exc}", file=sys.stderr)
        finally:
            if self._lock:
                self._lock.release()
                self._lock = None

    def __enter__(self) -> "SafariPage":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def open_page(url: str, settle: float = DEFAULT_SETTLE,
              load_timeout: float = LOAD_TIMEOUT) -> SafariPage:
    """Open ``url`` in a new Safari window, wait for it to load, then
    ``settle`` more seconds for client-side rendering."""
    lock = _MachineLock()
    lock.acquire()
    try:
        before = _window_ids()
        _osa([
            "on run argv",
            'tell application "Safari" to make new document with properties {URL:(item 1 of argv)}',
            "end run",
        ], url, timeout=30)
        new = set()
        for _ in range(20):          # the window can take a moment to register
            new = _window_ids() - before
            if new:
                break
            time.sleep(0.25)
        if len(new) != 1:
            # Never guess which window is ours: close every window that
            # appeared during this call and stop.
            for wid in new:
                _close_window(wid)
            raise SafariError(f"expected 1 new Safari window, saw {len(new)} — none kept open")
    except Exception:
        lock.release()
        raise
    page = SafariPage(new.pop(), url, lock)
    try:
        page.wait_loaded(load_timeout)
        if settle > 0:
            time.sleep(settle)
    except Exception:
        page.close()
        raise
    return page


def check() -> str:
    """Raise SafariError unless Safari can run JavaScript for us."""
    with open_page("about:blank", settle=0, load_timeout=15) as page:
        if page.js("1+1") != 2:
            raise SafariError("Safari answered, but JavaScript returned something unexpected")
    return "ok"


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Use the owner's Safari (with its logins).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="verify Safari accepts JavaScript from scripts")
    for name in ("text", "html"):
        p = sub.add_parser(name, help=f"print the page {name}")
        p.add_argument("url")
        p.add_argument("--settle", type=float, default=DEFAULT_SETTLE)
        p.add_argument("--scroll", type=int, default=0, help="scroll to bottom N times first")
    p = sub.add_parser("js", help="print the JSON result of a JS expression")
    p.add_argument("url")
    p.add_argument("expression")
    p.add_argument("--settle", type=float, default=DEFAULT_SETTLE)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "check":
            print(check())
            return 0
        with open_page(args.url, settle=args.settle) as page:
            if args.cmd == "js":
                print(json.dumps(page.js(args.expression), ensure_ascii=False, indent=2))
            else:
                if args.scroll:
                    page.scroll(args.scroll)
                print(page.text() if args.cmd == "text" else page.html())
        return 0
    except SafariError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
