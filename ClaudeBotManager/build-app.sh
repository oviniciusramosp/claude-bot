#!/bin/bash
# build-app.sh — Compila ClaudeBotManager e monta o .app bundle com assinatura estável.
# O bundle garante que o macOS preserva as permissões (TCC) entre builds.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_BUNDLE="$SCRIPT_DIR/ClaudeBotManager.app"
BINARY_NAME="ClaudeBotManager"
BUILD_DIR="$SCRIPT_DIR/.build/release"
PLIST_SRC="$SCRIPT_DIR/Sources/App/Info.plist"

echo "→ Building $BINARY_NAME (release)..."
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \
  /Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/swift build \
  -c release --package-path "$SCRIPT_DIR"

echo "→ Assembling .app bundle..."
mkdir -p "$APP_BUNDLE/Contents/MacOS"
mkdir -p "$APP_BUNDLE/Contents/Resources"

cp "$BUILD_DIR/$BINARY_NAME" "$APP_BUNDLE/Contents/MacOS/$BINARY_NAME"
cp "$PLIST_SRC" "$APP_BUNDLE/Contents/Info.plist"

# Copy SPM resource bundles (e.g. images) into the app
for bundle in "$BUILD_DIR"/*.bundle; do
    [ -d "$bundle" ] && cp -R "$bundle" "$APP_BUNDLE/Contents/Resources/"
done

echo "→ Signing with ad-hoc identity..."
codesign --sign - --force --deep "$APP_BUNDLE"

echo "→ Restarting app..."
pkill -x "$BINARY_NAME" 2>/dev/null || true
sleep 0.5
open "$APP_BUNDLE"

echo "✓ Done — $APP_BUNDLE"
