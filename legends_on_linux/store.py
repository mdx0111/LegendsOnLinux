"""legends_on_linux.store — the game itself, through xodus-cli.

xodus-cli (https://github.com/xodus-gaming/xodus, GPL-3.0) signs in to the
user's Microsoft account as a Windows Store device, asks Microsoft's licensing
service for the Minecraft Legends licence, streams the MSIXVC package from the
Xbox CDN and decrypts it. The game executable stays encrypted on disk, as on
Windows; `xodus-cli run` decrypts it into memory at every launch. Nothing here
links Xodus code: it only runs the binary.

The wrapper and the keyring handling follow BedrockOnLinux's bol/xodus.py (MIT).
"""
# SPDX-License-Identifier: MIT

import fcntl
import json
import os
import pty
import re
import signal
import struct
import subprocess
import sys
import termios
from pathlib import Path

from . import config as C
from .deps import ensure_xodus
from .util import LolError, info, ok, progress, progress_done, warn

KEYRING = C.XODUS_HOME / ".xodus-keyring.ron"
# `xodus-cli login` stores the account under these two entries; a keyring
# holding only device credentials is not a sign-in.
_USER_ENTRIES = (b'"user-tokens"', b'"user-DA"')
_NOT_OWNED = re.compile(r"package was not found|is it owned by the user|"
                        r"not entitled to this content", re.I)
_DEVICE_LIMIT = re.compile(r"device group is full", re.I)
_NO_ROOM = re.compile(r"not enough free disk space", re.I)
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def env():
    """xodus-cli keeps its keyring in $HOME, so give it a home of its own.

    Losing that keyring is worse than a sign-out: the next command registers
    a *new* Store device, and an account can only have ten.
    """
    C.XODUS_HOME.mkdir(mode=0o700, parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["HOME"] = str(C.XODUS_HOME)
    for name, sub in (("XDG_DATA_HOME", ".local/share"), ("XDG_CONFIG_HOME", ".config"),
                      ("XDG_CACHE_HOME", ".cache")):
        environment[name] = str(C.XODUS_HOME / sub)
    return environment


def signed_in():
    try:
        blob = KEYRING.read_bytes()
    except OSError:
        return False
    return all(entry in blob for entry in _USER_ENTRIES)


def login():
    binary = ensure_xodus()
    info("Sign in to the Microsoft account that owns Minecraft Legends "
         "(a sign-in window opens).")
    info("The first sign-in registers this PC as a Microsoft Store device; your "
         "system may ask for a password so xodus-cli can read the firmware's "
         "system information. Cancelling that prompt is fine.")
    code, tail = _run([str(binary), "login"])
    if _cancelled:
        raise LolError("The Microsoft Store sign-in was cancelled.")
    if code == 0 and signed_in():
        ok("Microsoft Store account linked")
        return True
    raise LolError(f"The Microsoft Store sign-in did not complete (exit {code})."
                   + (f" {tail[-1]}" if tail else ""))


def logout(device=False):
    binary = ensure_xodus()
    subprocess.run([str(binary), "logout"] + (["--device"] if device else []),
                   env=env(), capture_output=True)
    ok("Microsoft Store account unlinked" + (" and device forgotten" if device else ""))


def _require_sign_in():
    if not signed_in():
        raise LolError("The Microsoft Store account is not linked. Run:  legends-on-linux login --store")


def _explain(output):
    if _NOT_OWNED.search(output):
        return ("Microsoft says this account does not own Minecraft Legends "
                "(Windows Edition). Sign in with the account that bought it.")
    if _DEVICE_LIMIT.search(output):
        return ("This Microsoft account already has ten Store devices. Remove one at "
                "https://account.microsoft.com/devices and try again.")
    if _NO_ROOM.search(output):
        return "There is not enough free disk space for the game (about 12 GB)."
    return None


def latest_version():
    """The Store build Microsoft currently serves, without downloading it."""
    binary = ensure_xodus()
    _require_sign_in()
    result = subprocess.run([str(binary), "download", "--dry-run", C.PRODUCT_ID],
                            env=env(), capture_output=True, text=True, errors="replace")
    output = _ANSI.sub("", result.stdout + result.stderr)
    problem = _explain(output)
    if problem:
        raise LolError(problem)
    match = re.search(r"_(\d+\.\d+\.\d+\.\d+)_", output)
    return match.group(1) if match else None


def install(game_dir: Path):
    """Download or update the game into ``game_dir`` (incremental)."""
    binary = ensure_xodus()
    _require_sign_in()
    game_dir.mkdir(parents=True, exist_ok=True)
    info(f"Downloading Minecraft Legends into {game_dir} (about 12 GB on first install) …")
    code, tail = _run([str(binary), "streaming", C.PRODUCT_ID, str(game_dir)], bars=True)
    progress_done()
    if _cancelled:
        raise LolError("The download was cancelled; running it again resumes it.")
    output = "\n".join(tail)
    problem = _explain(output)
    if problem:
        raise LolError(problem)
    if code != 0 or not installed(game_dir):
        raise LolError(f"The download did not complete (exit {code}). "
                       + (tail[-1] if tail else ""))
    ok("Minecraft Legends is installed")


# ---------------------------------------------------------------- xodus-cli runs

# indicatif renders "Downloading   1.20 GiB/ 11.70 GiB [###   ] 10%"; only
# the aggregate bars (label exactly "Initializing"/"Downloading") count, not
# the per-file ones. Patterns follow BedrockOnLinux's bol/xodus.py.
_PROGRESS = re.compile(r"^\s*(?P<msg>\S[^\d]*?)\s+(?P<done>[\d.]+)\s*(?P<du>[KMGT]?i?B)\s*/\s*"
                       r"(?P<total>[\d.]+)\s*(?P<tu>[KMGT]?i?B)")
_TOTAL_BAR = re.compile(r"^(initializing|downloading)\s*$", re.I)
_BAR_FRAME = re.compile(r"\S.{0,29}?\s{2,}[\d.]+\s*[KMGT]?i?B\s*/\s*[\d.]+\s*[KMGT]?i?B"
                        r"[^\[\]]*\[[^\]]*\]\s*\d+\s*%")
_BAR_REMNANT = re.compile(r"[\d.]+\s*[KMGT]?i?B\s*/\s*[\d.]+\s*[KMGT]?i?B")
_UNITS = {"B": 1, "KiB": 1 << 10, "MiB": 1 << 20, "GiB": 1 << 30, "TiB": 1 << 40,
          "KB": 1000, "MB": 1000 ** 2, "GB": 1000 ** 3}

_current = None
_cancelled = False


def cancel():
    """Stop the sign-in or download that is running, if any."""
    global _cancelled
    proc = _current
    if proc and proc.poll() is None:
        _cancelled = True
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            pass


def _bytes(value, unit):
    try:
        return int(float(value) * _UNITS.get(unit, 1))
    except ValueError:
        return 0


def _line(line, tail, bars):
    """Handle one line of output: progress, or a message worth keeping."""
    line = _ANSI.sub("", line).replace("\x00", "").rstrip()
    if not line:
        return
    match = _PROGRESS.match(line)
    if bars and match and _TOTAL_BAR.match(match.group("msg").strip()):
        total = _bytes(match.group("total"), match.group("tu"))
        if total:
            progress("Downloading Minecraft Legends",
                     min(_bytes(match.group("done"), match.group("du")), total), total)
    if bars:
        line = _BAR_FRAME.sub(" ", line).strip()
        if not line or _BAR_REMNANT.search(line):
            return
    tail.append(line[:1000])
    del tail[:-60]
    info(f"xodus: {line[:300]}")


def _run(cmd, bars=False):
    """Run xodus-cli, logging its output; returns (exit code, last lines).

    With ``bars`` the child gets a pty: indicatif draws nothing otherwise.
    """
    global _current, _cancelled
    _cancelled = False
    environment = env()
    if bars and (environment.get("TERM") or "dumb") in ("", "dumb", "unknown"):
        environment["TERM"] = "xterm-256color"
    tail = []
    if bars:
        master, slave = pty.openpty()
        try:
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 160, 0, 0))
        except OSError:
            pass
        proc = subprocess.Popen(cmd, env=environment, stdin=slave, stdout=slave, stderr=slave,
                                start_new_session=True)
        os.close(slave)
        _current = proc
        buffer = ""
        try:
            while True:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", "replace")
                parts = re.split(r"[\r\n]", buffer)
                buffer = parts.pop()
                for part in parts:
                    _line(part, tail, True)
        finally:
            os.close(master)
            proc.wait()
        _line(buffer, tail, True)
    else:
        proc = subprocess.Popen(cmd, env=environment, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors="replace", start_new_session=True)
        _current = proc
        for raw in proc.stdout:
            _line(raw, tail, False)
        proc.wait()
    _current = None
    return proc.returncode, tail


def installed(game_dir: Path):
    return (game_dir / C.EXE_NAME).is_file() and (game_dir / C.PACKAGE_CACHE).is_file()


def exe_encrypted(game_dir: Path):
    try:
        with open(game_dir / C.EXE_NAME, "rb") as stream:
            return stream.read(2) != b"MZ"
    except OSError:
        return False


# ---------------------------------------------------------------- launch

_WRAPPER = '''\
#!{interpreter}
"""Generated by LegendsOnLinux; rewritten on every launch.

`xodus-cli run` decrypts the game executable into an anonymous memfd and
publishes it through WINE_DLL_FILE_MAP as "<fd>:<NT name>", then execs this
script. The game runs inside the Steam Linux Runtime container, where a
descriptor number means nothing, so each one is copied into a private file
in RAM ({stage_dir}) that the container can open; WineGDK's loader unlinks it
as soon as it has mapped it.
"""
import json, os, shutil, struct, sys, tempfile

ARGV = json.loads({argv!r})
EXE_NAME = {exe_name!r}
STAGE_DIR = {stage_dir!r}
RESTORE_ENV = json.loads({restore_env!r})

entries = []
for entry in (os.environ.get("WINE_DLL_FILE_MAP") or "").split("|"):
    fd_text, _, mapped = entry.partition(":")
    if fd_text.isdigit() and mapped:
        entries.append((int(fd_text), mapped))
target = next((e for e in entries if e[1].lower().rsplit(chr(92), 1)[-1] == EXE_NAME.lower()), None)
nt_name = target[1] if target else (sys.argv[1] if len(sys.argv) > 1 else None)
if not nt_name:
    sys.exit("xodus-cli run passed no executable")


def raise_stack_reserve(fd, wanted=0x1000000):
    head = os.pread(fd, 0x400, 0)
    if head[:2] != b"MZ":
        return
    pe = struct.unpack_from("<I", head, 0x3C)[0]
    opt = pe + 24
    if head[pe:pe + 4] != b"PE\\0\\0" or struct.unpack_from("<H", head, opt)[0] != 0x20B:
        return
    if struct.unpack_from("<Q", head, opt + 72)[0] < wanted:
        os.pwrite(fd, struct.pack("<Q", wanted), opt + 72)


staged = {{}}
try:
    os.makedirs(STAGE_DIR, mode=0o700, exist_ok=True)
    for fd_number, mapped in entries:
        handle, path = tempfile.mkstemp(prefix="lol-", dir=STAGE_DIR)
        os.fchmod(handle, 0o600)
        os.lseek(fd_number, 0, os.SEEK_SET)
        with open(fd_number, "rb", closefd=False) as src, open(handle, "wb", closefd=True) as dst:
            shutil.copyfileobj(src, dst, 1 << 22)
        staged[mapped] = path
except OSError as exc:
    for path in staged.values():
        try:
            os.unlink(path)
        except OSError:
            pass
    sys.exit("could not stage the decrypted game: %s" % exc)

if nt_name in staged:
    try:
        fd = os.open(staged[nt_name], os.O_RDWR)
        try:
            raise_stack_reserve(fd)
        finally:
            os.close(fd)
    except OSError as exc:
        print("legends-on-linux: stack reserve unchanged: %s" % exc, file=sys.stderr)

if staged:
    os.environ["WINE_DLL_FILE_MAP"] = "|".join("%s:%s" % (p, m) for m, p in staged.items())
for name, value in RESTORE_ENV.items():
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
os.execvp(ARGV[0], ARGV + [nt_name])
'''


def stage_dir():
    if os.environ.get("FLATPAK_ID") and os.environ.get("XDG_RUNTIME_DIR"):
        return Path(os.environ["XDG_RUNTIME_DIR"]) / C.APP
    return Path("/dev/shm")


def wrap_launch(argv, game_dir: Path, environment):
    """Return a command that starts ``argv`` (exe last) through `xodus-cli run`.

    `xodus-cli run` reads the licence from the Store keyring, so it runs with
    the Xodus home; the wrapper hands the game its real $HOME back.
    """
    _require_sign_in()
    if not installed(game_dir):
        raise LolError(f"Minecraft Legends is not installed in {game_dir}. Run:  legends-on-linux install")
    binary = ensure_xodus()
    restore = {"HOME": environment.get("HOME")}
    for name in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
        restore[name] = environment.get(name)
    environment.update({k: v for k, v in env().items()
                        if k in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME")})
    C.RUN.mkdir(parents=True, exist_ok=True)
    wrapper = C.RUN / "xodus-launch-wrapper.py"
    interpreter = sys.executable if sys.executable and " " not in sys.executable else "/usr/bin/env python3"
    wrapper.write_text(_WRAPPER.format(
        interpreter=interpreter, argv=json.dumps(list(argv[:-1])),
        exe_name=Path(argv[-1]).name, stage_dir=str(stage_dir()),
        restore_env=json.dumps(restore)), encoding="utf-8")
    wrapper.chmod(0o755)
    _sweep_stale_images()
    return [str(binary), "run", str(game_dir), str(wrapper)]


def _sweep_stale_images(older_than=120):
    """Remove decrypted images a crashed launch left behind in RAM."""
    import time
    directory = stage_dir()
    try:
        for path in directory.glob("lol-*"):
            if path.is_file() and time.time() - path.stat().st_mtime > older_than:
                path.unlink(missing_ok=True)
    except OSError as exc:
        warn(f"Could not clean {directory}: {exc}")
