#!/usr/bin/env python3
"""OSS Radar v2 -- Step: collect-github

Pipeline: oss-radar-v2.md (pipeline_version: 2)
Step-id: collect-github
Replaces: vault/main/Routines/oss-radar/steps/collect.md (v1 LLM collector)

What it does (v1 collect.md collapsed into one deterministic script):
  1. OpenClaw org -- list repos (sorted by pushed_at), fetch recent commits
     and releases for each repo pushed in the last 48h.
  2. NousResearch/hermes-agent -- fetch recent commits, releases, and open
     PRs.
  3. Writes structured markdown to $PIPELINE_STEP_OUTPUT_FILE with sections
     for the LLM analyze step to read.

Reads env:
  - $PIPELINE_STEP_OUTPUT_FILE -- destination markdown path (mandatory)
  - $GITHUB_TOKEN              -- optional auth (raises rate limit; required
                                  for private repos). Anonymous works for
                                  public repos at 60 req/h.
  - $GITHUB_API_URL            -- optional override (default api.github.com)

Stdout's last line is the JSON status report (Pipeline v2 contract).
Best-effort: per-source try/except. Returns `ready` even when some sources
failed (the LLM analyze step is robust to missing data). Returns `failed`
only when every source failed.

Stdlib only. Tries `gh api` first (uses host auth), then raw HTTPS with
GITHUB_TOKEN, then anonymous.
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

USER_AGENT = "Mozilla/5.0 (compatible; oss-radar/2.0)"
HTTP_TIMEOUT = 15
GH_TIMEOUT = 20

DEFAULT_API_URL = "https://api.github.com"
LOOKBACK_HOURS = 48           # window for commits/releases (matches v1)
OPENCLAW_ORG = "openclaw"     # discovered dynamically via /orgs/<org>/repos
OPENCLAW_REPOS_LIMIT = 10     # mirrors v1 prompt (per_page=10)
PER_REPO_COMMITS = 20         # mirrors v1 prompt (per_page=20)
RELEASES_PER_REPO = 3         # mirrors v1 prompt (per_page=3)
HERMES_REPO = "NousResearch/hermes-agent"
HERMES_PRS_LIMIT = 10         # mirrors v1 prompt (per_page=10)

UTC = datetime.timezone.utc


# ---------------------------------------------------------------------------
# Status report (Pipeline v2 contract)
# ---------------------------------------------------------------------------

def emit_status(status: str, output_file: Optional[str], reason: str = "") -> None:
    print(json.dumps({"status": status, "output_file": output_file, "reason": reason}))
    sys.exit(0 if status in ("ready", "skipped") else 1)


def fail(reason: str, output: Optional[Path] = None) -> None:
    print(f"ERROR: {reason}", file=sys.stderr)
    emit_status("failed", str(output) if output else None, reason)


# ---------------------------------------------------------------------------
# HTTP / GitHub fetch (gh -> token -> anonymous)
# ---------------------------------------------------------------------------

def _gh_api_call(endpoint: str) -> Tuple[bool, Any]:
    """Call `gh api <endpoint>` and return (ok, parsed_json_or_error_str)."""
    if not shutil.which("gh"):
        return False, "gh CLI not in PATH"
    cmd = ["gh", "api", endpoint]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=GH_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return False, f"gh api timeout after {GH_TIMEOUT}s"
    except Exception as exc:  # noqa: BLE001
        return False, f"gh api exception: {type(exc).__name__}: {exc}"

    if result.returncode != 0:
        err = (result.stderr or "").strip()[:200] or f"exit code {result.returncode}"
        return False, f"gh api failed: {err}"
    try:
        return True, json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return False, f"gh api JSON decode failed: {exc}"


def _http_get_json(url: str, headers: Optional[Dict[str, str]] = None) -> Tuple[bool, Any]:
    hdrs = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            raw = resp.read()
        return True, json.loads(raw.decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")[:160]
        except Exception:  # noqa: BLE001
            pass
        return False, f"HTTP {exc.code}: {exc.reason}{(' -- ' + body) if body else ''}"
    except urllib.error.URLError as exc:
        return False, f"URLError: {exc.reason}"
    except (TimeoutError, OSError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    except json.JSONDecodeError as exc:
        return False, f"JSONDecodeError: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def github_get(endpoint: str, params: Optional[Dict[str, str]] = None) -> Tuple[bool, Any]:
    """Fetch a GitHub API endpoint. Tries gh CLI first (uses host auth), then
    raw HTTPS with GITHUB_TOKEN, then anonymous.

    `endpoint` is the path WITHOUT leading slash, e.g. `repos/foo/bar/commits`.
    `params` is a dict of query string parameters appended for the HTTP path.
    """
    qs = ""
    if params:
        qs = "?" + "&".join(f"{k}={urllib.request.quote(str(v), safe='')}" for k, v in params.items())

    # 1. Try gh first -- uses authenticated host session if available
    ok, payload = _gh_api_call(endpoint + qs)
    if ok:
        return True, payload
    gh_err = payload

    # 2. Try authenticated raw HTTPS via GITHUB_TOKEN
    base = os.environ.get("GITHUB_API_URL", "").strip() or DEFAULT_API_URL
    url = f"{base}/{endpoint}{qs}"
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        ok, payload = _http_get_json(url, headers={"Authorization": f"Bearer {token}"})
        if ok:
            return True, payload
        token_err = payload
    else:
        token_err = "GITHUB_TOKEN not set"

    # 3. Fall through to anonymous (60 req/h shared per IP)
    ok, payload = _http_get_json(url)
    if ok:
        return True, payload
    anon_err = payload
    return False, f"gh: {gh_err} | token: {token_err} | anonymous: {anon_err}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def since_iso(hours: int) -> str:
    """ISO 8601 UTC string for `now - hours`."""
    return (datetime.datetime.now(UTC) - datetime.timedelta(hours=hours))\
        .strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> Optional[datetime.datetime]:
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def first_line(text: str, limit: int = 160) -> str:
    if not text:
        return ""
    line = text.splitlines()[0].strip() if text.strip() else ""
    return line[:limit]


def short_body(text: str, limit: int = 400) -> str:
    if not text:
        return ""
    text = text.strip()
    return (text[:limit] + ("..." if len(text) > limit else ""))


# ---------------------------------------------------------------------------
# Source: list openclaw repos pushed in the last LOOKBACK_HOURS hours
# ---------------------------------------------------------------------------

def list_active_openclaw_repos() -> Tuple[bool, Any]:
    ok, payload = github_get(
        f"orgs/{OPENCLAW_ORG}/repos",
        params={"sort": "pushed", "per_page": str(OPENCLAW_REPOS_LIMIT)},
    )
    if not ok:
        return False, payload
    if not isinstance(payload, list):
        return False, f"unexpected payload (not a list): {type(payload).__name__}"

    cutoff = datetime.datetime.now(UTC) - datetime.timedelta(hours=LOOKBACK_HOURS)
    active: List[Dict[str, Any]] = []
    overview: List[Dict[str, Any]] = []
    for repo in payload:
        if not isinstance(repo, dict):
            continue
        full_name = repo.get("full_name", "")
        pushed = parse_iso(str(repo.get("pushed_at", "")))
        stars = repo.get("stargazers_count", 0)
        overview.append({
            "full_name": full_name,
            "pushed_at": str(repo.get("pushed_at", "")),
            "stars": stars,
        })
        if pushed and pushed >= cutoff:
            active.append({"full_name": full_name, "pushed_at": str(repo.get("pushed_at", ""))})
    return True, {"active": active, "overview": overview}


# ---------------------------------------------------------------------------
# Per-repo: commits / releases / pulls
# ---------------------------------------------------------------------------

def fetch_repo_commits(full_name: str, since: str) -> Tuple[bool, Any]:
    ok, payload = github_get(
        f"repos/{full_name}/commits",
        params={"since": since, "per_page": str(PER_REPO_COMMITS)},
    )
    if not ok:
        return False, payload
    if not isinstance(payload, list):
        return False, f"unexpected payload (not a list): {type(payload).__name__}"
    out: List[Dict[str, str]] = []
    for c in payload:
        if not isinstance(c, dict):
            continue
        sha = (c.get("sha", "") or "")[:7]
        commit = c.get("commit", {}) or {}
        msg = commit.get("message", "") or ""
        author_obj = commit.get("author", {}) or {}
        author = author_obj.get("name", "") or "?"
        date = author_obj.get("date", "") or ""
        out.append({
            "sha": sha,
            "title": first_line(msg, limit=200),
            "body": short_body(msg, limit=400),
            "author": author,
            "date": date,
            "url": c.get("html_url", "") or f"https://github.com/{full_name}/commit/{sha}",
        })
    return True, out


def fetch_repo_releases(full_name: str, max_age_hours: Optional[int] = None) -> Tuple[bool, Any]:
    ok, payload = github_get(
        f"repos/{full_name}/releases",
        params={"per_page": str(RELEASES_PER_REPO)},
    )
    if not ok:
        return False, payload
    if not isinstance(payload, list):
        return False, f"unexpected payload (not a list): {type(payload).__name__}"
    cutoff = None
    if max_age_hours is not None:
        cutoff = datetime.datetime.now(UTC) - datetime.timedelta(hours=max_age_hours)
    out: List[Dict[str, str]] = []
    for r in payload:
        if not isinstance(r, dict):
            continue
        published = r.get("published_at", "") or ""
        if cutoff is not None:
            pub = parse_iso(published)
            if pub is None or pub < cutoff:
                continue
        out.append({
            "tag_name": r.get("tag_name", "") or "",
            "name": r.get("name", "") or "",
            "published_at": published,
            "author": (r.get("author", {}) or {}).get("login", "") or "?",
            "body": short_body(r.get("body", ""), limit=500),
            "url": r.get("html_url", "") or "",
        })
    return True, out


def fetch_repo_open_pulls(full_name: str) -> Tuple[bool, Any]:
    ok, payload = github_get(
        f"repos/{full_name}/pulls",
        params={"state": "open", "sort": "updated", "direction": "desc",
                "per_page": str(HERMES_PRS_LIMIT)},
    )
    if not ok:
        return False, payload
    if not isinstance(payload, list):
        return False, f"unexpected payload (not a list): {type(payload).__name__}"
    out: List[Dict[str, str]] = []
    for p in payload:
        if not isinstance(p, dict):
            continue
        out.append({
            "number": p.get("number", ""),
            "title": p.get("title", "") or "",
            "author": (p.get("user", {}) or {}).get("login", "") or "?",
            "updated_at": p.get("updated_at", "") or "",
            "body": short_body(p.get("body", ""), limit=400),
            "url": p.get("html_url", "") or "",
        })
    return True, out


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def now_label() -> str:
    return datetime.datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


def section_repo_activity(full_name: str, sect_id: str,
                          commits: Tuple[bool, Any],
                          releases: Tuple[bool, Any],
                          pulls: Optional[Tuple[bool, Any]] = None) -> List[str]:
    lines: List[str] = []
    lines.append(f"## {sect_id}_activity")
    lines.append(f"repo: {full_name}")

    # commits
    lines.append("commits:")
    if commits[0]:
        items = commits[1]
        if items:
            lines.append("```json")
            lines.append(json.dumps(items, indent=2, ensure_ascii=False))
            lines.append("```")
        else:
            lines.append("(none in window)")
    else:
        lines.append(f"error: {commits[1]}")

    # releases
    lines.append("releases:")
    if releases[0]:
        items = releases[1]
        if items:
            lines.append("```json")
            lines.append(json.dumps(items, indent=2, ensure_ascii=False))
            lines.append("```")
        else:
            lines.append("(none recent)")
    else:
        lines.append(f"error: {releases[1]}")

    # pulls (only Hermes uses this section)
    if pulls is not None:
        lines.append("open_pulls:")
        if pulls[0]:
            items = pulls[1]
            if items:
                lines.append("```json")
                lines.append(json.dumps(items, indent=2, ensure_ascii=False))
                lines.append("```")
            else:
                lines.append("(none open)")
        else:
            lines.append(f"error: {pulls[1]}")

    lines.append("")
    return lines


def safe_section_id(full_name: str) -> str:
    """Sanitize a repo full_name into a markdown-section-safe id."""
    return full_name.replace("/", "_").replace("-", "_").lower()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    output_str = os.environ.get("PIPELINE_STEP_OUTPUT_FILE", "").strip()
    if not output_str:
        fail("PIPELINE_STEP_OUTPUT_FILE env var not set")
    output_path = Path(output_str)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    since = since_iso(LOOKBACK_HOURS)
    print(f"INFO: lookback={LOOKBACK_HOURS}h since={since}", file=sys.stderr)

    sources_ok: List[str] = []
    sources_failed: List[Dict[str, str]] = []
    sections: List[str] = []

    # ---- 1. OpenClaw org repo discovery ----
    print(f"INFO: listing repos under org={OPENCLAW_ORG} (top {OPENCLAW_REPOS_LIMIT})...",
          file=sys.stderr)
    ok_list, list_payload = list_active_openclaw_repos()
    overview: List[Dict[str, Any]] = []
    active_repos: List[Dict[str, Any]] = []
    if ok_list:
        sources_ok.append(f"openclaw_repos_list")
        overview = list_payload.get("overview", [])
        active_repos = list_payload.get("active", [])
        print(f"INFO: openclaw -> {len(overview)} total, {len(active_repos)} active in window",
              file=sys.stderr)
    else:
        sources_failed.append({"source": "openclaw_repos_list", "error": str(list_payload)[:200]})
        print(f"WARN: openclaw repos list failed: {list_payload}", file=sys.stderr)

    # ---- 2. Per-active-repo: commits + releases ----
    for repo in active_repos:
        full_name = repo.get("full_name", "")
        if not full_name:
            continue
        sect_id = safe_section_id(full_name)
        commits = fetch_repo_commits(full_name, since)
        releases = fetch_repo_releases(full_name)
        # log + status tracking
        if commits[0]:
            sources_ok.append(f"{sect_id}_commits")
        else:
            sources_failed.append({"source": f"{sect_id}_commits", "error": str(commits[1])[:200]})
            print(f"WARN: {full_name} commits failed: {commits[1]}", file=sys.stderr)
        if releases[0]:
            sources_ok.append(f"{sect_id}_releases")
        else:
            sources_failed.append({"source": f"{sect_id}_releases", "error": str(releases[1])[:200]})
            print(f"WARN: {full_name} releases failed: {releases[1]}", file=sys.stderr)
        sections.extend(section_repo_activity(full_name, sect_id, commits, releases))

    # ---- 3. Hermes Agent ----
    print(f"INFO: fetching {HERMES_REPO} (commits + releases + open PRs)...",
          file=sys.stderr)
    h_commits = fetch_repo_commits(HERMES_REPO, since)
    h_releases = fetch_repo_releases(HERMES_REPO)
    h_pulls = fetch_repo_open_pulls(HERMES_REPO)
    h_sect = safe_section_id(HERMES_REPO)
    if h_commits[0]:
        sources_ok.append(f"{h_sect}_commits")
    else:
        sources_failed.append({"source": f"{h_sect}_commits", "error": str(h_commits[1])[:200]})
        print(f"WARN: hermes commits failed: {h_commits[1]}", file=sys.stderr)
    if h_releases[0]:
        sources_ok.append(f"{h_sect}_releases")
    else:
        sources_failed.append({"source": f"{h_sect}_releases", "error": str(h_releases[1])[:200]})
        print(f"WARN: hermes releases failed: {h_releases[1]}", file=sys.stderr)
    if h_pulls[0]:
        sources_ok.append(f"{h_sect}_open_pulls")
    else:
        sources_failed.append({"source": f"{h_sect}_open_pulls", "error": str(h_pulls[1])[:200]})
        print(f"WARN: hermes open PRs failed: {h_pulls[1]}", file=sys.stderr)
    sections.extend(section_repo_activity(HERMES_REPO, h_sect, h_commits, h_releases,
                                          pulls=h_pulls))

    # ---- 4. Render ----
    parts: List[str] = []
    parts.append(f"# OSS Activity -- collected at {now_label()}")
    parts.append("")
    parts.append("## collection_status")
    parts.append(f"lookback_hours: {LOOKBACK_HOURS}")
    parts.append(f"since: {since}")
    parts.append(f"sources_ok: {sources_ok}")
    parts.append(f"sources_failed: {sources_failed}")
    parts.append("")

    parts.append("## openclaw_repos_overview")
    if ok_list and overview:
        parts.append("```json")
        parts.append(json.dumps(overview, indent=2, ensure_ascii=False))
        parts.append("```")
    elif ok_list:
        parts.append("(no repos returned)")
    else:
        parts.append(f"error: {list_payload}")
    parts.append("")

    parts.extend(sections)

    output_path.write_text("\n".join(parts), encoding="utf-8")

    n_ok = len(sources_ok)
    n_failed = len(sources_failed)
    total = n_ok + n_failed
    print(f"INFO: wrote {output_path} ({output_path.stat().st_size} bytes), "
          f"{n_ok}/{total} sources ok", file=sys.stderr)

    if total > 0 and n_ok == 0:
        emit_status("failed", str(output_path),
                    reason=f"all {total} GitHub fetches failed")

    emit_status(
        "ready", str(output_path),
        reason=f"{n_ok}/{total} sources ok ({len(active_repos)} active openclaw repos, "
               f"hermes={'ok' if h_commits[0] else 'partial'})",
    )
    return 0


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        emit_status("failed", None, f"unhandled: {type(exc).__name__}: {exc}")
