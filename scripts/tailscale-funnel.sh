#!/usr/bin/env bash
# tailscale-funnel.sh — wrapper for Tailscale Funnel management used by
# ClaudeBotManager and manual troubleshooting.
#
# Commands:
#   enable <port>   — expose a local port via Tailscale Funnel (persistent)
#   disable         — disable Funnel on HTTPS (port 443)
#   status          — print JSON status (including public URL when available)
#   detect          — print JSON: {installed, logged_in, tailnet, machine, base_url}
#
# Exits non-zero on failure. All responses on stdout are JSON.

set -u

find_tailscale() {
    for p in \
        /Applications/Tailscale.app/Contents/MacOS/Tailscale \
        /usr/local/bin/tailscale \
        /opt/homebrew/bin/tailscale \
        "$(command -v tailscale 2>/dev/null || true)"
    do
        if [[ -n "$p" && -x "$p" ]]; then
            echo "$p"
            return 0
        fi
    done
    return 1
}

json_error() {
    printf '{"ok":false,"error":%s}\n' "$(printf '%s' "$1" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')"
    exit 1
}

TS="$(find_tailscale)" || json_error "Tailscale binary not found"

cmd="${1:-}"

case "$cmd" in
    enable)
        port="${2:-}"
        if [[ -z "$port" ]]; then
            json_error "missing port argument"
        fi
        # Run with a hard timeout so we never hang the UI if tailscale blocks.
        # `perl -e alarm` is a portable timeout in POSIX shells on macOS (no `timeout` builtin).
        out="$(perl -e 'alarm shift; exec @ARGV' 30 "$TS" funnel --bg "$port" 2>&1)"
        rc=$?
        # Detect "Funnel feature not enabled on tailnet" — Tailscale prints an
        # authorization URL to stdout/stderr. The user must visit it once to
        # enable Funnel access for their tailnet, then retry.
        if printf '%s' "$out" | grep -qi "Funnel is not enabled on your tailnet\|enable Funnel"; then
            auth_url="$(printf '%s' "$out" | grep -Eo 'https://login\.tailscale\.com/[^[:space:]]*')"
            printf '{"ok":false,"error":"funnel_tailnet_not_enabled","auth_url":%s,"raw":%s}\n' \
                "$(printf '%s' "$auth_url" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')" \
                "$(printf '%s' "$out" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')"
            exit 0
        fi
        if [[ $rc -ne 0 ]]; then
            printf '{"ok":false,"error":%s}\n' \
                "$(printf '%s' "$out" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')"
            exit 0
        fi
        printf '{"ok":true,"action":"enable","port":%d,"output":%s}\n' \
            "$port" \
            "$(printf '%s' "$out" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')"
        ;;
    disable)
        out="$("$TS" funnel --https=443 off 2>&1)" || true
        printf '{"ok":true,"action":"disable","output":%s}\n' \
            "$(printf '%s' "$out" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')"
        ;;
    status)
        out="$("$TS" funnel status --json 2>&1)" || {
            printf '{"ok":false,"error":%s}\n' \
                "$(printf '%s' "$out" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')"
            exit 0
        }
        printf '{"ok":true,"status":%s}\n' "$out"
        ;;
    detect)
        # Returns combined info: installed, login state, tailnet, machine, base_url
        if ! "$TS" status --peers=false >/dev/null 2>&1; then
            printf '{"ok":true,"installed":true,"logged_in":false}\n'
            exit 0
        fi
        ts_status="$("$TS" status --json 2>/dev/null || echo '{}')"
        python3 - "$ts_status" <<'PY'
import json, sys
try:
    data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
except Exception:
    data = {}
self_info = data.get("Self") or {}
machine = (self_info.get("HostName") or "").lower()
dns_name = (self_info.get("DNSName") or "").rstrip(".")
# DNSName is like "mac.tail1234.ts.net." — prefer it since it includes tailnet
base_url = None
if dns_name:
    base_url = f"https://{dns_name}"
elif machine:
    base_url = f"https://{machine}"
out = {
    "ok": True,
    "installed": True,
    "logged_in": bool(dns_name or machine),
    "machine": machine,
    "dns_name": dns_name,
    "base_url": base_url,
}
print(json.dumps(out))
PY
        ;;
    *)
        json_error "unknown command: ${cmd:-<empty>}. Use: enable <port> | disable | status | detect"
        ;;
esac
