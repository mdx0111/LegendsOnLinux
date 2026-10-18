#!/bin/bash
# SPDX-License-Identifier: MIT
#
# Install-test the packages in dist/ in clean containers (podman or docker):
#   tests/packaging/run.sh            # .deb and AppImage
#   tests/packaging/run.sh deb        # one of them
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
dist=$(cd "$here/../.." && pwd)/dist
engine=$(command -v podman || command -v docker)
what=${1:-all}
run() {  # image script
    "$engine" run --rm -v "$dist:/out:ro,Z" -v "$here/$2:/test.sh:ro,Z" "docker.io/library/$1" /test.sh 2>&1 \
        | grep -E "^==|^cli:|^gui:|^unresolved|^error"
}
if [[ $what == all || $what == deb ]]; then
    echo "#### .deb"
    for image in ubuntu:22.04 ubuntu:24.04 debian:trixie; do run "$image" in-container-deb.sh; done
fi
if [[ $what == all || $what == appimage ]]; then
    echo "#### AppImage"
    for image in ubuntu:22.04 ubuntu:24.04 debian:trixie fedora:44; do run "$image" in-container-appimage.sh; done
fi
