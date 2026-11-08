"""Main HMI + Teensy contract tests; all serial writes are in-memory."""
import os
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QSettings as RealQSettings
from PyQt6.QtWidgets import QApplication
import main
from controller_backends import TEENSY_CARRIAGE, create_controller_backend
from teensy_carriage import IDENTITY


class FakeSerial:
    def __init__(self):
        self.is_open = True
        self.writes = []

    def write(self, data):
        self.writes.append(data.decode().strip())
        return len(data)

    def close(self):
        self.is_open = False


def packet(panel, **changes):
    fields = dict(ARMED=0, CONFIGURED=0, READY=0, HOME_VERIFIED=0, HOME_RAW=1,
                  ALARM_RAW=1, STEP=0, DIR=0, ENA=1, BUDGET=0, REMAINING=0,
                  POS_STEPS=0, MOVE_ID=0, UP_MS=1000, CAL_SPI="127.12", FAULT="NONE")
    fields.update(changes)
    panel.handle_line("BENCH_X," + ",".join(f"{k}:{v}" for k, v in fields.items()))


def ready(panel):
    panel.session(True)
    panel.handle_line("BENCH_HELLO," + ",".join(f"{k}:{v}" for k, v in IDENTITY.items()))
    panel.handle_line("BENCH_SAFETY,READY:1,RESET_READY:1,DOOR_CLOSED:1,SAW_POSITION:UP,FAULT:NONE,BLOCKER:NONE")
    panel.handle_line("BENCH_INPUTS,HOME:1,BOARD_EDGE:0,FENCE_DOOR:0,SAW_UP:0,SAW_DOWN:1,CL57T_ALM:1")
    packet(panel, HOME_VERIFIED=1)


def run():
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as folder:
        main.QSettings = lambda *a, **k: RealQSettings(os.path.join(folder, "settings.ini"), RealQSettings.Format.IniFormat)
        main.updater.check_for_update = lambda *a, **k: None
        w = main.MinimalHMI()
        w.controller_combo.setCurrentIndex(w.controller_combo.findData(TEENSY_CARRIAGE))
        w.ser = FakeSerial()
        wire = w.ser
        w.set_controls_enabled(True)
        p = w.carriage_tab
        assert p.connected
        assert not w.legacy_tab.isEnabled() and not w.auto_tab.isEnabled() and not w.full_auto_tab.isEnabled()
        assert not w.active_controller().capabilities.automatic_cycle_ready
        assert not w.active_controller().capabilities.manual_motion_ready
        assert w.active_controller().capabilities.carriage_jog_ready
        assert create_controller_backend(TEENSY_CARRIAGE).startup_commands() == ["HELLO", "PINMAP", "STATUS"]
        assert not wire.writes, "Connecting must not enable/arm or move"
        for cmd in ("S12.5", "V1", "C1", "OUT 0 1", "ARM 1", "XLEVEL 1 0", "G1 X1", "XARM 1", "OFF\nXARM 1"):
            assert not w.send_command(cmd), cmd
        ready(p)
        assert p.sensor_labels["FENCE_DOOR"].text() == "ACTIVE"
        assert p.sensor_labels["CL57T_ALM"].text() == "NORMAL"
        assert p.sensor_labels["BOARD_EDGE"].text() == "ACTIVE"
        assert not p.configure_button.isEnabled()
        p.consent.setChecked(True)
        assert p.configure_button.isEnabled()
        p.configure_button.click()
        assert wire.writes[-1] == "XCONFIG 0 1"
        assert not p.arm_button.isEnabled(), "Wait for configuration ACK"
        packet(p, CONFIGURED=1, READY=1, HOME_VERIFIED=1)
        p.arm_button.click()
        assert wire.writes[-1] == "XARM 1"
        assert not p.toward_saw.isEnabled(), "Wait for arm ACK"
        packet(p, ARMED=1, CONFIGURED=1, HOME_VERIFIED=1, ENA=0, BUDGET=254)
        assert p.toward_saw.isEnabled() and not p.toward_saw.autoRepeat()
        p.toward_saw.click()
        assert wire.writes[-1] == "XJOG -1 13"
        before = len(wire.writes)
        p.jog(1)
        assert len(wire.writes) == before, "No duplicate while awaiting ACK"
        packet(p, ARMED=1, CONFIGURED=1, HOME_VERIFIED=1, ENA=0, BUDGET=254)
        assert p.pending is not None, "Old telemetry must not acknowledge a new move"
        packet(p, ARMED=1, CONFIGURED=1, HOME_VERIFIED=1, ENA=0, BUDGET=250, REMAINING=9, POS_STEPS=-4, MOVE_ID=1)
        assert p.pending is None and not p.toward_home.isEnabled() and not p.distance.isEnabled()
        p.tick()
        assert wire.writes[-1] == "KEEPALIVE"
        packet(p, ARMED=1, CONFIGURED=1, HOME_VERIFIED=1, ENA=0, BUDGET=241, POS_STEPS=-13, MOVE_ID=1)
        assert "-0.1023" in p.position.text()
        assert w.homed_label.text() == "NOT HOMED", "Pulse count is not an absolute or encoder position"
        for distance, count in ((0.25, 32), (0.5, 64), (1, 127), (2, 254)):
            packet(p, ARMED=1, CONFIGURED=1, HOME_VERIFIED=1, ENA=0, BUDGET=254, MOVE_ID=count)
            p.distance.setValue(distance)
            p.toward_home.click()
            assert wire.writes[-1] == f"XJOG 1 {count}"
            packet(p, ARMED=1, CONFIGURED=1, HOME_VERIFIED=1, ENA=0, BUDGET=254, MOVE_ID=count+1)
        packet(p, ARMED=1, CONFIGURED=1, HOME_VERIFIED=1, ENA=0, BUDGET=10)
        assert not p.toward_saw.isEnabled(), "Enforce remaining budget"
        assert not w.send_command("XJOG 1 255") and not w.send_command("XJOG 1 1 EXTRA")

        packet(p, ARMED=1, CONFIGURED=1, HOME_VERIFIED=1, ENA=0, BUDGET=254)
        p.stop()
        assert p.stopping and not p.allowed("XJOG 1 13"), "Wait for stop ACK"
        packet(p, ARMED=0, CONFIGURED=1, HOME_VERIFIED=1, ENA=0, BUDGET=254)
        assert not p.stopping
        packet(p, ARMED=1, CONFIGURED=1, HOME_VERIFIED=1, ENA=0, BUDGET=254)
        # Stale safety alone must stop, even with fresh motion telemetry.
        p.received["SAFETY"] -= 3
        p.tick()
        assert wire.writes[-1] == "OFF" and p.local_fault and not p.consent.isChecked()
        p.handle_line("BENCH_SAFETY,READY:1,DOOR_CLOSED:1,SAW_POSITION:UP,FAULT:NONE")
        assert not p.toward_home.isEnabled(), "Late telemetry must not rearm"
        packet(p, UP_MS=2000)
        p.acknowledge()
        assert wire.writes[-1] == "RESET" and not p.consent.isChecked()
        ready(p)
        p.consent.setChecked(True)
        packet(p, ARMED=1, CONFIGURED=1, HOME_VERIFIED=1, ENA=0, BUDGET=254, UP_MS=3000)
        packet(p, UP_MS=100)
        assert "restarted" in p.local_fault and not p.consent.isChecked()

        # Invalid packets and missing move ACKs fail closed.
        ready(p)
        p.handle_line("BENCH_X,ARMED:1")
        assert p.local_fault and wire.writes[-1] == "OFF"
        ready(p)
        p.consent.setChecked(True)
        packet(p, ARMED=1, CONFIGURED=1, HOME_VERIFIED=1, ENA=0, BUDGET=254)
        p.pending = (0, time.monotonic()-2)
        p.tick()
        assert p.local_fault == "Move acknowledgment timed out" and wire.writes[-1] == "OFF"
        ready(p)
        p.consent.setChecked(True)
        wrong = dict(IDENTITY, X_MAP="STEP2_DIR3_EN10")
        p.handle_line("BENCH_HELLO," + ",".join(f"{k}:{v}" for k,v in wrong.items()))
        assert not p.compatible and wire.writes[-1] == "OFF"
        ready(p)
        p.release_button.click()
        assert wire.writes[-1] == "XDISABLE"
        p.received["INPUTS"] -= 3
        p.refresh()
        assert p.sensor_labels["HOME"].text() == "UNKNOWN"
        # The real main serial message handler routes Teensy telemetry to this tab.
        w.update_message_log("BENCH_INPUTS,HOME:0,BOARD_EDGE:1,FENCE_DOOR:0,SAW_UP:0,SAW_DOWN:1,CL57T_ALM:1")
        assert p.sensor_labels["HOME"].text() == "ACTIVE"
        w._stop_listener()
        assert wire.writes[-1] == "OFF" and not wire.is_open and not p.connected
        w.update_message_log("BENCH_HELLO," + ",".join(f"{k}:{v}" for k,v in IDENTITY.items()))
        assert not p.compatible, "Disconnected/old-session telemetry must be ignored"
        w.close()
        app.processEvents()
    print("Teensy main-app carriage integration tests passed")


if __name__ == "__main__":
    run()
