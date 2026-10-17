"""legends_on_linux.deps — the pinned components the launcher runs on.

Every archive is checked against a SHA-256 pin before anything in it is used.
The engine is BedrockOnLinux's published WineGDK build with one file replaced:
xgameruntime.dll, rebuilt from the same source plus engine/patches/.
"""
# SPDX-License-Identifier: MIT

import os
import shutil
import tempfile
from pathlib import Path

from . import config as C
from .util import LolError, download, info, ok, replace_dir, safe_extract, sha256_file, warn

PROJECT = Path(__file__).resolve().parent.parent


def _marker_ok(directory: Path, rev: str):
    try:
        return (directory / ".lol-rev").read_text().strip() == rev
    except OSError:
        return False


def _mark(directory: Path, rev: str):
    (directory / ".lol-rev").write_text(rev + "\n")


# ---------------------------------------------------------------- umu

def ensure_umu():
    umu_run = C.UMU_DIR / "umu-run"
    if umu_run.is_file() and sha256_file(umu_run) == C.UMU_RUN_SHA256:
        return umu_run
    archive = download(C.UMU_URL, C.CACHE / C.UMU_ASSET, "umu-launcher", C.UMU_ARCHIVE_SHA256)
    staging = Path(tempfile.mkdtemp(prefix=".umu-", dir=C.CACHE))
    try:
        safe_extract(archive, staging)
        source = next((p for p in staging.rglob("umu-run") if p.is_file()), None)
        if not source or sha256_file(source) != C.UMU_RUN_SHA256:
            raise LolError("umu-launcher archive does not contain the pinned umu-run.")
        C.UMU_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, umu_run)
        umu_run.chmod(0o755)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    ok(f"umu-launcher {C.UMU_VERSION} ready")
    return umu_run


# ---------------------------------------------------------------- xodus

def xodus_bin():
    return C.XODUS_DIR / "xodus-cli"


def ensure_xodus():
    binary = xodus_bin()
    if binary.is_file() and _marker_ok(C.XODUS_DIR, C.XODUS_REV):
        return binary
    archive = download(C.XODUS_URL, C.CACHE / C.XODUS_ASSET, "xodus-cli", C.XODUS_SHA256)
    staging = Path(tempfile.mkdtemp(prefix=".xodus-", dir=C.CACHE))
    try:
        safe_extract(archive, staging)
        if not (staging / "xodus-cli").is_file():
            raise LolError("The xodus-cli archive contains no xodus-cli binary.")
        (staging / "xodus-cli").chmod(0o755)
        _mark(staging, C.XODUS_REV)
        replace_dir(staging, C.XODUS_DIR)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    ok(f"xodus-cli {C.XODUS_REV} ready")
    return binary


# ---------------------------------------------------------------- OpenSSL XCurl

def ensure_xcurl_set():
    if (C.XCURL_SET / "xcurl-cashim.dll").is_file() and _marker_ok(C.XCURL_SET, C.XCURL_REV):
        return C.XCURL_SET
    archive = download(C.XCURL_URL, C.CACHE / C.XCURL_ASSET, "OpenSSL XCurl", C.XCURL_SHA256)
    staging = Path(tempfile.mkdtemp(prefix=".xcurl-", dir=C.CACHE))
    try:
        safe_extract(archive, staging)
        found = next((p.parent for p in staging.rglob("xcurl-cashim.dll")), None)
        if not found or not (found / "libcurl-4.dll").is_file():
            raise LolError("The OpenSSL XCurl archive is incomplete.")
        _mark(found, C.XCURL_REV)
        replace_dir(found, C.XCURL_SET)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    cacert = C.CACHE / "cacert.pem"
    download(C.CACERT_URL, cacert, "CA certificates")
    ok("OpenSSL XCurl ready")
    return C.XCURL_SET


# ---------------------------------------------------------------- engine

def engine_dll_target():
    return C.ENGINE / "files" / "lib" / "wine" / "x86_64-windows" / C.XGAMERUNTIME


def native5_patch_dir(root: Path = C.ENGINE):
    """BoL ships the source delta of its engine inside the engine itself."""
    return root / "files/share/bedrock-on-linux/licenses-and-provenance/winegdk/native5"


def local_xgameruntime():
    """A development build, when one is asked for or has been made."""
    for candidate in (os.environ.get("LOL_XGAMERUNTIME_DLL"),
                      C.ENGINE_OVERLAY / C.XGAMERUNTIME,
                      PROJECT / "build" / C.XGAMERUNTIME):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def pinned_xgameruntime():
    return C.ENGINE_OVERLAY / C.XGAMERUNTIME_ASSET


def xgameruntime_dll():
    """The xgameruntime.dll to install into the engine.

    LOL_XGAMERUNTIME_DLL wins; otherwise the published, SHA-256-pinned build
    is downloaded. A local build (scripts/build-xgameruntime.sh) is used only
    when that download is not possible.
    """
    override = os.environ.get("LOL_XGAMERUNTIME_DLL")
    if override:
        if not Path(override).is_file():
            raise LolError(f"LOL_XGAMERUNTIME_DLL does not exist: {override}")
        return Path(override)
    try:
        return download(C.XGAMERUNTIME_URL, pinned_xgameruntime(),
                        f"Legends engine patch ({C.XGAMERUNTIME_REV})", C.XGAMERUNTIME_SHA256)
    except LolError as exc:
        local = local_xgameruntime()
        if local:
            warn(f"{exc}. Using the local build {local} instead.")
            return local
        raise LolError(f"{exc}\nYou can also build it yourself with "
                       "scripts/build-xgameruntime.sh.") from exc


def ensure_engine():
    """Install the base engine, then put our xgameruntime.dll into it."""
    if not ((C.ENGINE / "proton").is_file() and _marker_ok(C.ENGINE, C.ENGINE_REV)):
        archive = download(C.ENGINE_URL, C.CACHE / C.ENGINE_ASSET,
                           f"game engine {C.ENGINE_REV} (~820 MiB)", C.ENGINE_SHA256)
        info("Extracting the game engine …")
        C.ENGINE.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".engine-", dir=C.ENGINE.parent))
        try:
            safe_extract(archive, staging)
            root = next((p.parent for p in staging.rglob("proton")
                         if p.is_file() and (p.parent / "files").is_dir()), None)
            if not root:
                raise LolError("The engine archive contains no Proton tree.")
            _mark(root, C.ENGINE_REV)
            replace_dir(root, C.ENGINE)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        ok(f"Game engine {C.ENGINE_REV} installed")
    install_xgameruntime()
    return C.ENGINE


def xgameruntime_installed():
    """Whether the engine carries the Legends xgameruntime.dll (no network)."""
    target = engine_dll_target()
    if not target.is_file():
        return False
    installed = sha256_file(target)
    override = os.environ.get("LOL_XGAMERUNTIME_DLL")
    if override and Path(override).is_file():
        return installed == sha256_file(Path(override))
    local = local_xgameruntime()
    return installed == C.XGAMERUNTIME_SHA256 or bool(local and installed == sha256_file(local))


def install_xgameruntime():
    dll = xgameruntime_dll()
    target = engine_dll_target()
    if target.is_file() and sha256_file(dll) == sha256_file(target):
        return target
    shutil.copy2(dll, target)
    ok(f"Engine patched with the Legends xgameruntime.dll ({dll.name})")
    return target


def ensure_all():
    ensure_umu()
    ensure_xodus()
    ensure_xcurl_set()
    ensure_engine()
