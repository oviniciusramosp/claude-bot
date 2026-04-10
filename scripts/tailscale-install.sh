#!/usr/bin/env bash
# tailscale-install.sh — download and install the latest Tailscale macOS .pkg
# from the official pkgs.tailscale.com CDN, using a GUI password prompt for the
# installer step. Emits JSON to stdout. Non-zero exit on failure.
#
# This avoids requiring the user to use Homebrew or manually download anything,
# but still requires the system password once (inherent to any macOS .pkg) and
# Network Extension approval on Tailscale's first launch (controlled by macOS).

set -u

json_error() {
    printf '{"ok":false,"error":%s}\n' \
        "$(printf '%s' "$1" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')"
    exit 1
}

# 1) Fetch the latest stable version metadata (published at pkgs.tailscale.com)
version_json="$(curl -fsSL 'https://pkgs.tailscale.com/stable/?mode=json' 2>&1)" \
    || json_error "failed to fetch version info: $version_json"

# Parse: {"MacZips": {"universal-package": "Tailscale-1.96.5-macos.pkg"}, "MacZipsVersion": "1.96.5"}
read -r version pkg_filename <<<"$(printf '%s' "$version_json" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
    version = data.get("MacZipsVersion", "")
    filename = (data.get("MacZips") or {}).get("universal-package", "")
    if not version or not filename:
        sys.exit(1)
    print(version, filename)
except Exception:
    sys.exit(1)
' 2>/dev/null)" || json_error "failed to parse version feed"

if [[ -z "${version:-}" || -z "${pkg_filename:-}" ]]; then
    json_error "empty version or filename from feed"
fi

# 2) Construct the .pkg URL
pkg_url="https://pkgs.tailscale.com/stable/${pkg_filename}"
pkg_path="/tmp/${pkg_filename}"

# 3) Download (no sudo needed)
if ! curl -fSL -o "$pkg_path" "$pkg_url" 2>/tmp/tailscale-install-curl.log; then
    err="$(tail -c 500 /tmp/tailscale-install-curl.log 2>/dev/null || echo 'download failed')"
    rm -f "$pkg_path"
    json_error "download failed: $err"
fi

# 4) Install via AppleScript's `with administrator privileges` which triggers
#    the standard macOS GUI password dialog exactly once.
install_output="$(osascript -e "do shell script \"/usr/sbin/installer -pkg '$pkg_path' -target /\" with administrator privileges" 2>&1)"
install_status=$?

rm -f "$pkg_path"

if [[ $install_status -ne 0 ]]; then
    # User-cancelled password dialogs come back as "User canceled" (-128)
    if [[ "$install_output" == *"User canceled"* ]] || [[ "$install_output" == *"-128"* ]]; then
        json_error "cancelled by user"
    fi
    json_error "installer failed: $install_output"
fi

printf '{"ok":true,"version":%s}\n' \
    "$(printf '%s' "$version" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')"
