#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# Build the LegendsOnLinux Flatpak from this working tree into
# dist/LegendsOnLinux-<version>-x86_64.flatpak.
#
#   scripts/build-flatpak.sh            # build the bundle
#   scripts/build-flatpak.sh --install  # also install it for this user
#
# Needs flatpak, and either flatpak-builder or the org.flatpak.Builder app:
#   flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
#   flatpak install --user flathub org.flatpak.Builder org.gnome.Platform//51 org.gnome.Sdk//51
set -euo pipefail

src=$(cd "$(dirname "$0")/.." && pwd)
app_id=io.github.mdx0111.LegendsOnLinux
version=$(grep -m1 '^VERSION = ' "$src/legends_on_linux/config.py" | cut -d'"' -f2)
out=${OUTDIR:-$src/dist}
work=${FLATPAK_WORK:-$src/.flatpak-build}
install=false
for arg in "$@"; do
    case $arg in
        --install) install=true ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

if command -v flatpak-builder >/dev/null; then
    builder=(flatpak-builder)
elif flatpak info org.flatpak.Builder >/dev/null 2>&1; then
    builder=(flatpak run --filesystem="$src" --filesystem="$out" --filesystem="$work"
             org.flatpak.Builder)
else
    echo "flatpak-builder missing: flatpak install --user flathub org.flatpak.Builder" >&2
    exit 1
fi

mkdir -p "$out" "$work"
"${builder[@]}" --user --force-clean --disable-rofiles-fuse \
    --state-dir="$work/state" --repo="$work/repo" \
    --install-deps-from=flathub \
    "$work/build" "$src/flatpak/$app_id.yml"

bundle=$out/LegendsOnLinux-$version-x86_64.flatpak
flatpak build-bundle --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo \
    "$work/repo" "$bundle" "$app_id"
(cd "$out" && sha256sum "$(basename "$bundle")" > SHA256SUMS-flatpak)
echo ":: built $bundle ($(du -h "$bundle" | cut -f1))"

if $install; then
    flatpak install --user --noninteractive -y --reinstall "$bundle"
    echo ":: installed; run: flatpak run $app_id"
fi
