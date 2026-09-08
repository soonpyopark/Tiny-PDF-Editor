"""Watch the virtual-printer spool file and open finished PDFs."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QFileSystemWatcher, QLockFile, QObject, QProcess, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

from pdf_editor.resources import load_app_icon
from pdf_editor.virtual_printer import (
    WATCH_FLAG,
    claim_spool_pdf,
    exe_path,
    printer_is_installed,
    spool_dir,
    spool_file,
    uninstall_virtual_printer,
    watch_lock_file,
)
from pdf_editor.version import APP_NAME


class PrintSpoolWatcher(QObject):
    pdf_ready = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lock = QLockFile(str(watch_lock_file()))
        self._lock.setStaleLockTime(30_000)
        self._fs = QFileSystemWatcher(self)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(1200)
        self._debounce.timeout.connect(self._try_claim)
        self._retry = QTimer(self)
        self._retry.setInterval(500)
        self._retry.timeout.connect(self._try_claim)
        self._retries = 0
        self._owned = False
        self._poll = QTimer(self)
        self._poll.setInterval(800)
        self._poll.timeout.connect(self._try_claim)

    def start(self) -> bool:
        spool_dir().mkdir(parents=True, exist_ok=True)
        self._lock.setStaleLockTime(5_000)
        if not self._lock.tryLock(200):
            return False
        self._owned = True
        folder = str(spool_dir())
        if folder not in self._fs.directories():
            self._fs.addPath(folder)
        target = str(spool_file())
        if Path(target).exists() and target not in self._fs.files():
            self._fs.addPath(target)
        self._fs.directoryChanged.connect(self._on_change)
        self._fs.fileChanged.connect(self._on_change)
        self._poll.start()
        self._try_claim()
        return True

    def stop(self) -> None:
        self._poll.stop()
        self._retry.stop()
        if self._owned:
            self._lock.unlock()
            self._owned = False

    def _on_change(self, _path: str = "") -> None:
        target = str(spool_file())
        if Path(target).exists() and target not in self._fs.files():
            self._fs.addPath(target)
        self._retries = 0
        self._retry.stop()
        self._debounce.start()

    def _try_claim(self) -> None:
        claimed = claim_spool_pdf()
        if claimed is not None:
            self._retry.stop()
            self._retries = 0
            self.pdf_ready.emit(str(claimed))
            return
        if spool_file().exists():
            self._retries += 1
            if self._retries <= 40:
                self._retry.start()
            else:
                self._retry.stop()


def launch_editor_with_pdf(path: str = "") -> None:
    exe = str(exe_path())
    extra = [path] if path else []
    if getattr(sys, "frozen", False):
        args = extra
    else:
        main_py = str(Path(__file__).resolve().parents[1] / "main.py")
        args = [main_py, *extra]
    if QProcess.startDetached(exe, args):
        return
    import subprocess

    subprocess.Popen(
        [exe, *args],
        close_fds=True,
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )


class PrintWatchController(QObject):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.watcher = PrintSpoolWatcher(self)
        self.watcher.pdf_ready.connect(self._on_pdf)
        self._tray: QSystemTrayIcon | None = None

    def start(self) -> bool:
        return self.watcher.start()

    def attach_tray(self, icon: QIcon) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        tray = QSystemTrayIcon(icon, self)
        menu = QMenu()
        open_act = QAction("Tiny PDF Editor 열기", menu)
        open_act.triggered.connect(lambda: launch_editor_with_pdf(""))
        menu.addAction(open_act)
        remove_act = QAction("가상 프린터 제거", menu)
        remove_act.triggered.connect(self._remove_printer)
        menu.addAction(remove_act)
        menu.addSeparator()
        quit_act = QAction("종료", menu)
        quit_act.triggered.connect(QApplication.instance().quit)
        menu.addAction(quit_act)
        tray.setContextMenu(menu)
        tray.setToolTip(f"{APP_NAME} 가상 프린터")
        tray.show()
        self._tray = tray

    def _on_pdf(self, path: str) -> None:
        launch_editor_with_pdf(path)

    def _remove_printer(self) -> None:
        uninstall_virtual_printer()
        QApplication.instance().quit()

    def stop(self) -> None:
        self.watcher.stop()


def run_print_watch_app(app: QApplication) -> int:
    if not printer_is_installed():
        return 0
    icon = load_app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    controller = PrintWatchController(app)
    if not controller.start():
        return 0
    controller.attach_tray(icon)
    app.aboutToQuit.connect(controller.stop)
    # Keep a hidden widget so the process is not treated as already finished.
    holder = QWidget()
    holder.setWindowTitle(APP_NAME)
    holder.resize(1, 1)
    app.setQuitOnLastWindowClosed(False)
    _ = holder
    return app.exec()


def launch_watch_if_needed() -> None:
    if not printer_is_installed():
        return
    exe = str(exe_path())
    if getattr(sys, "frozen", False):
        cmd = [exe, WATCH_FLAG]
    else:
        main_py = str(Path(__file__).resolve().parents[1] / "main.py")
        cmd = [exe, main_py, WATCH_FLAG]
    import subprocess

    subprocess.Popen(
        cmd,
        close_fds=True,
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        | getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
