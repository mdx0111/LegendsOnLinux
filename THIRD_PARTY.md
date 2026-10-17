# Third-party components

## BedrockOnLinux — MIT
https://github.com/Wyze3306/BedrockOnLinux (commit f976cd5)

- `legends_on_linux/wine_registry.py` is vendored from `bol/wine_registry.py`.
- The Xbox Live token chain in `legends_on_linux/auth.py` and the
  `xodus-cli run` wrapper in `legends_on_linux/store.py` are ported from
  `bol/auth.py` and `bol/xodus.py`.
- At runtime the launcher downloads BedrockOnLinux's published builds: the
  WineGDK engine (`engine-wow64-archs-native20`), xodus-cli
  (`xodus-64d39eb87a56-p5`) and the OpenSSL XCurl set (`xcurl-504bb166e4e7`).
  Each is pinned by SHA-256.

    Copyright (c) 2026 BedrockOnLinux contributors
    (MIT licence text: see LICENSE; identical terms.)

## WineGDK — LGPL-2.1-or-later
https://github.com/Weather-OS/WineGDK (commit 75637b6)

`engine/patches/*.patch` modify WineGDK and are distributed under the
LGPL-2.1-or-later, like the files they change.
`scripts/build-xgameruntime.sh` builds `xgameruntime.dll` from WineGDK source.
It applies BedrockOnLinux's native5 patches (shipped inside its engine) and
then these patches.

## Xodus — GPL-3.0
https://github.com/xodus-gaming/xodus

`xodus-cli` is downloaded and run as a separate program; no Xodus code is
linked into or copied into this project.

## umu-launcher — GPL-3.0
https://github.com/Open-Wine-Components/umu-launcher

Downloaded and run as a separate program (pinned by SHA-256).

## Application icon
`data/icons/` (all sizes, scaled with nearest-neighbour from the 512×512
original) is the Minecraft Legends icon
[#49024 on SteamGridDB](https://www.steamgriddb.com/icon/49024), uploaded by
TheWaslijn. SteamGridDB lists it as "official" style: it is based on Mojang's
artwork for the game. Minecraft and Minecraft Legends are trademarks of
Microsoft/Mojang; the icon is not covered by this project's MIT licence.

## PySide6 and Qt (in the .deb only) — LGPL-3.0
https://pypi.org/project/PySide6-Essentials/

The `.deb` bundles the PySide6-Essentials and shiboken6 6.11.2 wheels
(pinned by hash in `third_party/requirements-deb.txt`) under
`/usr/lib/legends-on-linux/vendor`, with unused Qt modules removed.
