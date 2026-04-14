Collect recent activity from two GitHub repositories. Run the commands below and save ALL output to the data file.

## 1. OpenClaw (https://github.com/openclaw)

First, discover the main repos under the openclaw org:

```bash
curl -sL "https://api.github.com/orgs/openclaw/repos?sort=pushed&per_page=10" 2>/dev/null | python3 -c "
import sys, json
repos = json.load(sys.stdin)
for r in repos:
    print(f\"{r['full_name']}  pushed:{r['pushed_at']}  stars:{r['stargazers_count']}\")
"
```

For each repo that was pushed in the last 48 hours, fetch recent commits:

```bash
curl -sL "https://api.github.com/repos/{full_name}/commits?since=$(date -u -v-2d '+%Y-%m-%dT%H:%M:%SZ')&per_page=20" 2>/dev/null | python3 -c "
import sys, json
commits = json.load(sys.stdin)
for c in commits:
    sha = c['sha'][:7]
    msg = c['commit']['message'].split('\n')[0]
    date = c['commit']['author']['date']
    print(f'{sha} {date} {msg}')
"
```

Also check for recent releases:

```bash
curl -sL "https://api.github.com/repos/{full_name}/releases?per_page=3" 2>/dev/null | python3 -c "
import sys, json
releases = json.load(sys.stdin)
for r in releases:
    print(f\"Release: {r['tag_name']} ({r['published_at']}) — {r['name']}\")
    if r.get('body'):
        print(r['body'][:500])
    print()
"
```

## 2. Hermes Agent (https://github.com/NousResearch/hermes-agent)

```bash
curl -sL "https://api.github.com/repos/NousResearch/hermes-agent/commits?since=$(date -u -v-2d '+%Y-%m-%dT%H:%M:%SZ')&per_page=20" 2>/dev/null | python3 -c "
import sys, json
commits = json.load(sys.stdin)
for c in commits:
    sha = c['sha'][:7]
    msg = c['commit']['message'].split('\n')[0]
    date = c['commit']['author']['date']
    print(f'{sha} {date} {msg}')
"
```

```bash
curl -sL "https://api.github.com/repos/NousResearch/hermes-agent/releases?per_page=3" 2>/dev/null | python3 -c "
import sys, json
releases = json.load(sys.stdin)
for r in releases:
    print(f\"Release: {r['tag_name']} ({r['published_at']}) — {r['name']}\")
    if r.get('body'):
        print(r['body'][:500])
    print()
"
```

Also check open PRs for interesting new features:

```bash
curl -sL "https://api.github.com/repos/NousResearch/hermes-agent/pulls?state=open&sort=updated&per_page=10" 2>/dev/null | python3 -c "
import sys, json
prs = json.load(sys.stdin)
for p in prs:
    print(f\"PR #{p['number']}: {p['title']} (by {p['user']['login']}, updated {p['updated_at']})\")
"
```

## Output

Write ALL collected data to the data file. Structure it as:

```
# OSS Activity Report — {date}

## OpenClaw

### Repos
{list of repos with push dates}

### Recent Commits
{commits per repo}

### Releases
{releases if any}

## Hermes Agent

### Recent Commits
{commits}

### Releases
{releases if any}

### Open PRs
{PRs}

## Summary
- OpenClaw: {N} new commits, {M} releases
- Hermes Agent: {N} new commits, {M} releases, {K} open PRs
```

If BOTH repos had zero activity in the last 48h, respond with exactly `NO_REPLY` and stop. Do not write the data file.
