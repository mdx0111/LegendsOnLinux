#!/bin/bash
# SPDX-License-Identifier: MIT
# Runs inside a clean container with dist/ mounted at /out: install what a
# desktop session normally has, then check the AppImage's CLI and window and
# list anything its Qt cannot find.
set -e
if command -v apt-get >/dev/null; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    glib=$(apt-cache show libglib2.0-0t64 >/dev/null 2>&1 && echo libglib2.0-0t64 || echo libglib2.0-0)
    apt-get install -y -qq --no-install-recommends "$glib" libgl1 libegl1 libfontconfig1 \
        libxkbcommon0 libxkbcommon-x11-0 libdbus-1-3 libx11-xcb1 libxcb-cursor0 libxcb-icccm4 \
        libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xkb1 \
        libwayland-client0 libwayland-cursor0 libwayland-egl1 ca-certificates >/dev/null 2>&1
else
    dnf -y -q install mesa-libGL mesa-libEGL fontconfig libxkbcommon-x11 dbus-libs xcb-util-cursor \
        xcb-util-wm xcb-util-image xcb-util-keysyms xcb-util-renderutil libwayland-client \
        libwayland-cursor libwayland-egl ca-certificates >/dev/null 2>&1
fi
. /etc/os-release; echo "== $PRETTY_NAME"
cp /out/LegendsOnLinux-*-x86_64.AppImage /tmp/app.AppImage
export APPIMAGE_EXTRACT_AND_RUN=1
/tmp/app.AppImage --help >/dev/null && echo "cli: ok"
QT_QPA_PLATFORM=offscreen timeout 20 /tmp/app.AppImage gui >/tmp/gui.log 2>&1 & pid=$!
sleep 8
if kill -0 $pid 2>/dev/null; then echo "gui: window running"; kill $pid; else echo "gui: exited early"; tail -5 /tmp/gui.log; fi
root=$(ls -d /tmp/appimage_extracted_*/ 2>/dev/null | head -1)
missing=$(cd "$root/usr/python/lib/python3.12/site-packages/PySide6" && for so in Qt/plugins/platforms/libqxcb.so Qt/plugins/platforms/libqwayland.so Qt/lib/*.so* *.abi3.so; do ldd "$so" 2>/dev/null | grep "not found"; done | sort -u)
echo "unresolved: ${missing:-none}"
