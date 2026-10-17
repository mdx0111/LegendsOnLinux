"""legends_on_linux.cli — the `legends-on-linux` command."""
# SPDX-License-Identifier: MIT

import argparse
import os
import shutil
import sys
from pathlib import Path

from . import auth, deps, launch, prefix, store
from . import config as C
from .util import LolError, colour, load_settings, ok, save_settings


def cmd_setup(args):
    deps.ensure_all()
    prefix.ensure_prefix()
    ok("Setup complete")


def cmd_login(args):
    both = not (args.store or args.xbox)
    if args.store or both:
        store.login()
    if args.xbox or both:
        auth.login()
        auth.preauth(force=True)


def cmd_logout(args):
    both = not (args.store or args.xbox)
    if args.xbox or both:
        auth.logout()
    if args.store or both:
        store.logout(device=args.forget_device)


def cmd_install(args):
    if args.dir:
        directory = Path(args.dir).expanduser().resolve()
        settings = load_settings()
        settings["game_dir"] = str(directory)
        save_settings(settings)
    directory = launch.game_dir()
    store.install(directory)


def cmd_use(args):
    directory = Path(args.dir).expanduser().resolve()
    if not store.installed(directory):
        raise LolError(f"{directory} does not hold a Minecraft Legends download made by xodus-cli "
                       f"({C.EXE_NAME} and {C.PACKAGE_CACHE}).")
    settings = load_settings()
    settings["game_dir"] = str(directory)
    save_settings(settings)
    ok(f"Using the game in {directory}")


def cmd_play(args):
    launch.play(offline=args.offline, debug=args.debug)


def cmd_gui(args):
    try:
        from . import gui
    except ImportError as exc:
        raise LolError(f"The launcher window needs PySide6 ({exc}). Install it "
                       "(Fedora: sudo dnf install python3-pyside6; elsewhere: "
                       "pip install PySide6), or use the commands in --help.") from exc
    sys.exit(gui.main())


def cmd_desktop_entry(args):
    """Add a checkout's launcher to the desktop's application menu.

    Distribution packages install their own desktop file and icons.
    """
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    entry = data / "applications" / f"{C.APP_ID}.desktop"
    icons = sorted((C.ASSETS / "icons" / "hicolor").glob(f"*/apps/{C.APP_ID}.png"))
    # The entry an earlier version created, under the old name.
    (data / "applications" / f"{C.APP}.desktop").unlink(missing_ok=True)
    (data / "icons" / f"{C.APP}.png").unlink(missing_ok=True)
    if args.remove:
        entry.unlink(missing_ok=True)
        for icon in icons:
            (data / "icons" / "hicolor" / icon.relative_to(C.ASSETS / "icons" / "hicolor")
             ).unlink(missing_ok=True)
        ok("Removed the launcher from the application menu")
        return
    script = Path(sys.argv[0]).resolve()
    command = (f'"{script}"' if script.name == "legends-on-linux" and script.is_file()
               else f'"{sys.executable}" -m legends_on_linux')
    for icon in icons:
        target = data / "icons" / "hicolor" / icon.relative_to(C.ASSETS / "icons" / "hicolor")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(icon, target)
    template = (C.ASSETS / f"{C.APP_ID}.desktop").read_text(encoding="utf-8")
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(template.replace("Exec=legends-on-linux gui", f"Exec={command} gui"),
                     encoding="utf-8")
    ok(f"Added LegendsOnLinux to the application menu ({entry})")


def cmd_status(args):
    directory = launch.game_dir()

    def line(label, value, good):
        mark = colour(32, "✓", sys.stdout) if good else colour(33, "✗", sys.stdout)
        print(f" {mark} {label:<26} {value}")

    print(f"{C.PRETTY} {C.VERSION}  —  data in {C.DATA}")
    line("Microsoft Store account", "linked" if store.signed_in() else "not linked "
         "(legends-on-linux login --store)", store.signed_in())
    line("Xbox Live account", "linked" if auth.signed_in() else "not linked "
         "(legends-on-linux login --xbox)", auth.signed_in())
    installed = store.installed(directory)
    line("Game", str(directory) if installed else f"not installed in {directory}", installed)
    engine = (C.ENGINE / "proton").is_file()
    line("Game engine", C.ENGINE_REV if engine else "not installed (legends-on-linux setup)", engine)
    patched = deps.xgameruntime_installed()
    line("Legends engine patch", C.XGAMERUNTIME_REV if patched else
         "not installed yet (legends-on-linux setup)", patched)
    line("xodus-cli", C.XODUS_REV if deps.xodus_bin().is_file() else "not installed",
         deps.xodus_bin().is_file())
    has_prefix = (C.PFX / "system.reg").is_file()
    line("Wine prefix", str(C.PFX) if has_prefix else "not created yet", has_prefix)
    saves = prefix.saves_dir()
    count = sum(1 for p in saves.rglob("*") if p.is_file()) if saves.is_dir() else 0
    line("Local saves", f"{count} files in {saves}" if count else "none yet", True)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="legends-on-linux",
        description="Download and play Minecraft Legends (Windows edition) on Linux.")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("gui", help="open the launcher window (the default)").set_defaults(func=cmd_gui)

    sub.add_parser("setup", help="download the engine and tools, create the Wine prefix"
                   ).set_defaults(func=cmd_setup)

    p = sub.add_parser("login", help="link your Microsoft account (Store and Xbox Live)")
    p.add_argument("--store", action="store_true", help="only the Store sign-in (download/licence)")
    p.add_argument("--xbox", action="store_true", help="only the in-game Xbox Live sign-in")
    p.set_defaults(func=cmd_login)

    p = sub.add_parser("logout", help="unlink the Microsoft account")
    p.add_argument("--store", action="store_true")
    p.add_argument("--xbox", action="store_true")
    p.add_argument("--forget-device", action="store_true",
                   help="also forget this PC's Microsoft Store device registration")
    p.set_defaults(func=cmd_logout)

    p = sub.add_parser("install", help="download or update the game from Microsoft")
    p.add_argument("--dir", help=f"where to install it (default {C.DEFAULT_GAME_DIR})")
    p.set_defaults(func=cmd_install)

    p = sub.add_parser("use", help="use a game folder already downloaded with xodus-cli")
    p.add_argument("dir")
    p.set_defaults(func=cmd_use)

    p = sub.add_parser("play", help="start the game")
    p.add_argument("--debug", action="store_true", help="write Proton and HTTP logs")
    p.add_argument("--offline", action="store_true", help="start without Xbox Live (debugging)")
    p.set_defaults(func=cmd_play)

    sub.add_parser("status", help="show what is set up").set_defaults(func=cmd_status)

    p = sub.add_parser("desktop-entry", help="add the launcher to the application menu")
    p.add_argument("--remove", action="store_true", help="remove it again")
    p.set_defaults(func=cmd_desktop_entry)

    args = parser.parse_args(argv)
    if args.command is None:
        args.func = cmd_gui
    try:
        args.func(args)
    except LolError as exc:
        print(f"{colour(31, 'error:')} {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(file=sys.stderr)
        return 130
    return 0
