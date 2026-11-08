#!/usr/bin/env bash
# Builds PDFNest.app for macOS with PyInstaller and packs it into a .dmg (or a .zip without hdiutil).
#
#   scripts/build_macos_app.sh [VERSION]
#
# Must run on a Mac: PyInstaller cannot cross-compile. The app is built for the architecture of
# the Python that runs it (arm64 on Apple Silicon, x86_64 on Intel). CI builds both, see
# .github/workflows/release.yml.
#
# Environment:
#   PYTHON     Python with the app's requirements and PyInstaller (default: .venv/bin/python,
#              else python3 on PATH)
#   BUNDLE_ID  CFBundleIdentifier (default: io.github.pdfnest.PDFNest)
#   SIGN_ID    codesign identity (default: "-", an ad-hoc signature; the app is not notarized)
#
# Output (under release/):
#   PDFNest.app
#   PDFNest-<VERSION>-macos-<arch>.dmg   (or .zip when hdiutil is unavailable)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "error: build_macos_app.sh must run on macOS (PyInstaller cannot cross-compile)." >&2
    exit 1
fi

if [[ -n "${PYTHON:-}" ]]; then
    :
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
    PYTHON="$ROOT/.venv/bin/python"
else
    PYTHON="$(command -v python3)"
fi

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
    VERSION="$("$PYTHON" - <<'PY'
import re, pathlib
text = pathlib.Path("pyproject.toml").read_text(encoding="utf-8")
match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
print(match.group(1) if match else "0.0.0")
PY
)"
fi
VERSION="${VERSION#v}"
BUNDLE_ID="${BUNDLE_ID:-io.github.pdfnest.PDFNest}"
SIGN_ID="${SIGN_ID:--}"
ARCH="$("$PYTHON" -c 'import platform; print(platform.machine())')"

if ! "$PYTHON" -m PyInstaller --version >/dev/null 2>&1; then
    echo "error: PyInstaller is not installed. Run: $PYTHON -m pip install pyinstaller" >&2
    exit 1
fi

RELEASE="$ROOT/release"
WORK="$ROOT/build/pyinstaller-macos"
DIST="$WORK/dist"
MAIN="$ROOT/src/pdf_notes_reader/main.py"
ASSET="$ROOT/src/pdf_notes_reader/assets/Icon.png"
PIC="$ROOT/Pic"

# Icon source: the same transparent PNG the Windows build uses, else the tracked copies.
ICON_PNG=""
for candidate in "$ROOT/release_assets/PDFNest-256x256-transparent.png" "$ROOT/PDFNest-Icon.png" "$ROOT/Icon.png" "$ASSET"; do
    if [[ -f "$candidate" ]]; then
        ICON_PNG="$candidate"
        break
    fi
done
[[ -n "$ICON_PNG" ]] || { echo "error: no icon PNG found (PDFNest-Icon.png / Icon.png)" >&2; exit 1; }
[[ -f "$ASSET" ]] || { echo "error: missing bundled icon $ASSET" >&2; exit 1; }
[[ -d "$PIC" ]] || { echo "error: missing UI icon assets folder $PIC" >&2; exit 1; }

rm -rf "$WORK"
mkdir -p "$WORK" "$RELEASE"

echo "==> PDFNest $VERSION for macOS $ARCH ($PYTHON)"

# --- .icns from the PNG (sips + iconutil ship with macOS) --------------------------------------
ICONSET="$WORK/PDFNest.iconset"
ICNS="$WORK/PDFNest.icns"
mkdir -p "$ICONSET"
for size in 16 32 128 256 512; do
    sips -z "$size" "$size" "$ICON_PNG" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
    double=$((size * 2))
    sips -z "$double" "$double" "$ICON_PNG" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$ICNS"

# --- PyInstaller: windowed onedir build -> PDFNest.app ----------------------------------------
# Same data files as scripts/build_windows_exe.ps1 (":" is the macOS --add-data separator).
"$PYTHON" -m PyInstaller --noconfirm --clean --windowed \
    --name PDFNest \
    --osx-bundle-identifier "$BUNDLE_ID" \
    --icon "$ICNS" \
    --paths "$ROOT/src" \
    --distpath "$DIST" --workpath "$WORK/build" --specpath "$WORK" \
    --add-data "$ASSET:pdf_notes_reader/assets" \
    --add-data "$PIC:Pic" \
    "$MAIN"

APP="$DIST/PDFNest.app"
PLIST="$APP/Contents/Info.plist"
[[ -f "$PLIST" ]] || { echo "error: PyInstaller did not produce $APP" >&2; exit 1; }

# --- Info.plist: version, pdfnest:// links, .pdf documents ------------------------------------
"$PYTHON" - "$PLIST" "$VERSION" "$BUNDLE_ID" <<'PY'
import plistlib, sys

path, version, bundle_id = sys.argv[1:4]
with open(path, "rb") as handle:
    info = plistlib.load(handle)
info.update({
    "CFBundleName": "PDFNest",
    "CFBundleDisplayName": "PDFNest",
    "CFBundleIdentifier": bundle_id,
    "CFBundleShortVersionString": version,
    "CFBundleVersion": version,
    "NSHighResolutionCapable": True,
    "NSPrincipalClass": "NSApplication",
    "LSApplicationCategoryType": "public.app-category.productivity",
    # pdfnest://open?path=...&page=N&note=ID links (from Obsidian etc.) arrive as QFileOpenEvent.
    "CFBundleURLTypes": [{
        "CFBundleURLName": f"{bundle_id}.link",
        "CFBundleURLSchemes": ["pdfnest"],
        "CFBundleTypeRole": "Viewer",
    }],
    # Offer PDFNest in Finder's "Open With" for PDFs without taking over the default viewer.
    "CFBundleDocumentTypes": [{
        "CFBundleTypeName": "PDF Document",
        "CFBundleTypeRole": "Viewer",
        "LSHandlerRank": "Alternate",
        "LSItemContentTypes": ["com.adobe.pdf"],
        "CFBundleTypeExtensions": ["pdf"],
        "CFBundleTypeIconFile": "PDFNest.icns",
    }],
})
with open(path, "wb") as handle:
    plistlib.dump(info, handle)
PY

# Editing Info.plist breaks PyInstaller's signature; Apple Silicon refuses to run unsigned code,
# so sign again (ad-hoc unless SIGN_ID names a Developer ID).
codesign --force --deep --sign "$SIGN_ID" "$APP"
codesign --verify --deep --strict "$APP"

rm -rf "$RELEASE/PDFNest.app"
ditto "$APP" "$RELEASE/PDFNest.app"

# --- package --------------------------------------------------------------------------------
BASENAME="PDFNest-$VERSION-macos-$ARCH"
if command -v hdiutil >/dev/null 2>&1; then
    STAGE="$WORK/dmg"
    rm -rf "$STAGE"
    mkdir -p "$STAGE"
    ditto "$APP" "$STAGE/PDFNest.app"
    ln -s /Applications "$STAGE/Applications"
    OUT="$RELEASE/$BASENAME.dmg"
    rm -f "$OUT"
    hdiutil create -volname "PDFNest $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$OUT" >/dev/null
else
    OUT="$RELEASE/$BASENAME.zip"
    rm -f "$OUT"
    ditto -c -k --sequesterRsrc --keepParent "$APP" "$OUT"
fi

echo "==> $OUT"
ls -l "$RELEASE"
