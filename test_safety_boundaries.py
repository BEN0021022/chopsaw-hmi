"""UI safety-boundary tests using an in-memory serial connection."""

import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSettings as RealQSettings
from PyQt6.QtWidgets import QApplication

import main
from controller_backends import TEENSY_CARRIAGE, create_controller_backend


class FakeSerial:
    def __init__(self):
        self.is_open = True
        self.writes = []

    def write(self, data):
        self.writes.append(data.decode("utf-8").strip())
        return len(data)

    def close(self):
        self.is_open = False


def main_test():
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as folder:
        settings_path = os.path.join(folder, "settings.ini")
        main.QSettings = lambda *args, **kwargs: RealQSettings(
            settings_path, RealQSettings.Format.IniFormat
        )
        main.updater.check_for_update = lambda *args, **kwargs: None

        window = main.MinimalHMI()
        window.ser = FakeSerial()
        window.connection_controls_enabled = True

        window.controller = create_controller_backend(TEENSY_CARRIAGE)
        window.selected_controller_mode = TEENSY_CARRIAGE
        window.apply_controller_capabilities()
        assert window.full_auto_tab.isEnabled()  # Read-only layout/scenarios stay accessible.
        assert window.full_auto_legacy.isEnabled()  # View remains readable; actuation is gated per button.
        assert not window.fa_start_cycle_button.isEnabled()
        assert not window.controller_combo.isEnabled()

        writes_before = list(window.ser.writes)
        window.clamp_left_engaged = False
        assert window.cylinder_extend(1) is False
        assert not window.clamp_left_engaged
        assert window._actuate_saw() is False
        assert not window.clamps_engaged_cutting
        assert window.ser.writes == writes_before

        window.close()
        app.processEvents()


if __name__ == "__main__":
    main_test()
    print("UI safety boundaries OK")
