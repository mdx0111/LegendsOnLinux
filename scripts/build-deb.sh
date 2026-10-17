#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# Build the LegendsOnLinux .deb (amd64) into dist/.
#
#   scripts/build-deb.sh            # from the working tree (tracked + new files)
#   scripts/build-deb.sh --head     # from the last commit only
#
# Ubuntu 22.04/24.04 package no PySide6, so the pinned, hash-checked wheels of
# third_party/requirements-deb.txt are bundled into /usr/lib/legends-on-linux/
# vendor; everything else comes from the distribution.
#
# Needs dpkg-deb and python3-pip. Without them (on Fedora, say) the build
# runs itself inside a debian:trixie container through podman or docker.
# OUTDIR overrides where the package goes (default: dist/).
set -euo pipefail

src=$(cd "$(dirname "$0")/.." && pwd)
name=legends-on-linux
app_id=io.github.mdx0111.LegendsOnLinux
version=$(grep -m1 '^VERSION = ' "$src/legends_on_linux/config.py" | cut -d'"' -f2)
revision=${DEB_REVISION:-1}
out=${OUTDIR:-$src/dist}
from_head=false
for arg in "$@"; do
    case $arg in
        --head) from_head=true ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

if ! command -v dpkg-deb >/dev/null || ! python3 -m pip --version >/dev/null 2>&1; then
    engine=$(command -v podman || command -v docker || true)
    [[ -n "$engine" ]] || { echo "need dpkg-deb and python3-pip, or podman/docker" >&2; exit 1; }
    echo ":: building inside debian:trixie ($engine)"
    mkdir -p "$out"
    exec "$engine" run --rm -v "$src:/src:ro,Z" -v "$out:/out:Z" -e OUTDIR=/out \
        -e DEB_REVISION="$revision" -e SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-}" \
        -e DEBIAN_FRONTEND=noninteractive docker.io/library/debian:trixie bash -c "
            set -e
            apt-get update -qq
            apt-get install -y -qq --no-install-recommends python3-pip git ca-certificates binutils >/dev/null
            git config --global --add safe.directory '*'
            /src/scripts/build-deb.sh $*"
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
pkg=$work/pkg
lib=$pkg/usr/lib/$name

# Project files: git's view of the tree, so nothing ignored or untracked-and-
# ignored (dist/, caches) slips in.
mkdir -p "$work/tree"
if $from_head; then
    git -C "$src" archive HEAD | tar -x -C "$work/tree"
else
    git -C "$src" ls-files -z --cached --others --exclude-standard \
        | (cd "$src" && while IFS= read -r -d '' f; do [[ -e "$f" ]] && printf '%s\0' "$f"; done) \
        | (cd "$src" && tar --null -T - -cf -) | tar -x -C "$work/tree"
fi
tree=$work/tree

install -d "$lib" "$pkg/usr/bin" "$pkg/DEBIAN" "$pkg/usr/share/doc/$name"
cp -a "$tree/legends_on_linux" "$tree/data" "$lib/"
install -m755 "$tree/legends-on-linux" "$lib/legends-on-linux"
install -Dm755 "$tree/scripts/build-xgameruntime.sh" "$lib/scripts/build-xgameruntime.sh"
install -d "$lib/engine"
cp -a "$tree/engine/patches" "$lib/engine/"
ln -s "../lib/$name/legends-on-linux" "$pkg/usr/bin/$name"

echo ":: bundling PySide6 (pinned wheels)"
python3 -m pip install --quiet --root-user-action=ignore --no-cache-dir --no-compile --no-deps --require-hashes \
    --only-binary=:all: --platform manylinux_2_34_x86_64 --python-version 3.10 \
    --implementation cp --abi abi3 --target "$lib/vendor" \
    -r "$tree/third_party/requirements-deb.txt"
rm -rf "$lib/vendor/bin"
"$tree/scripts/prune-pyside6.sh" "$lib/vendor"
find "$lib" -name __pycache__ -prune -exec rm -rf {} +
for meta in "$lib"/vendor/*.dist-info; do
    [[ -d "$meta" ]] || { echo "missing wheel metadata in vendor/" >&2; exit 1; }
done

# Desktop integration.
install -Dm644 "$tree/data/$app_id.desktop" "$pkg/usr/share/applications/$app_id.desktop"
install -Dm644 "$tree/data/$app_id.metainfo.xml" "$pkg/usr/share/metainfo/$app_id.metainfo.xml"
for icon in "$tree"/data/icons/hicolor/*/apps/"$app_id.png"; do
    install -Dm644 "$icon" "$pkg/usr/share/${icon#"$tree"/data/}"
done
install -m644 "$tree/README.md" "$pkg/usr/share/doc/$name/README.md"
{
    echo "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/"
    echo "Upstream-Name: LegendsOnLinux"
    echo "Source: https://github.com/mdx0111/LegendsOnLinux"
    echo
    echo "Files: *"
    echo "License: MIT"
    echo
    echo "Files: usr/lib/$name/vendor/*"
    echo "License: LGPL-3.0-only (PySide6, shiboken6 and the Qt libraries they bundle)"
    echo
    echo "Files: usr/lib/$name/engine/patches/*"
    echo "License: LGPL-2.1-or-later (patches to WineGDK)"
    echo
    sed 's/^$/./; s/^/ /' "$tree/LICENSE"
    echo
    sed 's/^$/./; s/^/ /' "$tree/THIRD_PARTY.md"
} > "$pkg/usr/share/doc/$name/copyright"

size=$(du -sk --exclude=DEBIAN "$pkg" | cut -f1)
cat > "$pkg/DEBIAN/control" <<EOF
Package: $name
Version: $version-$revision
Section: games
Priority: optional
Architecture: amd64
Installed-Size: $size
Depends: python3 (>= 3.10), python3-cryptography, libwebkit2gtk-4.1-0,
 ca-certificates, xdg-utils,
 libglib2.0-0t64 | libglib2.0-0, libdbus-1-3, libfontconfig1, libfreetype6,
 libgl1, libegl1, libopengl0, libx11-6, libx11-xcb1, libxkbcommon0, libxkbcommon-x11-0,
 libxcb1, libxcb-cursor0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1,
 libxcb-randr0, libxcb-render0, libxcb-render-util0, libxcb-shape0, libxcb-shm0,
 libxcb-sync1, libxcb-util1, libxcb-xfixes0, libxcb-xkb1,
 libwayland-client0, libwayland-cursor0, libwayland-egl1
Recommends: mesa-vulkan-drivers | nvidia-driver
Maintainer: LegendsOnLinux <noreply@github.com>
Homepage: https://github.com/mdx0111/LegendsOnLinux
Description: Download and play Minecraft Legends (Windows edition) on Linux
 LegendsOnLinux downloads Minecraft Legends from Microsoft for an account
 that owns the Windows edition, and runs it with a patched WineGDK engine.
 It signs the game in to Xbox Live and keeps its saves on this computer.
 .
 The engine, the Steam Linux Runtime and xodus-cli are downloaded (SHA-256
 pinned) on first use. You need to own the game; no game files are included.
EOF

# Reproducible-ish: fixed mtimes and owners.
epoch=${SOURCE_DATE_EPOCH:-$(git -C "$src" log -1 --format=%ct 2>/dev/null || date +%s)}
find "$pkg" -exec touch -h -d "@$epoch" {} +
mkdir -p "$out"
deb=$out/${name}_${version}-${revision}_amd64.deb
dpkg-deb --root-owner-group -Zxz --build "$pkg" "$deb" >/dev/null
(cd "$out" && sha256sum "$(basename "$deb")" > SHA256SUMS-deb)
echo ":: built $deb ($(du -h "$deb" | cut -f1), installed ${size} KiB)"
