#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# Strip a bundled PySide6 down to what the launcher uses (QtCore, QtGui,
# QtWidgets and the platform plugins).  Used by the .deb and the Flatpak.
#
#   scripts/prune-pyside6.sh <dir containing PySide6/>
set -euo pipefail

pyside=$1/PySide6
qt=$pyside/Qt
[[ -d "$qt/lib" ]] || { echo "no PySide6 in $1" >&2; exit 1; }

# QML/Quick, Designer and translations are most of the wheel.
rm -rf "$pyside"/{Qt/qml,Qt/translations,designer,assistant,linguist,lupdate,lrelease,qmlformat,qmllint,qmlls,qmlimportscanner,qmltyperegistrar,uic,rcc,examples,include,glue,typesystems,scripts}
for module in QtQml QtQuick QtQuickControls2 QtQuickWidgets QtDesigner QtUiTools QtTest QtSql \
              QtNetwork QtOpenGL QtOpenGLWidgets QtXml QtConcurrent QtDBus QtHelp QtPrintSupport \
              QtSvg QtSvgWidgets QtStateMachine; do
    rm -f "$pyside/$module".*.so "$pyside/$module".pyi
done
rm -f "$qt"/lib/libQt6{Qml,Quick,QmlModels,QmlMeta,QmlWorkerScript,QuickControls2,QuickTemplates2,QuickWidgets,QuickShapes,QuickLayouts,QuickParticles,QuickTest,Designer,DesignerComponents,UiTools,Test,Sql,Help,Svg,SvgWidgets,StateMachine,Xml}*.so*

# Then whatever was left depending on what is gone, until nothing changes.
# Only a missing Qt library counts: a missing system library is a missing
# package dependency, for the package's own checks to report.
while :; do
    broken=$(for so in "$qt"/lib/*.so* "$qt"/plugins/*/*.so "$pyside"/*.abi3.so; do
                 [[ -e "$so" ]] || continue
                 if ldd "$so" 2>/dev/null | grep -q 'libQt6[^ ]* => not found'; then echo "$so"; fi
             done)
    [[ -n "$broken" ]] || break
    echo "$broken" | xargs rm -f
done
find "$qt/plugins" -type d -empty -delete

for needed in "$pyside"/QtCore.abi3.so "$pyside"/QtGui.abi3.so "$pyside"/QtWidgets.abi3.so \
              "$qt"/plugins/platforms/libqxcb.so "$qt"/plugins/platforms/libqwayland.so; do
    [[ -e "$needed" ]] || { echo "pruning removed $needed" >&2; exit 1; }
done
