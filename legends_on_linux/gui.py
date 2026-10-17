"""legends_on_linux.gui — the launcher window (PySide6).

Every operation runs on a worker thread; the core reports back through the
log and progress sinks in util, which are bridged into Qt signals here.
"""
# SPDX-License-Identifier: MIT

import os
import re
import shutil
import subprocess
import sys
import threading
import traceback
import webbrowser
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSizePolicy,
    QToolButton, QVBoxLayout, QWidget,
)

from . import auth, deps, launch, prefix, store, util
from . import config as C
from .util import LolError, load_settings, save_settings

STYLE = """
QWidget { color: #e6edf5; font-size: 10.5pt; }
QMainWindow, QDialog, QWidget#root { background: #0d1520; }
QLabel, QWidget#row { background: transparent; }
QToolButton::menu-indicator { image: none; width: 0; }
QLabel#title { font-size: 20pt; font-weight: 700; }
QLabel#subtitle, QLabel#muted { color: #8ea3b8; }
QLabel#cardTitle { font-size: 12pt; font-weight: 600; }
QLabel#statusGood { color: #5fd38d; }
QLabel#statusBad { color: #f0b350; }
QFrame#card { background: #152232; border: 1px solid #22364b; border-radius: 10px; }
QFrame#sep { background: #22364b; max-height: 1px; min-height: 1px; border: none; }
QPushButton, QToolButton {
    background: #1d2f44; border: 1px solid #2c4560; border-radius: 6px;
    padding: 6px 14px; color: #e6edf5;
}
QPushButton:hover, QToolButton:hover { background: #24394f; }
QPushButton:disabled { color: #5e7286; border-color: #22364b; }
QPushButton#primary { background: #1f6fd1; border-color: #3a8af0; font-weight: 600; }
QPushButton#primary:hover { background: #2a7de0; }
QPushButton#play {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3aa7ff, stop:1 #1c63c4);
    border: 1px solid #63bcff; border-radius: 10px;
    font-size: 16pt; font-weight: 800; padding: 10px 40px; min-width: 190px;
}
QPushButton#play:hover { background: #3fb0ff; }
QPushButton#play:disabled { background: #1d2f44; color: #5e7286; border-color: #22364b; }
QPushButton#stop { background: #8c2b2b; border-color: #c24b4b; font-size: 14pt;
    font-weight: 700; border-radius: 10px; padding: 10px 40px; min-width: 190px; }
QPushButton#link { background: transparent; border: none; color: #6fb6ff; padding: 2px; }
QPushButton#link:hover { text-decoration: underline; }
QProgressBar { background: #152232; border: 1px solid #22364b; border-radius: 5px;
    height: 10px; text-align: center; font-size: 8pt; }
QProgressBar::chunk { background: #2a8cf0; border-radius: 4px; }
QPlainTextEdit { background: #0a1018; border: 1px solid #22364b; border-radius: 6px;
    font-family: monospace; font-size: 9pt; color: #b8c7d6; }
QMenu { background: #152232; border: 1px solid #2c4560; }
QMenu::item { padding: 6px 22px; }
QMenu::item:selected { background: #24394f; }
QDialog { background: #0d1520; }
QLabel#code { font-size: 26pt; font-weight: 800; letter-spacing: 4px; color: #ffffff;
    background: #152232; border: 1px solid #2c4560; border-radius: 8px; padding: 10px 24px; }
"""


# ---------------------------------------------------------------- plumbing

class Bridge(QObject):
    """Carries the core's log and progress callbacks onto the GUI thread."""
    log = Signal(str, str)
    progress = Signal(str, object, object)
    device_code = Signal(str, str)


class Task(QThread):
    """Runs one core operation; ``failed`` carries a message, ``succeeded`` the result."""
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn, self._args, self._kwargs = fn, args, kwargs

    def run(self):
        try:
            self.succeeded.emit(self._fn(*self._args, **self._kwargs))
        except LolError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:                            # noqa: BLE001
            util.warn(traceback.format_exc().rstrip())
            self.failed.emit(f"Unexpected error: {exc}")


def card(title, subtitle=None):
    frame = QFrame(objectName="card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 14, 18, 14)
    layout.setSpacing(10)
    head = QLabel(title, objectName="cardTitle")
    layout.addWidget(head)
    if subtitle:
        sub = QLabel(subtitle, objectName="muted")
        sub.setWordWrap(True)
        layout.addWidget(sub)
    return frame, layout


def separator():
    return QFrame(objectName="sep")


class Row(QWidget):
    """Label + description on the left, status and a button on the right."""

    def __init__(self, title, description, button_text, on_click):
        super().__init__(objectName="row")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        text = QVBoxLayout()
        text.setSpacing(1)
        self.title = QLabel(title)
        self.title.setStyleSheet("font-weight: 600;")
        self.description = QLabel(description, objectName="muted")
        self.description.setWordWrap(True)
        text.addWidget(self.title)
        text.addWidget(self.description)
        layout.addLayout(text, 1)
        self.status = QLabel()
        layout.addWidget(self.status)
        self.button = QPushButton(button_text)
        self.button.clicked.connect(on_click)
        layout.addWidget(self.button)

    def set_status(self, text, good):
        self.status.setText(text)
        self.status.setObjectName("statusGood" if good else "statusBad")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)


class DeviceCodeDialog(QDialog):
    """Shows the Xbox Live sign-in code while the worker waits for it."""

    def __init__(self, parent, url, code, on_cancel):
        super().__init__(parent)
        self.setWindowTitle("Xbox Live sign-in")
        self.setModal(True)
        self._url, self._code, self._on_cancel = url, code, on_cancel
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(14)
        intro = QLabel(f"Open <b>{url}</b> in a browser, sign in with the Microsoft "
                       "account you play as, and enter this code:")
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.RichText)
        layout.addWidget(intro)
        code_label = QLabel(code, objectName="code")
        code_label.setAlignment(Qt.AlignCenter)
        code_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(code_label)
        hint = QLabel("This window closes by itself once the sign-in is complete.",
                      objectName="muted")
        layout.addWidget(hint)
        buttons = QHBoxLayout()
        open_btn = QPushButton("Copy code and open browser", objectName="primary")
        open_btn.clicked.connect(self._open)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(open_btn)
        buttons.addStretch(1)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)

    def _open(self):
        QGuiApplication.clipboard().setText(self._code)
        QDesktopServices.openUrl(QUrl(self._url))

    def reject(self):
        self._on_cancel()
        super().reject()


# ---------------------------------------------------------------- main window

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Minecraft Legends — LegendsOnLinux")
        self.setMinimumSize(780, 560)
        self.task = None
        self.game = None
        self.code_dialog = None
        self.xbox_cancel = None
        self.cancel_action = None

        self.bridge = Bridge()
        self.bridge.log.connect(self._append_log)
        self.bridge.progress.connect(self._on_progress)
        self.bridge.device_code.connect(self._show_device_code)
        util.set_log_sink(self.bridge.log.emit)
        util.set_progress_sink(self.bridge.progress.emit)

        root = QWidget(objectName="root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(22, 18, 22, 16)
        outer.setSpacing(14)

        # header
        header = QHBoxLayout()
        self.logo = QLabel()
        self.logo.setFixedSize(72, 72)
        header.addWidget(self.logo)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(QLabel("Minecraft Legends", objectName="title"))
        self.subtitle = QLabel(objectName="subtitle")
        titles.addWidget(self.subtitle)
        header.addLayout(titles, 1)
        self.menu_button = QToolButton(text="⋮")
        self.menu_button.setStyleSheet("font-size: 14pt; padding: 2px 12px;")
        self.menu_button.setPopupMode(QToolButton.InstantPopup)
        self.menu_button.setMenu(self._build_menu())
        header.addWidget(self.menu_button, 0, Qt.AlignTop)
        outer.addLayout(header)

        # accounts
        accounts, layout = card("Microsoft account",
                                "Sign in twice with the account that owns the game: once for "
                                "the Store, once for Xbox Live.")
        self.store_row = Row("Microsoft Store", "Proves you own the game, downloads and "
                             "decrypts it.", "Sign in", self._store_clicked)
        self.xbox_row = Row("Xbox Live", "The account the game plays as.", "Sign in",
                            self._xbox_clicked)
        layout.addWidget(self.store_row)
        layout.addWidget(separator())
        layout.addWidget(self.xbox_row)
        outer.addWidget(accounts)

        # game
        game, layout = card("Game")
        self.game_row = Row("Install location", "", "Install", self._install_clicked)
        change = QPushButton("Change…")
        change.clicked.connect(self._change_folder)
        self.game_row.layout().insertWidget(2, change)
        layout.addWidget(self.game_row)
        outer.addWidget(game)

        # log
        self.log = QPlainTextEdit(readOnly=True)
        self.log.setMaximumBlockCount(5000)
        self.log.setVisible(False)
        self.log.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        outer.addWidget(self.log, 1)
        if not self.log.isVisible():
            outer.addStretch(1)

        # bottom bar
        bottom = QHBoxLayout()
        status_box = QVBoxLayout()
        status_box.setSpacing(4)
        self.status = QLabel("Ready", objectName="muted")
        self.status.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        status_line = QHBoxLayout()
        status_line.addWidget(self.status, 1)
        self.cancel_button = QPushButton("Cancel", objectName="link")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self._cancel)
        status_line.addWidget(self.cancel_button)
        self.log_button = QPushButton("Show log", objectName="link")
        self.log_button.clicked.connect(self._toggle_log)
        status_line.addWidget(self.log_button)
        status_box.addLayout(status_line)
        status_box.addWidget(self.progress)
        bottom.addLayout(status_box, 1)
        self.play_button = QPushButton("PLAY", objectName="play")
        self.play_button.clicked.connect(self._play_clicked)
        bottom.addWidget(self.play_button)
        outer.addLayout(bottom)

        self.poll = QTimer(self, interval=2000)
        self.poll.timeout.connect(self._poll_game)
        self.refresh()

    # ------------------------------------------------------------ menu

    def _build_menu(self):
        menu = QMenu(self)
        menu.addAction("Open game folder", lambda: self._open_path(launch.game_dir()))
        menu.addAction("Open saves folder", lambda: self._open_path(prefix.saves_dir()))
        menu.addAction("Open logs folder", lambda: self._open_path(C.LOGS))
        menu.addAction("Open data folder", lambda: self._open_path(C.DATA))
        menu.addSeparator()
        self.debug_action = menu.addAction("Debug logging when playing")
        self.debug_action.setCheckable(True)
        self.debug_action.setChecked(bool(load_settings().get("debug")))
        self.debug_action.toggled.connect(self._set_debug)
        menu.addAction("Repair: set up engine and prefix again", self._setup_clicked)
        menu.addSeparator()
        menu.addAction("Sign out of the Microsoft Store", lambda: self._run(
            "Signing out of the Store …", store.logout, after=self.refresh))
        menu.addAction("Sign out of Xbox Live", lambda: self._run(
            "Signing out of Xbox Live …", auth.logout, after=self.refresh))
        menu.addSeparator()
        menu.addAction("Project page", lambda: webbrowser.open(
            "https://github.com/mdx0111/LegendsOnLinux"))
        menu.addAction("About", self._about)
        return menu

    def _open_path(self, path):
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _set_debug(self, enabled):
        settings = load_settings()
        settings["debug"] = enabled
        save_settings(settings)

    def _about(self):
        QMessageBox.about(self, "About LegendsOnLinux", (
            f"<b>{C.PRETTY} {C.VERSION}</b><br>Minecraft Legends (Windows edition) on Linux."
            "<br><br>Built on WineGDK, BedrockOnLinux, xodus-cli and umu-launcher. "
            "Not affiliated with Microsoft or Mojang; you need to own the game."))

    # ------------------------------------------------------------ state

    def refresh(self):
        directory = launch.game_dir()
        installed = store.installed(directory)
        version = game_version(directory) if installed else None
        self.subtitle.setText(f"{C.PRETTY} {C.VERSION}"
                              + (f"  ·  game {version}" if version else ""))
        logo = directory / "icons" / "MCSquare71x71Logo.scale-400.png"
        if logo.is_file():
            pixmap = QPixmap(str(logo))
            self.logo.setPixmap(pixmap.scaled(72, 72, Qt.KeepAspectRatio,
                                              Qt.SmoothTransformation))
            self.setWindowIcon(QIcon(pixmap))

        linked = store.signed_in()
        self.store_row.set_status("Linked" if linked else "Not linked", linked)
        self.store_row.button.setText("Sign out" if linked else "Sign in")
        xbox = auth.signed_in()
        tag = auth.gamertag() if xbox else None
        self.xbox_row.set_status(tag or ("Linked" if xbox else "Not linked"), xbox)
        self.xbox_row.button.setText("Sign out" if xbox else "Sign in")

        self.game_row.description.setText(str(directory))
        self.game_row.set_status("Installed" if installed else "Not installed", installed)
        self.game_row.button.setText("Update" if installed else "Install")
        self._update_buttons()

    def _busy(self):
        return self.task is not None

    def _update_buttons(self):
        busy = self._busy()
        playing = self.game is not None
        for button in (self.store_row.button, self.xbox_row.button, self.game_row.button):
            button.setEnabled(not busy and not playing)
        if playing:
            self.play_button.setText("STOP")
            self.play_button.setObjectName("stop")
            self.play_button.setEnabled(not busy)
        else:
            self.play_button.setText("PLAY")
            self.play_button.setObjectName("play")
            ready = (store.installed(launch.game_dir()) and store.signed_in()
                     and auth.signed_in())
            self.play_button.setEnabled(not busy and ready)
            self.play_button.setToolTip("" if ready else
                                        "Sign in to both services and install the game first.")
        self.play_button.style().unpolish(self.play_button)
        self.play_button.style().polish(self.play_button)

    # ------------------------------------------------------------ running work

    def _run(self, status, fn, *args, after=None, cancel=None, **kwargs):
        if self._busy():
            return
        self.status.setText(status)
        self.progress.setVisible(False)
        self.cancel_action = cancel
        self.cancel_button.setVisible(cancel is not None)
        self.task = Task(fn, *args, **kwargs)

        def finished_ok(result):
            self._finish()
            self.status.setText("Ready")
            if after:
                after(result) if _accepts_arg(after) else after()

        def finished_error(message):
            self._finish()
            self.status.setText("Failed — see the log for details")
            self._append_log("warn", message)
            QMessageBox.warning(self, "LegendsOnLinux", message)
            self.refresh()

        self.task.succeeded.connect(finished_ok)
        self.task.failed.connect(finished_error)
        self.task.start()
        self._update_buttons()

    def _finish(self):
        if self.task:
            self.task.wait()
        self.task = None
        self.cancel_action = None
        self.cancel_button.setVisible(False)
        self.progress.setVisible(False)
        if self.code_dialog:
            self.code_dialog.accept()
            self.code_dialog = None
        self._update_buttons()

    def _cancel(self):
        if self.cancel_action:
            self.status.setText("Cancelling …")
            self.cancel_action()

    def _append_log(self, level, message):
        prefix_mark = {"ok": "✓", "warn": "!", "info": "·"}.get(level, "·")
        for line in message.splitlines() or [""]:
            self.log.appendPlainText(f"{prefix_mark} {line}")
        if level in ("ok", "warn") or not message.startswith("xodus:"):
            short = message.splitlines()[0] if message else ""
            if self._busy() and short:
                self.status.setText(short[:160])

    def _on_progress(self, label, done, total):
        self.progress.setVisible(True)
        if total:
            self.progress.setRange(0, 1000)
            self.progress.setValue(int(done * 1000 / total))
            self.progress.setFormat(f"{label}: {human(done)} / {human(total)}  (%p%)")
        else:
            self.progress.setRange(0, 0)

    def _toggle_log(self):
        visible = not self.log.isVisible()
        self.log.setVisible(visible)
        self.log_button.setText("Hide log" if visible else "Show log")

    # ------------------------------------------------------------ accounts

    def _store_clicked(self):
        if store.signed_in():
            if QMessageBox.question(self, "Sign out", "Sign out of the Microsoft Store? "
                                    "You need to sign in again to play.") == QMessageBox.Yes:
                self._run("Signing out of the Store …", store.logout, after=self.refresh)
            return
        self._run("Finish the sign-in in the Microsoft window that opened …",
                  store.login, after=self.refresh, cancel=store.cancel)

    def _xbox_clicked(self):
        if auth.signed_in():
            if QMessageBox.question(self, "Sign out",
                                    "Sign out of Xbox Live?") == QMessageBox.Yes:
                self._run("Signing out of Xbox Live …", auth.logout, after=self.refresh)
            return
        self.xbox_cancel = threading.Event()

        def sign_in(cancel):
            auth.login(on_code=self.bridge.device_code.emit, cancel=cancel)
            auth.preauth(force=True)

        self._run("Waiting for the Xbox Live sign-in …", sign_in, self.xbox_cancel,
                  after=self.refresh, cancel=self.xbox_cancel.set)

    def _show_device_code(self, url, code):
        self.code_dialog = DeviceCodeDialog(self, url, code, self.xbox_cancel.set)
        self.code_dialog.show()

    # ------------------------------------------------------------ game

    def _install_clicked(self):
        if not store.signed_in():
            QMessageBox.information(self, "Sign in first",
                                    "Sign in to the Microsoft Store to download the game.")
            return
        directory = launch.game_dir()
        free = shutil.disk_usage(_existing_parent(directory)).free
        if not store.installed(directory) and free < 14 << 30:
            QMessageBox.warning(self, "Not enough space",
                                f"The game needs about 13 GB; {human(free)} is free in "
                                f"{_existing_parent(directory)}.")
            return
        self._run("Preparing the download …", store.install, directory,
                  after=self.refresh, cancel=store.cancel)

    def _change_folder(self):
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose the game folder (an existing download, or where to install)",
            str(launch.game_dir().parent))
        if not chosen:
            return
        directory = Path(chosen)
        settings = load_settings()
        settings["game_dir"] = str(directory)
        save_settings(settings)
        if store.installed(directory):
            util.ok(f"Using the game in {directory}")
        else:
            util.info(f"The game will be installed in {directory}")
        self.refresh()

    def _setup_clicked(self):
        self._run("Setting up the engine and Wine prefix …", setup, after=self.refresh)

    # ------------------------------------------------------------ play

    def _play_clicked(self):
        if self.game is not None:
            self._run("Stopping the game …", launch.stop, self.game, after=self._game_ended)
            return
        debug = bool(load_settings().get("debug"))

        def started(proc):
            self.game = proc
            self.status.setText("Minecraft Legends is running")
            self.poll.start()
            self._update_buttons()

        self._run("Starting Minecraft Legends …", start_game, debug, after=started)

    def _poll_game(self):
        if self.game is None:
            return
        if self.game.poll() is not None and not launch.running():
            self._game_ended()

    def _game_ended(self, *_):
        self.poll.stop()
        code = self.game.returncode if self.game else None
        self.game = None
        self.status.setText("The game has closed" + (f" (exit code {code})" if code else ""))
        self.refresh()

    def closeEvent(self, event):
        if self.game is not None:
            if QMessageBox.question(self, "Quit", "The game is still running. Close the "
                                    "launcher anyway? (The game keeps running.)") != QMessageBox.Yes:
                event.ignore()
                return
        if self.task is not None:
            if self.cancel_action:
                self.cancel_action()
            self.task.wait(5000)
        util.set_log_sink(None)
        util.set_progress_sink(None)
        super().closeEvent(event)


# ---------------------------------------------------------------- core glue

def setup():
    """Download what is missing and create the Wine prefix.

    If the published engine patch cannot be downloaded and no local build
    exists, build one when the tools for it are there.
    """
    try:
        deps.ensure_all()
    except LolError:
        if deps.pinned_xgameruntime().is_file() or deps.local_xgameruntime():
            raise
        build_xgameruntime()
        deps.ensure_all()
    prefix.ensure_prefix()
    util.ok("Engine and Wine prefix are ready")


def start_game(debug):
    if not deps.xgameruntime_installed() or not (C.PFX / ".lol-ready").is_file():
        setup()
    return launch.start(debug=debug)


def build_xgameruntime():
    script = deps.PROJECT / "scripts" / "build-xgameruntime.sh"
    missing = [t for t in ("git", "gcc", "make", "flex", "bison", "x86_64-w64-mingw32-gcc")
               if shutil.which(t) is None]
    if missing or not script.is_file():
        raise LolError("The engine patch has to be built once, which needs: "
                       + ", ".join(missing or ["the project's scripts/ folder"])
                       + ".\nOn Fedora: sudo dnf install git gcc make flex bison mingw64-gcc")
    util.info("Building the Legends engine patch (about a minute) …")
    proc = subprocess.Popen([str(script)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, errors="replace")
    for line in proc.stdout:
        util.info(line.rstrip())
    if proc.wait() != 0:
        raise LolError("Building the engine patch failed; see the log.")


def game_version(directory: Path):
    try:
        text = (directory / "appxmanifest.xml").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.search(r'<Identity[^>]*\bVersion="([\d.]+)"', text)
    return match.group(1).rsplit(".", 1)[0] if match else None


def human(size):
    size = float(size or 0)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024


def _existing_parent(path: Path):
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def _accepts_arg(fn):
    import inspect
    try:
        return len(inspect.signature(fn).parameters) > 0
    except (TypeError, ValueError):
        return False


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(C.PRETTY)
    app.setDesktopFileName(C.APP)
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    return app.exec()
