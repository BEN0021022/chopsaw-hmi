"""Background GitHub Releases update checker, downloader, and banner UI."""
import sys

from PyQt6.QtCore import QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QProgressDialog, QPushButton, QWidget


class UpdateChecker(QThread):
    """Background check for a newer GitHub release; never blocks the UI thread."""

    update_found = pyqtSignal(dict)
    check_finished = pyqtSignal(object, str)  # (info or None, error_detail)

    def __init__(self, updater_module, parent=None, diagnose_errors=False):
        super().__init__(parent)
        self._updater = updater_module
        self._diagnose_errors = diagnose_errors

    def run(self):
        error_detail = ""
        try:
            info = self._updater.check_for_update()
        except Exception as exc:
            info = None
            error_detail = f"{type(exc).__name__}: {exc}"
        if info is None and self._diagnose_errors and not error_detail:
            try:
                self._updater._http_get(self._updater.API_LATEST, self._updater.DEFAULT_TIMEOUT)
            except Exception as exc:
                error_detail = f"{type(exc).__name__}: {exc}"
        if info:
            self.update_found.emit(info)
        self.check_finished.emit(info, error_detail)


class UpdateDownloader(QThread):
    """Downloads the release EXE off the UI thread, reporting progress and honoring cancel."""

    progress = pyqtSignal(int, int)       # downloaded, total bytes
    finished_path = pyqtSignal(object)    # local Path, or None on failure / cancel

    def __init__(self, updater_module, info, parent=None):
        super().__init__(parent)
        self._updater = updater_module
        self._info = info

    def run(self):
        try:
            path = self._updater.download_update(
                self._info,
                progress_cb=lambda d, t: self.progress.emit(d, t),
                cancel_cb=self.isInterruptionRequested,
            )
        except Exception:
            path = None
        self.finished_path.emit(path)


class UpdateManager:
    """Owns the top update banner, async check/download workers, and clean teardown."""

    def __init__(self, window, updater_module, app_version):
        self.window = window
        self.updater = updater_module
        self.app_version = app_version
        self.pending_update = None
        self.downloaded_exe = None
        self.dialog = None
        self.startup_checker = None
        self.manual_checker = None
        self.downloader = None
        self.startup_timer = None
        self.banner = None
        self.banner_label = None
        self.install_btn = None
        self.later_btn = None

    def build_banner(self):
        banner = QWidget()
        banner.setStyleSheet(
            "background-color:#1e3a8a; border:1px solid #2563eb; border-radius:10px;"
        )
        row = QHBoxLayout(banner)
        row.setContentsMargins(12, 6, 12, 6)
        self.banner_label = QLabel("Update available")
        self.banner_label.setStyleSheet(
            "color:#e2e8f0; font-weight:bold; background:transparent; border:none;"
        )
        row.addWidget(self.banner_label, 1)
        self.install_btn = QPushButton("Install && Restart")
        self.install_btn.setStyleSheet("background-color:#22c55e; color:white; font-weight:700;")
        self.install_btn.clicked.connect(self.install_update)
        row.addWidget(self.install_btn)
        self.later_btn = QPushButton("Later")
        self.later_btn.clicked.connect(lambda: banner.setVisible(False))
        row.addWidget(self.later_btn)
        banner.setVisible(False)
        self.banner = banner
        return banner

    def schedule_startup_check(self):
        # Defer startup check to the first event-loop tick so headless tests
        # that stop child QTimers do not spawn background QThreads.
        self.startup_checker = UpdateChecker(self.updater, self.window)
        self.startup_checker.update_found.connect(self.on_update_found)
        self.startup_timer = QTimer(self.window)
        self.startup_timer.setSingleShot(True)
        self.startup_timer.setInterval(0)
        self.startup_timer.timeout.connect(self.startup_checker.start)
        self.startup_timer.start()

    def on_update_found(self, info):
        self.pending_update = info
        self.window._pending_update = info
        notes = info.get("notes", "")
        first_line = notes.splitlines()[0] if notes else ""
        text = f"Update v{info.get('version')} is available"
        if first_line:
            text += f" — {first_line}"
        self.banner_label.setText(text)
        self.banner.setVisible(True)

    def check_manual(self):
        if self.manual_checker and self.manual_checker.isRunning():
            return
        self.window.check_updates_btn.setEnabled(False)
        self.window.check_updates_btn.setText("Checking…")
        self.manual_checker = UpdateChecker(self.updater, self.window, diagnose_errors=True)
        self.manual_checker.check_finished.connect(self._on_manual_check_done)
        self.manual_checker.start()

    def _on_manual_check_done(self, info, error_detail):
        self.window.check_updates_btn.setEnabled(True)
        self.window.check_updates_btn.setText("Check for Updates")
        if info:
            self.on_update_found(info)
            QMessageBox.information(
                self.window,
                "Update Available",
                f"Version {info.get('version')} is available.\n\n"
                "Use the banner at the top to install and restart.",
            )
        elif not error_detail:
            QMessageBox.information(
                self.window,
                "Up to Date",
                f"You are running the latest version (v{self.app_version}).",
            )
        else:
            QMessageBox.warning(
                self.window,
                "Update Check Failed",
                "Could not reach the update server.\n\n"
                f"Update source:\n{self.updater.API_LATEST}\n\n"
                f"Details:\n{error_detail}\n\n"
                "Check the internet connection / firewall and try again.",
            )

    def install_update(self):
        info = self.pending_update or self.window._pending_update
        if not info:
            QMessageBox.warning(self.window, "No Update", "No pending update to install.")
            return
        if not getattr(sys, "frozen", False):
            QMessageBox.information(
                self.window,
                "Developer Mode",
                "Updates can only be installed from the packaged .exe, "
                "not when running from source.",
            )
            return

        self.dialog = QProgressDialog("Downloading update…", "Cancel", 0, 100, self.window)
        self.dialog.setWindowTitle("Updating")
        self.dialog.setMinimumDuration(0)
        self.dialog.setValue(0)
        self.window._update_dialog = self.dialog

        self.downloader = UpdateDownloader(self.updater, info, self.window)
        self.downloader.progress.connect(self._on_download_progress)
        self.downloader.finished_path.connect(self._on_download_finished)
        self.dialog.canceled.connect(self.downloader.requestInterruption)
        self.install_btn.setEnabled(False)
        self.downloader.start()

    def _on_download_progress(self, downloaded, total):
        if self.dialog and total > 0:
            self.dialog.setValue(int(downloaded * 100 / total))

    def _on_download_finished(self, path):
        was_cancelled = bool(self.downloader and self.downloader.isInterruptionRequested())
        if self.dialog:
            self.dialog.close()
            self.dialog = None
            self.window._update_dialog = None
        self.install_btn.setEnabled(True)

        if was_cancelled:
            return
        if not path:
            QMessageBox.critical(
                self.window,
                "Update Failed",
                "The update could not be downloaded or failed its integrity "
                "check. Please try again later.",
            )
            return

        self.downloaded_exe = path
        self.window._downloaded_exe = path
        if not self.updater.schedule_update(path):
            QMessageBox.critical(
                self.window,
                "Update Failed",
                "Could not schedule the update install.",
            )
            return
        QMessageBox.information(
            self.window,
            "Restarting",
            "The update has been downloaded. The app will now close and "
            "restart on the new version.",
        )
        self.window.close()

    def shutdown(self):
        for worker in (self.startup_checker, self.manual_checker, self.downloader):
            if worker is not None and worker.isRunning():
                worker.requestInterruption()
                worker.wait(3000)
