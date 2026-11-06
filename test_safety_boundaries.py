"""UI safety-boundary tests using an in-memory serial connection."""

import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSettings as RealQSettings
from PyQt6.QtWidgets import QApplication

import main
from controller_backends import TEENSY_GRBLHAL, TEENSY_HARDWARE_TEST, create_controller_backend


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

        window.controller = create_controller_backend(TEENSY_GRBLHAL)
        window.selected_controller_mode = TEENSY_GRBLHAL
        window.apply_controller_capabilities()
        assert not window.legacy_tab.isEnabled()
        assert not window.auto_tab.isEnabled()
        assert not window.full_auto_tab.isEnabled()
        assert not window.controller_combo.isEnabled()

        window.clamp_left_engaged = False
        assert window.cylinder_extend(1) is False
        assert not window.clamp_left_engaged
        assert window._actuate_saw() is False
        assert not window.clamps_engaged_cutting

        window.controller = create_controller_backend(TEENSY_HARDWARE_TEST)
        assert window.set_actuator_direction("forward")
        assert window.ser.writes[-3:] == ["OUT 3 0", "OUT 4 0", "OUT 3 1"]
        assert window.set_actuator_direction("reverse")
        assert window.ser.writes[-3:] == ["OUT 3 0", "OUT 4 0", "OUT 4 1"]

        window.close()
        app.processEvents()


if __name__ == "__main__":
    main_test()
    print("UI safety boundaries OK")
