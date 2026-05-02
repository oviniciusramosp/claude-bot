#!/usr/bin/env python3
"""Shell-callable pipeline trigger (Pipeline v2).

Posts to the bot's HTTP server (claude-bot-web.py / the bot's webhook
listener) to trigger a pipeline by name, optionally with runtime overrides
that match the v2 ``accepts_overrides`` schema on each step.

Usage:
    scripts/run_pipeline.py <pipeline-name>
    scripts/run_pipeline.py <pipeline-name> --overrides '{"step": {"attr": "val"}}'
    scripts/run_pipeline.py <pipeline-name> --time-slot manual-cron --overrides '...'

Exits:
    0 — pipeline accepted (HTTP 200)
    1 — invalid args / parse error
    2 — pipeline not found (HTTP 404)
    3 — validation error (HTTP 400 — invalid overrides, etc.)
    4 — bot HTTP server not reachable
    5 — other HTTP error

The script depends ONLY on the Python stdlib so it can run in cron, agent
shell tools, or any environment where the bot is locally installed.

Reads ``CLAUDE_BOT_WEB_URL`` from env (default ``http://127.0.0.1:8765``)
and ``CLAUDE_BOT_WEB_TOKEN`` if set (passed as Authorization header).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Trigger a claude-bot pipeline via the local HTTP API",
        epilog=(
            "Examples:\n"
            "  scripts/run_pipeline.py crypto-ta-analise\n"
            "  scripts/run_pipeline.py crypto-ta-analise --overrides '{\"analyst\": {\"focus_asset\": \"ETH\"}}'\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("name", help="Pipeline (or routine) file name without .md")
    parser.add_argument(
        "--overrides", default=None,
        help="JSON object {step_id: {attr: value}} — Pipeline v2 only",
    )
    parser.add_argument(
        "--time-slot", default="manual-shell",
        help="Identifier for this run in routines-state JSON (default: manual-shell)",
    )
    parser.add_argument(
        "--url", default=os.environ.get("CLAUDE_BOT_WEB_URL", "http://127.0.0.1:8765"),
        help="Bot HTTP base URL (env: CLAUDE_BOT_WEB_URL, default: http://127.0.0.1:8765)",
    )
    args = parser.parse_args()

    payload = {"name": args.name, "time_slot": args.time_slot}
    if args.overrides:
        try:
            overrides_obj = json.loads(args.overrides)
        except json.JSONDecodeError as exc:
            print(f"ERROR: --overrides JSON parse failed: {exc}", file=sys.stderr)
            return 1
        if not isinstance(overrides_obj, dict):
            print("ERROR: --overrides must be a JSON object {step_id: {attr: val}}", file=sys.stderr)
            return 1
        payload["overrides"] = overrides_obj

    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    token = os.environ.get("CLAUDE_BOT_WEB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = args.url.rstrip("/") + "/routine/run"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            response = json.loads(resp.read().decode("utf-8"))
            print(json.dumps(response, indent=2))
            return 0
    except urllib.error.HTTPError as exc:
        try:
            err_body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            err_body = {"raw": "<unparseable>"}
        print(f"HTTP {exc.code}: {json.dumps(err_body, indent=2)}", file=sys.stderr)
        if exc.code == 404:
            return 2
        if exc.code == 400:
            return 3
        return 5
    except urllib.error.URLError as exc:
        print(f"ERROR: bot HTTP server not reachable at {url}: {exc.reason}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
