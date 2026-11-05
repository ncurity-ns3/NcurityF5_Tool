#!/usr/bin/env bash
set -euo pipefail

# Build macOS customer release: PyInstaller .app + ZIP + DMG + optional notarization.
#
# Usage:
#   ./scripts/build_macos.sh
#   ./scripts/build_macos.sh --skip-sign
#   ./scripts/build_macos.sh --notarize
#
# Optional environment variables:
#   NCURITY_MAC_CODESIGN_IDENTITY="Developer ID Application: ... (TEAMID)"
#   NCURITY_MAC_NOTARY_PROFILE="notarytool profile name"
#   NCURITY_MAC_BUNDLE_ID="kr.co.ncurity.f5tool" (default)

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SKIP_SIGN=0
DO_NOTARIZE=0
for arg in "$@"; do
  case "$arg" in
    --skip-sign) SKIP_SIGN=1 ;;
    --notarize) DO_NOTARIZE=1 ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script must run on macOS." >&2
  exit 1
fi

PY="$ROOT/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "Missing $PY. Create venv first (python3 -m venv .venv)." >&2
  exit 1
fi

APP_VERSION="$("$PY" - <<'PY'
from pathlib import Path
import re
toml = Path("pyproject.toml").read_text(encoding="utf-8")
m = re.search(r'^version\s*=\s*"([^"]+)"', toml, re.M)
print(m.group(1) if m else "0.1.0")
PY
)"

echo "Preparing dependencies..."
"$PY" -m pip install -q pyinstaller Pillow
"$PY" -m pip install -q -e ".[gui-mac,packaging]"
"$PY" scripts/prepare_branding_assets.py || true

ICON_PNG="$ROOT/app/resources/ncurity_app_icon.png"
ICON_ICNS="$ROOT/app/resources/ncurity_app_icon.icns"
if [[ ! -f "$ICON_PNG" ]]; then
  echo "Missing $ICON_PNG. Run scripts/prepare_branding_assets.py first." >&2
  exit 1
fi

if [[ ! -f "$ICON_ICNS" ]]; then
  echo "Generating $ICON_ICNS from PNG..."
  ICONSET_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ncurity-iconset.XXXXXX")"
  mkdir -p "$ICONSET_DIR"
  sips -z 16 16 "$ICON_PNG" --out "$ICONSET_DIR/icon_16x16.png" >/dev/null
  sips -z 32 32 "$ICON_PNG" --out "$ICONSET_DIR/icon_16x16@2x.png" >/dev/null
  sips -z 32 32 "$ICON_PNG" --out "$ICONSET_DIR/icon_32x32.png" >/dev/null
  sips -z 64 64 "$ICON_PNG" --out "$ICONSET_DIR/icon_32x32@2x.png" >/dev/null
  sips -z 128 128 "$ICON_PNG" --out "$ICONSET_DIR/icon_128x128.png" >/dev/null
  sips -z 256 256 "$ICON_PNG" --out "$ICONSET_DIR/icon_128x128@2x.png" >/dev/null
  sips -z 256 256 "$ICON_PNG" --out "$ICONSET_DIR/icon_256x256.png" >/dev/null
  sips -z 512 512 "$ICON_PNG" --out "$ICONSET_DIR/icon_256x256@2x.png" >/dev/null
  sips -z 512 512 "$ICON_PNG" --out "$ICONSET_DIR/icon_512x512.png" >/dev/null
  cp "$ICON_PNG" "$ICONSET_DIR/icon_512x512@2x.png"
  iconutil -c icns "$ICONSET_DIR" -o "$ICON_ICNS"
  rm -rf "$ICONSET_DIR"
fi

echo "Building app bundle..."
"$PY" -m PyInstaller app/gui/main.py \
  --name "NcurityF5Tool" \
  --windowed \
  --clean \
  --noconfirm \
  --icon "$ICON_ICNS" \
  --osx-bundle-identifier "${NCURITY_MAC_BUNDLE_ID:-kr.co.ncurity.f5tool}" \
  --add-data "app/resources:app/resources" \
  --add-data "templates:templates" \
  --add-data "config:config" \
  --hidden-import "app.runtime.paths" \
  --hidden-import "PyQt6.QtWebEngineWidgets" \
  --hidden-import "PyQt6.QtWebEngineCore" \
  --hidden-import "PyQt6.sip" \
  --hidden-import "httpx" \
  --hidden-import "jinja2" \
  --hidden-import "openpyxl" \
  --hidden-import "pydantic" \
  --hidden-import "yaml" \
  --exclude-module "matplotlib" \
  --exclude-module "numpy" \
  --exclude-module "pandas" \
  --exclude-module "scipy" \
  --exclude-module "tkinter" \
  --exclude-module "pytest" \
  --exclude-module "IPython" \
  --exclude-module "paramiko"

APP_PATH="$ROOT/dist/NcurityF5Tool.app"
if [[ ! -d "$APP_PATH" ]]; then
  echo "Build failed: $APP_PATH not found." >&2
  exit 1
fi

if [[ "$SKIP_SIGN" -eq 0 && -n "${NCURITY_MAC_CODESIGN_IDENTITY:-}" ]]; then
  echo "Signing app bundle..."
  ENTITLEMENTS="$ROOT/packaging/macos_entitlements.plist"
  codesign --force --deep --timestamp --options runtime \
    --entitlements "$ENTITLEMENTS" \
    --sign "$NCURITY_MAC_CODESIGN_IDENTITY" \
    "$APP_PATH"
  codesign --verify --deep --strict "$APP_PATH"
else
  echo "App signing skipped (set NCURITY_MAC_CODESIGN_IDENTITY or use --skip-sign)."
fi

RELEASE_DIR="$ROOT/dist/release"
mkdir -p "$RELEASE_DIR"
ZIP_PATH="$RELEASE_DIR/NcurityF5Tool-${APP_VERSION}-macos-app.zip"
rm -f "$ZIP_PATH"
ditto -c -k --sequesterRsrc --keepParent "$APP_PATH" "$ZIP_PATH"

# Build DMG (drag-and-drop install: app + Applications symlink)
DMG_STAGE="$(mktemp -d "${TMPDIR:-/tmp}/ncurity-dmg-stage.XXXXXX")"
cp -R "$APP_PATH" "$DMG_STAGE/"
ln -s /Applications "$DMG_STAGE/Applications"
DMG_PATH="$RELEASE_DIR/NcurityF5Tool-${APP_VERSION}-macos.dmg"
rm -f "$DMG_PATH"
hdiutil create \
  -volname "NcurityF5Tool" \
  -srcfolder "$DMG_STAGE" \
  -ov \
  -format UDZO \
  "$DMG_PATH" >/dev/null
rm -rf "$DMG_STAGE"

ZIP_SHA="$(shasum -a 256 "$ZIP_PATH" | awk '{print $1}')"
DMG_SHA="$(shasum -a 256 "$DMG_PATH" | awk '{print $1}')"
MANIFEST="$RELEASE_DIR/NcurityF5Tool-${APP_VERSION}-macos-release-manifest.txt"
{
  echo "Ncurity F5 Big-IP Managing Tool — macOS release manifest"
  echo "Version: $APP_VERSION"
  echo "Built: $(date '+%Y-%m-%d %H:%M:%S')"
  echo
  echo "App bundle: dist/NcurityF5Tool.app"
  echo "Portable ZIP: $(basename "$ZIP_PATH")"
  echo "ZIP SHA256: $ZIP_SHA"
  echo "DMG: $(basename "$DMG_PATH")"
  echo "DMG SHA256: $DMG_SHA"
  echo
  echo "Bundle ID: ${NCURITY_MAC_BUNDLE_ID:-kr.co.ncurity.f5tool}"
  if [[ -n "${NCURITY_MAC_CODESIGN_IDENTITY:-}" && "$SKIP_SIGN" -eq 0 ]]; then
    echo "Code signing: enabled ($NCURITY_MAC_CODESIGN_IDENTITY)"
  else
    echo "Code signing: skipped"
  fi
} > "$MANIFEST"

if [[ "$DO_NOTARIZE" -eq 1 ]]; then
  if [[ -z "${NCURITY_MAC_NOTARY_PROFILE:-}" ]]; then
    echo "Missing NCURITY_MAC_NOTARY_PROFILE for notarization." >&2
    exit 1
  fi
  echo "Submitting for notarization..."
  xcrun notarytool submit "$DMG_PATH" --keychain-profile "$NCURITY_MAC_NOTARY_PROFILE" --wait
  xcrun stapler staple "$APP_PATH"
  xcrun stapler staple "$DMG_PATH"
fi

echo
echo "App bundle: $APP_PATH"
echo "ZIP:        $ZIP_PATH"
echo "DMG:        $DMG_PATH"
echo "ZIP SHA256: $ZIP_SHA"
echo "DMG SHA256: $DMG_SHA"
echo "Manifest:   $MANIFEST"
