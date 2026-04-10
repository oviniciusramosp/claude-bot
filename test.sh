#!/usr/bin/env bash
# Run the claude-bot test suite. No pip dependencies for Python — stdlib only.
#
# Usage:
#   ./test.sh                 # run Python + Swift
#   ./test.sh py              # Python only
#   ./test.sh swift           # Swift only
#   ./test.sh tests.test_name # run a single Python module
#
# Set TEST_SKIP_SWIFT=1 to skip the Swift suite (e.g. in environments without Xcode).
set -euo pipefail

cd "$(dirname "$0")"

# Suppress noisy ResourceWarnings from the rotating log handler that the bot
# touches at import time. The bot itself runs fine; tests just open it many
# times in one process.
export PYTHONWARNINGS="${PYTHONWARNINGS:-ignore::ResourceWarning}"

run_python() {
    echo "→ Python tests"
    python3 -m unittest discover -t . -s tests -v
}

run_swift() {
    if [[ "${TEST_SKIP_SWIFT:-}" == "1" ]]; then
        echo "→ Swift tests skipped (TEST_SKIP_SWIFT=1)"
        return 0
    fi
    if [[ ! -d /Applications/Xcode.app ]]; then
        echo "→ Swift tests skipped (Xcode.app not found at /Applications/Xcode.app)"
        return 0
    fi
    echo "→ Swift tests"
    DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \
        /Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/swift \
        test --package-path ClaudeBotManager
}

case "${1:-all}" in
    py|python)
        run_python
        ;;
    swift)
        run_swift
        ;;
    all)
        run_python
        run_swift
        ;;
    tests.*)
        python3 -m unittest "$@"
        ;;
    *)
        python3 -m unittest "$@"
        ;;
esac
