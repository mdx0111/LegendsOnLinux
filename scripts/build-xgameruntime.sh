#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# Build the Minecraft Legends xgameruntime.dll.
#
# Source: Weather-OS/WineGDK at the commit BedrockOnLinux's engine is built
# from, plus BedrockOnLinux's native5 patches 0002-0011 (taken from the
# engine, which ships them), plus engine/patches/ from this repository.
# Only the one PE module is compiled; the result goes to
#   ${LOL_HOME:-~/.local/share/legends-on-linux}/engine-overlay/xgameruntime.dll
#
# Needs: git, gcc, make, flex, bison, x86_64-w64-mingw32-gcc.
# On Fedora:  sudo dnf install git gcc make flex bison mingw64-gcc
set -euo pipefail

here=$(cd "$(dirname "$0")/.." && pwd)
data=${LOL_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/legends-on-linux}
src=$data/src
commit=75637b674e1f191e65753663c4c0c32bea05ba6e
native5=$data/engine/GDK-Proton-legends/files/share/bedrock-on-linux/licenses-and-provenance/winegdk/native5
jobs=${JOBS:-$(nproc)}

for tool in git gcc make flex bison x86_64-w64-mingw32-gcc; do
    command -v "$tool" >/dev/null || { echo "missing build tool: $tool" >&2; exit 1; }
done
if [ ! -f "$native5/SOURCE-SHA256SUMS" ]; then
    echo "The game engine is not installed yet; run:  legends-on-linux setup" >&2
    echo "(the build takes BedrockOnLinux's engine patches from it)" >&2
    exit 1
fi

mkdir -p "$src"
if [ ! -d "$src/winegdk/.git" ]; then
    git init -q "$src/winegdk"
    git -C "$src/winegdk" remote add origin https://github.com/Weather-OS/WineGDK.git
fi
cd "$src/winegdk"
if [ "$(git rev-parse -q --verify HEAD 2>/dev/null)" != "$commit" ]; then
    git fetch -q --depth 1 origin "$commit"
    git checkout -q --detach FETCH_HEAD
fi
git reset -q --hard "$commit"
git clean -qfdx

# 0001 is already part of $commit.
for p in "$native5"/000[2-9]*.patch "$native5"/001*.patch; do
    git apply "$p"
done
sha256sum --quiet -c "$native5/SOURCE-SHA256SUMS"
echo ":: WineGDK source matches BedrockOnLinux's engine"
for p in "$here"/engine/patches/*.patch; do
    git apply "$p"
    echo ":: applied $(basename "$p")"
done

mkdir -p "$src/build64"
cd "$src/build64"
if [ ! -f Makefile ]; then
    echo ":: configuring (one-time) …"
    ../winegdk/configure --enable-win64 --without-x --without-freetype \
        --without-gstreamer --without-wayland --without-vulkan --without-opengl \
        --without-cups --without-sane --without-gphoto --without-v4l2 --without-pcap \
        --without-usb --without-krb5 --without-netapi --without-pulse --without-alsa \
        --without-oss --without-dbus --without-udev --without-sdl --without-capi \
        --without-gssapi --without-inotify --without-unwind --without-ffmpeg \
        > configure.log 2>&1 || { tail -20 configure.log; exit 1; }
fi
echo ":: building xgameruntime.dll …"
make -j"$jobs" dlls/xgameruntime/x86_64-windows/xgameruntime.dll > make.log 2>&1 \
    || { tail -30 make.log; exit 1; }

mkdir -p "$data/engine-overlay"
install -m 644 dlls/xgameruntime/x86_64-windows/xgameruntime.dll "$data/engine-overlay/"
echo ":: built $data/engine-overlay/xgameruntime.dll"
echo ":: install it with:  LOL_XGAMERUNTIME_DLL=$data/engine-overlay/xgameruntime.dll legends-on-linux setup"
sha256sum "$data/engine-overlay/xgameruntime.dll"
