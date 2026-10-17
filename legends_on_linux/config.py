"""legends_on_linux.config — constants, paths and pinned downloads (no logic)."""
# SPDX-License-Identifier: MIT

import os
from pathlib import Path

APP = "legends-on-linux"
APP_ID = "io.github.mdx0111.LegendsOnLinux"
PRETTY = "LegendsOnLinux"
VERSION = "0.1.1"

# Desktop file, metainfo and icons. Checkouts and distribution packages both
# keep data/ beside the legends_on_linux package.
ASSETS = Path(__file__).resolve().parent.parent / "data"

HOME = Path.home()
# Inside the Flatpak, XDG_DATA_HOME points into ~/.var/app; the launcher keeps
# using ~/.local/share/legends-on-linux (the manifest grants it) so the rpm,
# deb and Flatpak share one sign-in, game and set of saves. A second Store
# sign-in would register another device, and an account may only have ten.
FLATPAK = bool(os.environ.get("FLATPAK_ID")) or Path("/.flatpak-info").is_file()
_DATA_ROOT = (HOME / ".local" / "share" if FLATPAK else
              Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local" / "share"))
DATA = Path(os.environ.get("LOL_HOME") or _DATA_ROOT / APP).expanduser()

CACHE = DATA / "cache"
LOGS = DATA / "logs"
ENGINE = DATA / "engine" / "GDK-Proton-legends"
ENGINE_OVERLAY = DATA / "engine-overlay"
UMU_DIR = DATA / "umu"
XODUS_DIR = DATA / "xodus"
XODUS_HOME = DATA / "xodus-home"
XCURL_SET = DATA / "xcurl" / "openssl-set"
# Proton keeps the Wine prefix in a "pfx" folder inside the one it is given.
COMPAT = DATA / "prefix"
PFX = COMPAT / "pfx"
ACCOUNT = DATA / "account"
PREAUTH = ACCOUNT / "device.json"
RUN = DATA / "run"
SETTINGS = DATA / "settings.json"
DEFAULT_GAME_DIR = DATA / "game"

# --- Minecraft Legends -------------------------------------------------------
# From the package's MicrosoftGame.config.
PRODUCT_ID = "9N98Z825TNFW"
TITLE_ID = 0x61B215AE
EXE_NAME = "MinecraftLegends.Windows.exe"
PACKAGE_CACHE = ".xodus-streaming.msixvc"

# --- Engine: BedrockOnLinux's published WineGDK build ------------------------
# Built from Weather-OS/WineGDK 75637b6 plus BoL's native5 patches; it carries
# the ntdll loader patches that let `xodus-cli run` hand Wine a decrypted
# executable. engine/patches/ in this repository adds what Legends needs on top
# (a license answer and XGameSave) through a rebuilt xgameruntime.dll.
ENGINE_REV = "wow64-archs-native20"
ENGINE_ASSET = f"GDK-Proton-xuser-{ENGINE_REV}.tar.gz"
ENGINE_URL = ("https://github.com/Wyze3306/BedrockOnLinux/releases/download/"
              f"engine-{ENGINE_REV}/{ENGINE_ASSET}")
ENGINE_SHA256 = "2f30533b249954438bf6b425631539c8d8036261ce25cffa0d1ea5d30f1d3e27"
WINEGDK_REPO = "https://github.com/Weather-OS/WineGDK.git"
WINEGDK_COMMIT = "75637b674e1f191e65753663c4c0c32bea05ba6e"
XGAMERUNTIME = "xgameruntime.dll"
# Our xgameruntime.dll: WINEGDK_COMMIT + BoL's native5 patches + engine/patches,
# built by scripts/build-xgameruntime.sh and published as a release of this
# repository. A new build gets a new rev; published bytes are never replaced.
XGAMERUNTIME_REV = "legends-1"
XGAMERUNTIME_ASSET = f"xgameruntime-{XGAMERUNTIME_REV}.dll"
XGAMERUNTIME_URL = ("https://github.com/mdx0111/LegendsOnLinux/releases/download/"
                    f"xgameruntime-{XGAMERUNTIME_REV}/{XGAMERUNTIME_ASSET}")
XGAMERUNTIME_SHA256 = "9eda926e5718aa6f914908eaf696eb4c82c71766e3f9e55d2a64952442e4147d"

# --- umu-launcher (Steam Linux Runtime) --------------------------------------
UMU_VERSION = "1.4.3"
UMU_ASSET = f"umu-launcher-{UMU_VERSION}-zipapp.tar"
UMU_URL = ("https://github.com/Open-Wine-Components/umu-launcher/releases/"
           f"download/{UMU_VERSION}/{UMU_ASSET}")
UMU_ARCHIVE_SHA256 = "3f8fdc033f547afdb3408ea48ad07194769405148dcfa2b2f945b7fb368a33bb"
UMU_RUN_SHA256 = "577181dbff2eccdaa78b411c0fd1aa7fde574028449c3e0e99f508536a76870e"

# --- Xodus: Store sign-in, licence, download and decryption ------------------
# https://github.com/xodus-gaming/xodus (GPL-3.0), as built and published by
# BedrockOnLinux (commit 64d39eb plus its licensing patches).
XODUS_REV = "64d39eb87a56-p5"
XODUS_ASSET = f"xodus-cli-{XODUS_REV}.tar.gz"
XODUS_URL = ("https://github.com/Wyze3306/BedrockOnLinux/releases/download/"
             f"xodus-{XODUS_REV}/{XODUS_ASSET}")
XODUS_SHA256 = "bb507341bcd2eb56406e9aafab2a58978510b396df5d51a577bb0ba08560f8d8"

# --- OpenSSL XCurl: PlayFab over OpenSSL instead of Wine's Schannel ----------
XCURL_REV = "504bb166e4e7"
XCURL_ASSET = f"openssl-xcurl-set-{XCURL_REV}.tar.gz"
XCURL_URL = ("https://github.com/Wyze3306/BedrockOnLinux/releases/download/"
             f"xcurl-{XCURL_REV}/{XCURL_ASSET}")
XCURL_SHA256 = "504bb166e4e737ad81c3ac8e7a917740b28478f69acd89e538c3bf921c29523f"
CACERT_URL = "https://curl.se/ca/cacert.pem"

# --- Xbox Live sign-in for the game ------------------------------------------
# WineGDK's XUser refreshes the token it finds in the registry with this MSA
# application ID, so the device-code sign-in has to use the same one.
MSA_CLIENT_ID = "0000000048183522"
MSA_SCOPE = "service::user.auth.xboxlive.com::MBI_SSL"
MSA_CONNECT = "https://login.live.com/oauth20_connect.srf"
MSA_TOKEN = "https://login.live.com/oauth20_token.srf"
WINEGDK_REG = r"Software\Wine\WineGDK"
# The audiences Legends asks WineGDK for. PlayFab is Minecraft's shared
# PlayFab relying party, which Legends requests as well.
RP_XBOXLIVE = "http://xboxlive.com"
RP_PLAYFAB = "https://b980a380.minecraft.playfabapi.com/"
RP_LICENSING = "http://licensing.xboxlive.com"
