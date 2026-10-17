"""legends_on_linux.launch — start Minecraft Legends."""
# SPDX-License-Identifier: MIT

import os
import shutil
from pathlib import Path

from . import auth, deps, prefix, store
from . import config as C
from .util import LolError, info, load_settings, ok, warn


def game_dir():
    configured = load_settings().get("game_dir")
    return Path(configured).expanduser() if configured else C.DEFAULT_GAME_DIR


def install_xcurl(directory: Path):
    """Route the game's HTTP over OpenSSL instead of Wine's Schannel.

    Azure Front Door drops Wine's TLS handshakes, so PlayFab and the Minecraft
    services never answer. The set's XCurl.dll is a shim that injects a CA
    bundle and forwards to the real OpenSSL libcurl (xcurl_real.dll). All 16
    curl functions Legends imports are among the ones it exports.
    """
    xcurl = C.XCURL_SET
    original = directory / "XCurl.dll.lol-orig"
    if (directory / "XCurl.dll").is_file() and not original.exists():
        shutil.copy2(directory / "XCurl.dll", original)
    for dll in xcurl.glob("*.dll"):
        if dll.name not in ("cryptbase.dll", "xcurl-cashim.dll"):
            shutil.copy2(dll, directory / dll.name)
    shutil.copy2(xcurl / "libcurl-4.dll", directory / "xcurl_real.dll")
    shutil.copy2(xcurl / "xcurl-cashim.dll", directory / "XCurl.dll")
    shutil.copy2(C.CACHE / "cacert.pem", directory / "cacert.pem")


def _container_paths(directory: Path):
    """Paths outside $HOME the Steam Linux Runtime container must see."""
    home = Path.home().resolve()
    resolved = directory.resolve()
    if resolved == home or home in resolved.parents:
        return []
    return [str(resolved)]


def build(offline=False, debug=False):
    """Prepare everything and return (argv, environment) for the game."""
    directory = game_dir()
    if not store.installed(directory):
        raise LolError(f"Minecraft Legends is not installed in {directory}. "
                       "Run:  legends-on-linux install")
    deps.ensure_all()
    prefix.require_prefix_idle(C.PFX, "start the game")
    prefix.ensure_prefix()
    install_xcurl(directory)

    preauth_path = None
    refresh_token = None
    if offline:
        warn("Starting signed out: the GDK build of Legends stops at its sign-in dialog.")
    elif not auth.signed_in():
        raise LolError("No Xbox Live account is linked for the game. Run:  legends-on-linux login")
    else:
        preauth_path = auth.preauth()
        refresh_token = auth.current_refresh_token()
    prefix.write_registry(refresh_token)

    exe = directory / C.EXE_NAME
    cmd, environment = prefix.umu_command(exe)
    environment.update({
        "WINEDLLOVERRIDES": "cryptbase=n,b;amd_ags_x64=;vrclient=;vrclient_x64=;"
                            "openvr_api=;wineopenxr=",
        "WINEDEBUG": environment.get("WINEDEBUG") or ("+gdkc,+xgameruntime,fixme-all"
                                                      if debug else "-all"),
        "MICROSOFT_WINDOWSAPPRUNTIME_BOOTSTRAP_INITIALIZE_SHOWUI": "0",
        "MICROSOFT_WINDOWSAPPRUNTIME_BOOTSTRAP_INITIALIZE_FAILFAST": "0",
    })
    # Wine's Schannel only stays on TLS 1.2 without this variable.
    environment.pop("GNUTLS_SYSTEM_PRIORITY_FILE", None)
    if preauth_path:
        environment["WINEGDK_PREAUTH_DEVICE"] = preauth_path
    shared = _container_paths(directory)
    if shared:
        environment["PRESSURE_VESSEL_FILESYSTEMS_RW"] = ":".join(
            shared + [p for p in environment.get("PRESSURE_VESSEL_FILESYSTEMS_RW", "").split(":") if p])
    if debug:
        C.LOGS.mkdir(parents=True, exist_ok=True)
        environment.update(PROTON_LOG="1", PROTON_LOG_DIR=str(C.LOGS), XCURL_LOG="1")
        info(f"Debug logs: {C.LOGS} and {directory / 'xcurl.log'}")

    if store.exe_encrypted(directory):
        cmd = store.wrap_launch(cmd, directory, environment)
    else:
        info("The game executable is not encrypted; starting it directly.")
    return cmd, environment, directory


def play(offline=False, debug=False):
    cmd, environment, directory = build(offline=offline, debug=debug)
    ok("Starting Minecraft Legends …")
    os.chdir(directory)
    os.execvpe(cmd[0], cmd, environment)
