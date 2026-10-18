#!/bin/bash
# SPDX-License-Identifier: MIT
# Runs inside a clean Debian/Ubuntu container with dist/ mounted at /out:
# install the .deb with apt, then check the CLI, the window and Qt's libraries.
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq /out/legends-on-linux_*_amd64.deb >/tmp/apt.log 2>&1 || { tail -20 /tmp/apt.log; exit 1; }
. /etc/os-release; echo "== $PRETTY_NAME, python $(python3 -c 'import sys;print(sys.version.split()[0])')"
legends-on-linux --help >/dev/null && echo "cli: ok"
QT_QPA_PLATFORM=offscreen python3 - <<'PY'
import sys
sys.path[:0] = ["/usr/lib/legends-on-linux", "/usr/lib/legends-on-linux/vendor"]
from PySide6.QtWidgets import QApplication
import PySide6, legends_on_linux.gui as gui
app = QApplication([])
w = gui.MainWindow(); w.show(); app.processEvents()
print("gui: window built with PySide6", PySide6.__version__, "from", PySide6.__file__.split("/vendor")[0])
PY
missing=$(cd /usr/lib/legends-on-linux/vendor/PySide6 && for so in Qt/lib/*.so* Qt/plugins/*/*.so *.abi3.so; do ldd "$so" | grep "not found" | sed "s|^|$so: |"; done | sort -u)
echo "unresolved: ${missing:-none}"
