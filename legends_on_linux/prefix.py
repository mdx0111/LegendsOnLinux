"""legends_on_linux.prefix — the Wine prefix the game runs in."""
# SPDX-License-Identifier: MIT

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import config as C
from .deps import engine_dll_target, ensure_umu
from .util import LolError, info, ok, sha256_file
from .wine_registry import reg_delete, reg_dword, reg_sz, update_prefix_registry


def system32():
    return C.PFX / "drive_c" / "windows" / "system32"


def prefix_processes(prefix: Path = C.PFX):
    """PIDs of processes running Wine in ``prefix``."""
    wanted = {str(prefix), str(prefix.parent)}
    pids = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            environ = (proc / "environ").read_bytes().split(b"\0")
        except OSError:
            continue
        for item in environ:
            if item.startswith(b"WINEPREFIX=") and \
                    os.fsdecode(item[11:]).rstrip("/") in wanted:
                pids.append(int(proc.name))
                break
    return pids


def require_prefix_idle(prefix: Path, action="modify the Wine prefix"):
    if prefix_processes(Path(prefix)):
        raise LolError(f"Minecraft Legends is still running; cannot {action}. Close it first.")


def umu_command(exe, args=(), extra_env=None):
    """argv and environment that run ``exe`` with our engine in our prefix."""
    environment = os.environ.copy()
    environment.update({
        "PROTONPATH": str(C.ENGINE),
        "WINEPREFIX": str(C.COMPAT),
        "GAMEID": "umu-legends-on-linux",
        "PROTON_VERB": "run",
        # umu appends "umu" to this: the runtime lives in C.UMU_DIR.
        "UMU_FOLDERS_PATH": str(C.DATA),
        "UMU_RUNTIME_UPDATE": "0",
        "PROTON_USE_WOW64": "1",
    })
    environment.update(extra_env or {})
    return [sys.executable, str(ensure_umu()), str(exe), *args], environment


def ensure_prefix():
    """Create the prefix on first use, then bring its runtime up to date."""
    if not (C.PFX / ".lol-ready").is_file():
        create_prefix()
    sync_runtime()


def create_prefix(timeout=1200):
    """Build the prefix with one `wineboot -u`.

    The first run also downloads the Steam Linux Runtime, hence the generous
    timeout. A prefix that did not finish is thrown away rather than used.
    """
    seed_cryptbase()
    shutil.rmtree(C.COMPAT, ignore_errors=True)
    info("Creating the Wine prefix (one-time; the first run also fetches the "
         "Steam Linux Runtime, about 900 MB) …")
    cmd, environment = umu_command("wineboot", ["-u"], {
        "WINEDEBUG": "-all", "WINEDLLOVERRIDES": "cryptbase=n,b"})
    C.LOGS.mkdir(parents=True, exist_ok=True)
    log_path = C.LOGS / "prefix-setup.log"
    failure = None
    with open(log_path, "wb") as log:
        proc = subprocess.Popen(cmd, env=environment, stdout=log, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
        try:
            if proc.wait(timeout=timeout) != 0:
                failure = f"wineboot exited with status {proc.returncode}"
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            failure = f"wineboot did not finish within {timeout} seconds"
    stop_wineserver()
    if not failure and b"unimplemented function" in log_path.read_bytes():
        failure = "Wine aborted on an unimplemented function"
    if failure or not (C.PFX / "system.reg").is_file():
        raise LolError(f"Creating the Wine prefix failed: {failure or 'no registry'}. "
                       f"See {log_path}")
    (C.PFX / ".lol-ready").write_text(C.ENGINE_REV + "\n")
    ok("Wine prefix created")


def seed_cryptbase():
    """Put the cryptbase stub into the engine's template prefix.

    advapi32 forwards RtlGenRandom (SystemFunction036) to cryptbase, which
    this engine does not implement, so Wine aborts on the first random number
    -- wineboot included -- unless a real cryptbase.dll is in system32.
    Proton builds every new prefix from default_pfx, so the stub has to be
    there before the first wineboot.
    """
    stub = C.XCURL_SET / "cryptbase.dll"
    template = C.ENGINE / "files" / "share" / "default_pfx" / "drive_c" / "windows" / "system32"
    if stub.is_file() and template.is_dir():
        _copy_if_different(stub, template / "cryptbase.dll")


def stop_wineserver(grace=30):
    """Wait for the prefix's processes, which outlive wineboot by seconds.

    They run inside the Steam Linux Runtime container, so they are found by
    their WINEPREFIX rather than asked to quit through a wineserver binary.
    """
    deadline = time.monotonic() + grace
    while prefix_processes() and time.monotonic() < deadline:
        time.sleep(0.5)
    for pid in prefix_processes():
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def _copy_if_different(source: Path, target: Path):
    if target.is_file() and sha256_file(source) == sha256_file(target):
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name("." + target.name + ".lol-new")
    shutil.copy2(source, tmp)
    os.replace(tmp, target)
    return True


def sync_runtime():
    """Files the prefix needs that the engine does not put there itself.

    * xgameruntime.dll: Proton copies engine DLLs into a prefix only when it
      upgrades it, so a rebuilt one has to be carried over by hand.
    * cryptbase.dll: advapi32 forwards RtlGenRandom (SystemFunction036) to it,
      and GDK-Proton's override wants a real file there; without it every
      process aborts on its first random number.
    """
    if _copy_if_different(engine_dll_target(), system32() / C.XGAMERUNTIME):
        ok("Prefix updated with the Legends xgameruntime.dll")
    cryptbase = C.XCURL_SET / "cryptbase.dll"
    if not cryptbase.is_file():
        cryptbase = C.ENGINE / "files/lib/wine/x86_64-windows/cryptbase.dll"
    _copy_if_different(cryptbase, system32() / "cryptbase.dll")


def write_registry(refresh_token):
    """WineGDK prerequisites, written while the prefix is offline.

    ConsoleMode 8 selects the console code path in XSAPI; the TLS values keep
    Wine's Schannel on TLS 1.2, which Azure accepts; RefreshToken is where
    WineGDK's XUser looks for the signed-in account.
    """
    machine = [
        reg_dword(r"Software\Microsoft\Windows NT\CurrentVersion\OEM", "ConsoleMode", 8),
        reg_dword(r"Software\Microsoft\Windows\CurrentVersion\Internet Settings\WinHttp",
                  "DefaultSecureProtocols", 2560),
        reg_dword(r"Software\Microsoft\SchannelTLS\Protocols\TLS 1.3\Client",
                  "DisabledByDefault", 1),
    ]
    if refresh_token:
        machine.append(reg_sz(C.WINEGDK_REG, "RefreshToken", refresh_token))
    else:
        machine.append(reg_delete(C.WINEGDK_REG, "RefreshToken"))
    user = [reg_sz("Environment", name, "0") for name in (
        "MICROSOFT_WINDOWSAPPRUNTIME_BOOTSTRAP_INITIALIZE_SHOWUI",
        "MICROSOFT_WINDOWSAPPRUNTIME_BOOTSTRAP_INITIALIZE_FAILFAST",
        "MICROSOFT_WINDOWSAPPRUNTIME_DEPLOYMENT_INITIALIZE_ONERRORSHOWUI")]
    update_prefix_registry(C.PFX, machine=machine, user=user)


def saves_dir():
    """Where the XGameSave implementation keeps this prefix's saves."""
    users = C.PFX / "drive_c" / "users"
    for user in ("steamuser", os.environ.get("USER", "")):
        path = users / user / "AppData" / "Local" / "WineGDK" / "XGameSave"
        if user and path.is_dir():
            return path
    return users / "steamuser" / "AppData" / "Local" / "WineGDK" / "XGameSave"
