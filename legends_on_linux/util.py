"""legends_on_linux.util — logging, downloads, archives and settings."""
# SPDX-License-Identifier: MIT

import hashlib
import json
import os
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .config import APP, SETTINGS, VERSION

USER_AGENT = f"{APP}/{VERSION}"


class LolError(Exception):
    """Something the user has to know about; printed without a traceback."""


def colour(code, text, stream=sys.stderr):
    """``text`` in an ANSI colour when ``stream`` is a terminal."""
    return f"\033[{code}m{text}\033[0m" if stream.isatty() else text


def info(msg):
    print(f"{colour(36, '::')} {msg}", file=sys.stderr, flush=True)


def ok(msg):
    print(f"{colour(32, '✓')}  {msg}", file=sys.stderr, flush=True)


def warn(msg):
    print(f"{colour(33, '!')}  {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------- settings

def load_settings():
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(settings):
    write_private(SETTINGS, json.dumps(settings, indent=2).encode())


def write_private(path: Path, data: bytes, mode=0o600):
    """Atomically replace ``path`` with ``data``, readable by us only."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + "-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ---------------------------------------------------------------- network

def http_post_form(url, fields, timeout=30):
    """POST a form and return the decoded JSON body, error bodies included."""
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read()
    try:
        return json.loads(body or b"{}")
    except ValueError:
        return {}


def sha256_file(path: Path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url, dest: Path, label, sha256=None):
    """Download ``url`` to ``dest`` (resuming a .part file), then verify it.

    A file that is already there and matches ``sha256`` is reused; one that
    does not match is never kept.
    """
    if dest.is_file() and sha256 and sha256_file(dest) == sha256:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    headers = {"User-Agent": USER_AGENT}
    if have:
        headers["Range"] = f"bytes={have}-"
    req = urllib.request.Request(url, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and have:
            resp = None
        else:
            raise LolError(f"Downloading {label} failed: HTTP {exc.code} ({url})") from exc
    except OSError as exc:
        raise LolError(f"Downloading {label} failed: {exc}") from exc
    if resp is not None:
        with resp:
            if have and resp.status != 206:
                have = 0
            total = have + int(resp.headers.get("Content-Length") or 0)
            done, last = have, 0.0
            with open(part, "ab" if have else "wb") as out:
                while True:
                    block = resp.read(1 << 20)
                    if not block:
                        break
                    out.write(block)
                    done += len(block)
                    now = time.monotonic()
                    if sys.stderr.isatty() and now - last > 0.2:
                        last = now
                        pct = f"{done * 100 // total:3d}%" if total else ""
                        print(f"\r   {label}: {done >> 20} / {total >> 20} MiB {pct}",
                              end="", file=sys.stderr, flush=True)
            if sys.stderr.isatty():
                print(file=sys.stderr)
    if sha256:
        actual = sha256_file(part)
        if actual != sha256:
            part.unlink(missing_ok=True)
            raise LolError(f"{label}: SHA-256 mismatch (expected {sha256}, got {actual}).")
    os.replace(part, dest)
    return dest


# ---------------------------------------------------------------- archives

def safe_extract(archive: Path, dest: Path):
    """Extract a tarball, refusing members that would land outside ``dest``."""
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as tar:
        try:
            tar.extractall(dest, filter="data")
        except TypeError:          # Python without extraction filters
            root = dest.resolve()
            for member in tar.getmembers():
                target = (dest / member.name).resolve()
                if root not in target.parents and target != root:
                    raise LolError(f"{archive.name}: unsafe path {member.name}")
                if member.issym() or member.islnk():
                    link = (target.parent / member.linkname).resolve()
                    if root not in link.parents and link != root:
                        raise LolError(f"{archive.name}: unsafe link {member.name}")
            tar.extractall(dest)


def replace_dir(staging: Path, target: Path):
    """Swap ``staging`` in for ``target`` with the old one gone only at the end."""
    target.parent.mkdir(parents=True, exist_ok=True)
    old = target.with_name(target.name + ".old")
    shutil.rmtree(old, ignore_errors=True)
    if target.exists():
        os.replace(target, old)
    os.replace(staging, target)
    shutil.rmtree(old, ignore_errors=True)
