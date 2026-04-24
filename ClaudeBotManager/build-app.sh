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

echo "→ Generating AppIcon.icns from bot-avatar.png..."
AVATAR_SRC="$SCRIPT_DIR/Sources/Resources/bot-avatar.png"
ICONSET_DIR="$SCRIPT_DIR/.build/AppIcon.iconset"
ICNS_OUT="$SCRIPT_DIR/.build/AppIcon.icns"
rm -rf "$ICONSET_DIR" && mkdir -p "$ICONSET_DIR"
for size in 16 32 64 128 256 512 1024; do
    label=$([ $size -le 512 ] && echo "icon_${size}x${size}.png" || echo "icon_512x512@2x.png")
    sips -z $size $size "$AVATAR_SRC" --out "$ICONSET_DIR/$label" >/dev/null
done
# @2x variants
sips -z 32  32  "$AVATAR_SRC" --out "$ICONSET_DIR/icon_16x16@2x.png"  >/dev/null
sips -z 64  64  "$AVATAR_SRC" --out "$ICONSET_DIR/icon_32x32@2x.png"  >/dev/null
sips -z 256 256 "$AVATAR_SRC" --out "$ICONSET_DIR/icon_128x128@2x.png" >/dev/null
sips -z 512 512 "$AVATAR_SRC" --out "$ICONSET_DIR/icon_256x256@2x.png" >/dev/null
iconutil -c icns "$ICONSET_DIR" -o "$ICNS_OUT"

echo "→ Assembling .app bundle..."
mkdir -p "$APP_BUNDLE/Contents/MacOS"
mkdir -p "$APP_BUNDLE/Contents/Resources"

cp "$BUILD_DIR/$BINARY_NAME" "$APP_BUNDLE/Contents/MacOS/$BINARY_NAME"
cp "$PLIST_SRC" "$APP_BUNDLE/Contents/Info.plist"
cp "$ICNS_OUT" "$APP_BUNDLE/Contents/Resources/AppIcon.icns"

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
