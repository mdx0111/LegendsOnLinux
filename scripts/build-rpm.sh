#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# Build the LegendsOnLinux .rpm (noarch) and its source rpm into dist/.
#
#   scripts/build-rpm.sh            # from the working tree (tracked + new files)
#   scripts/build-rpm.sh --head     # from the last commit only
#   scripts/build-rpm.sh --head --srpm   # source rpm only (what COPR asks for)
#
# OUTDIR overrides where the packages go (default: dist/).
#
# Needs: rpmbuild (Fedora: sudo dnf install rpm-build).
# The source rpm is what Fedora COPR builds from.
set -euo pipefail

src=$(cd "$(dirname "$0")/.." && pwd)
name=legends-on-linux
app_id=io.github.mdx0111.LegendsOnLinux
version=$(grep -m1 '^VERSION = ' "$src/legends_on_linux/config.py" | cut -d'"' -f2)
release=${RPM_RELEASE:-1}
out=${OUTDIR:-$src/dist}
top=$out/rpmbuild
from_head=false
srpm_only=false
for arg in "$@"; do
    case $arg in
        --head) from_head=true ;;
        --srpm) srpm_only=true ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

command -v rpmbuild >/dev/null || { echo "rpmbuild missing (sudo dnf install rpm-build)" >&2; exit 1; }
[[ "$version" =~ ^[0-9]+(\.[0-9]+)*$ ]] || { echo "bad VERSION in config.py: $version" >&2; exit 1; }

rm -rf "$top"
mkdir -p "$top"/{SOURCES,SPECS,BUILD,RPMS,SRPMS} "$out"

# Source tarball: the files git knows about (and new, unignored ones unless --head).
tarball=$top/SOURCES/$name-$version.tar.gz
cd "$src"
if $from_head; then
    git archive --format=tar.gz --prefix="$name-$version/" -o "$tarball" HEAD
else
    git ls-files -z --cached --others --exclude-standard \
        | while IFS= read -r -d '' f; do [[ -e "$f" ]] && printf '%s\0' "$f"; done \
        | tar --null -T - --transform "s,^,$name-$version/," -czf "$tarball"
fi

cat > "$top/SPECS/$name.spec" <<EOF
Name:           $name
Version:        $version
Release:        $release%{?dist}
Summary:        Download and play Minecraft Legends (Windows edition) on Linux
License:        MIT
URL:            https://github.com/mdx0111/LegendsOnLinux
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  desktop-file-utils
BuildRequires:  /usr/bin/appstreamcli

Requires:       python3 >= 3.10
Requires:       python3-cryptography
Requires:       python3-pyside6
# xodus-cli (downloaded at first run) links WebKitGTK for the Store sign-in
# window and needs it for every launch.
Requires:       webkit2gtk4.1
Requires:       ca-certificates
Requires:       xdg-utils
Recommends:     mesa-vulkan-drivers

%description
LegendsOnLinux downloads Minecraft Legends from Microsoft for an account that
owns the Windows edition, and runs it with a patched WineGDK engine. It signs
the game in to Xbox Live and keeps its saves on this computer. The engine,
the Steam Linux Runtime and xodus-cli are downloaded (SHA-256 pinned) on first
use. You need to own the game; no game files are included.

%prep
%autosetup -n %{name}-%{version}

%build
# Pure Python: nothing to build.

%install
lib=%{buildroot}%{_prefix}/lib/%{name}
install -d "\$lib"
cp -a legends_on_linux data "\$lib/"
install -Dm755 legends-on-linux "\$lib/legends-on-linux"
install -Dm755 scripts/build-xgameruntime.sh "\$lib/scripts/build-xgameruntime.sh"
install -d "\$lib/engine"
cp -a engine/patches "\$lib/engine/"
find "\$lib" -name __pycache__ -prune -exec rm -rf {} +
install -d %{buildroot}%{_bindir}
ln -s ../lib/%{name}/legends-on-linux %{buildroot}%{_bindir}/%{name}
install -Dm644 data/$app_id.desktop %{buildroot}%{_datadir}/applications/$app_id.desktop
install -Dm644 data/$app_id.metainfo.xml %{buildroot}%{_metainfodir}/$app_id.metainfo.xml
for icon in data/icons/hicolor/*/apps/$app_id.png; do
    install -Dm644 "\$icon" "%{buildroot}%{_datadir}/\${icon#data/}"
done

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/$app_id.desktop
appstreamcli validate --no-net %{buildroot}%{_metainfodir}/$app_id.metainfo.xml
PYTHONDONTWRITEBYTECODE=1 %{buildroot}%{_prefix}/lib/%{name}/legends-on-linux --help >/dev/null

%files
%license LICENSE THIRD_PARTY.md
%doc README.md
%{_bindir}/%{name}
%{_prefix}/lib/%{name}/
%{_datadir}/applications/$app_id.desktop
%{_metainfodir}/$app_id.metainfo.xml
%{_datadir}/icons/hicolor/*/apps/$app_id.png

%changelog
* $(LC_ALL=C date -u '+%a %b %d %Y') LegendsOnLinux <noreply@github.com> - $version-$release
- Package version $version
EOF

if $srpm_only; then
    rpmbuild --define "_topdir $top" -bs "$top/SPECS/$name.spec"
    cp "$top"/SRPMS/*.src.rpm "$out/"
else
    rpmbuild --define "_topdir $top" -ba "$top/SPECS/$name.spec"
    cp "$top"/RPMS/noarch/*.rpm "$top"/SRPMS/*.src.rpm "$out/"
    (cd "$out" && sha256sum ./*.rpm > SHA256SUMS-rpm)
fi
rm -rf "$top"
echo ":: built:"
ls -1 "$out"/*.rpm
