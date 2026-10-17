#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# Build dist/LegendsOnLinux-<version>-x86_64.AppImage (and its .zsync).
#
#   scripts/build-appimage.sh            # from the working tree
#   scripts/build-appimage.sh --head     # from the last commit only
#
# The AppImage carries its own Python (python-build-standalone 3.12) with
# PySide6, cryptography and certifi from hash-pinned wheels, so it needs
# nothing from the host but glibc >= 2.34, the X11/Wayland libraries every
# desktop has, and WebKitGTK 4.1 (for xodus-cli's Store sign-in window; the
# launcher says how to install it when it is missing).
#
# Needs: curl, tar, readelf (binutils); eu-strip (elfutils) to strip the
# bundled Python. The pins for Python and appimagetool are the ones
# BedrockOnLinux reviewed for its AppImage.
set -euo pipefail

src=$(cd "$(dirname "$0")/.." && pwd)
app_id=io.github.mdx0111.LegendsOnLinux
version=$(grep -m1 '^VERSION = ' "$src/legends_on_linux/config.py" | cut -d'"' -f2)
out=${OUTDIR:-$src/dist}
cache=${APPIMAGE_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/legends-on-linux-build}
from_head=false
for arg in "$@"; do
    case $arg in
        --head) from_head=true ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

pbs_tag=20260610
pbs_py=3.12.13
pbs_asset=cpython-$pbs_py+$pbs_tag-x86_64-unknown-linux-gnu-install_only.tar.gz
pbs_url=https://github.com/astral-sh/python-build-standalone/releases/download/$pbs_tag/$pbs_asset
pbs_sha256=c218f50baeb2c06a30c2f03db5986b2bad6ab7c8a52faad2d5a59bda0677b93a
tool_url=https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage
tool_sha256=ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0
runtime_url=https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64
runtime_sha256=2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d
# AppImageUpdate and friends read this to find newer versions.
update_info="gh-releases-zsync|mdx0111|LegendsOnLinux|latest|LegendsOnLinux-*-x86_64.AppImage.zsync"

fetch() {  # url output sha256
    local url=$1 output=$2 expected=$3
    if [[ -f "$output" ]] && [[ "$(sha256sum "$output" | cut -d' ' -f1)" == "$expected" ]]; then
        return
    fi
    curl -fL --retry 3 -o "$output.part" "$url"
    [[ "$(sha256sum "$output.part" | cut -d' ' -f1)" == "$expected" ]] \
        || { rm -f "$output.part"; echo "SHA-256 mismatch for $url" >&2; exit 1; }
    mv -f "$output.part" "$output"
}

mkdir -p "$cache" "$out"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
appdir=$work/LegendsOnLinux.AppDir
tree=$work/tree
mkdir -p "$appdir/usr" "$tree"

# Project files, as git sees them.
if $from_head; then
    git -C "$src" archive HEAD | tar -x -C "$tree"
else
    git -C "$src" ls-files -z --cached --others --exclude-standard \
        | (cd "$src" && while IFS= read -r -d '' f; do [[ -e "$f" ]] && printf '%s\0' "$f"; done) \
        | (cd "$src" && tar --null -T - -cf -) | tar -x -C "$tree"
fi

echo ":: Python $pbs_py (python-build-standalone $pbs_tag)"
fetch "$pbs_url" "$cache/$pbs_asset" "$pbs_sha256"
tar -C "$appdir/usr" -xzf "$cache/$pbs_asset"
py=$appdir/usr/python/bin/python3.12
site=$appdir/usr/python/lib/python3.12/site-packages
# Unused parts of the standard library and its test suite.
rm -rf "$appdir"/usr/python/lib/python3.12/{test,idlelib,tkinter,turtledemo,ensurepip} \
       "$appdir"/usr/python/lib/{tcl*,tk*,itcl*,thread*,libtcl*,libtk*} "$appdir"/usr/python/include \
       "$appdir"/usr/python/share/man \
       "$appdir"/usr/python/lib/python3.12/lib-dynload/_tkinter*.so
# The interpreter is self-contained (its C modules are built in), and nothing
# bundled links libpython, which only exists for embedding: 218 MB unused.
rm -f "$appdir"/usr/python/lib/libpython3*.so*
# python-build-standalone ships its binaries with debug symbols. GNU strip
# breaks the interpreter's dynamic symbol table ("allocated section .dynstr
# not in segment"); elfutils' eu-strip handles its layout.
if command -v eu-strip >/dev/null; then
    for elf in "$appdir"/usr/python/bin/python3.12 "$appdir"/usr/python/lib/python3.12/lib-dynload/*.so; do
        eu-strip -g "$elf"
    done
else
    echo "   (eu-strip from elfutils not found: keeping debug symbols, ~70 MB more)"
fi

echo ":: Python packages (pinned wheels)"
PYTHONNOUSERSITE=1 "$py" -m pip install --quiet --disable-pip-version-check --no-cache-dir \
    --no-compile --no-deps --require-hashes --only-binary=:all: \
    -r "$tree/third_party/requirements-appimage.txt"
"$py" -m pip uninstall --quiet -y pip >/dev/null 2>&1 || true
rm -rf "$appdir"/usr/python/bin/{pip*,idle*,pydoc*,pyside6-*,shiboken6*}
bash "$tree/scripts/prune-pyside6.sh" "$site"

echo ":: the launcher"
lib=$appdir/usr/lib/legends-on-linux
install -d "$lib/engine"
cp -a "$tree/legends_on_linux" "$tree/data" "$lib/"
cp -a "$tree/engine/patches" "$lib/engine/"
install -m755 "$tree/legends-on-linux" "$lib/legends-on-linux"
install -Dm755 "$tree/scripts/build-xgameruntime.sh" "$lib/scripts/build-xgameruntime.sh"
find "$appdir" -name __pycache__ -prune -exec rm -rf {} +

# Desktop integration: the top-level copies are what appimagetool reads.
install -Dm644 "$tree/data/$app_id.desktop" "$appdir/usr/share/applications/$app_id.desktop"
install -Dm644 "$tree/data/$app_id.metainfo.xml" "$appdir/usr/share/metainfo/$app_id.appdata.xml"
for icon in "$tree"/data/icons/hicolor/*/apps/"$app_id.png"; do
    install -Dm644 "$icon" "$appdir/usr/share/${icon#"$tree"/data/}"
done
cp "$tree/data/$app_id.desktop" "$appdir/$app_id.desktop"
cp "$tree/data/icons/hicolor/256x256/apps/$app_id.png" "$appdir/$app_id.png"
ln -s "$app_id.png" "$appdir/.DirIcon"
install -Dm644 "$tree/LICENSE" "$appdir/usr/share/licenses/legends-on-linux/LICENSE"
install -Dm644 "$tree/THIRD_PARTY.md" "$appdir/usr/share/licenses/legends-on-linux/THIRD_PARTY.md"

cat > "$appdir/AppRun" <<'EOF'
#!/bin/sh
# LegendsOnLinux AppImage entry point.
here="$(dirname "$(readlink -f "$0")")"
# Self-contained Python: nothing from the host's Python may leak in.
unset PYTHONHOME PYTHONPATH PYTHONSTARTUP PYTHONUSERBASE
export PYTHONNOUSERSITE=1
# The bundled OpenSSL looks for CA certificates where its build put them;
# use the host's bundle when there is one, certifi's otherwise.
if [ -z "${SSL_CERT_FILE:-}" ]; then
    for ca in /etc/ssl/certs/ca-certificates.crt /etc/pki/tls/certs/ca-bundle.crt \
              /etc/ssl/ca-bundle.pem /etc/ssl/cert.pem \
              "$here/usr/python/lib/python3.12/site-packages/certifi/cacert.pem"; do
        if [ -f "$ca" ]; then export SSL_CERT_FILE="$ca"; break; fi
    done
fi
exec "$here/usr/python/bin/python3.12" "$here/usr/lib/legends-on-linux/legends-on-linux" "$@"
EOF
chmod 755 "$appdir/AppRun"
sh -n "$appdir/AppRun"

echo ":: checking the bundle in a clean environment"
env -i HOME="$work/home" PATH=/usr/bin:/bin QT_QPA_PLATFORM=offscreen \
    SSL_CERT_FILE="$site/certifi/cacert.pem" PYTHONNOUSERSITE=1 \
    "$py" -I - "$lib" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import cryptography, ssl, PySide6
from PySide6.QtWidgets import QApplication
import legends_on_linux.gui as gui
assert PySide6.__file__.startswith(sys.prefix), PySide6.__file__
app = QApplication([])
window = gui.MainWindow()
print(f"   Python {sys.version.split()[0]}, PySide6 {PySide6.__version__}, "
      f"cryptography {cryptography.__version__}, {ssl.OPENSSL_VERSION}; window ok")
PY

echo ":: packing"
fetch "$tool_url" "$cache/appimagetool" "$tool_sha256"
fetch "$runtime_url" "$cache/runtime-x86_64" "$runtime_sha256"
chmod 755 "$cache/appimagetool"
image=$out/LegendsOnLinux-$version-x86_64.AppImage
rm -f "$image" "$image.zsync"
(cd "$out" && ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$cache/appimagetool" --no-appstream \
    --runtime-file "$cache/runtime-x86_64" -u "$update_info" "$appdir" "$image" >"$work/tool.log" 2>&1) \
    || { tail -20 "$work/tool.log"; exit 1; }
chmod 755 "$image"
(cd "$out" && sha256sum "$(basename "$image")" > SHA256SUMS-appimage)
echo ":: built $image ($(du -h "$image" | cut -f1))"
