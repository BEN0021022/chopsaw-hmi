import os
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSettings as RealQSettings
from PyQt6.QtWidgets import QApplication

app = QApplication([])
import main

settings_dir = tempfile.TemporaryDirectory()
settings_path = os.path.join(settings_dir.name, "settings.ini")
main.QSettings = lambda *args, **kwargs: RealQSettings(
    settings_path, RealQSettings.Format.IniFormat
)
main.updater.check_for_update = lambda *args, **kwargs: None


def pump(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.004)


def pump_until(cond, timeout, what):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.004)
        if cond():
            return
    raise AssertionError("timeout waiting for " + what)


def make_window(auto_clamp):
    w = main.MinimalHMI()
    w.show()
    w._sent = []
    orig = w.send_command
    w.send_command = lambda c: (w._sent.append(c), orig(c))[1]
    idx = w.port_combo.findData("SIM")
    w.port_combo.setCurrentIndex(idx)
    w.toggle_connection()
    w.auto_clamp_checkbox.setChecked(auto_clamp)
    for sb in (w.norm_speed, w.gentle_speed, w.fast_speed):
        sb.setValue(20000)
    for sb in (w.norm_accel, w.gentle_accel, w.fast_accel):
        sb.setValue(50000)
    w.fa_clamp_engage_delay.setValue(20)
    w.fa_saw_start_delay.setValue(20)
    w.home_motor()
    pump_until(lambda: w.homed_label.text() == "HOMED", 15, "homing")
    w.load_cut_list_lines(["18 A", "24 B", "30 C"])
    w.start_auto_cycle()
    return w


def drive_to_finish(w):
    """Press CUT COMPLETE whenever the cycle stops for a manual/ack cut."""
    deadline = time.monotonic() + 60
    while w.auto_cycle_state != "FINISHED" and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.004)
        waiting = w.auto_cycle_state in ("WAITING_FOR_TRUING_CUT", "WAITING_FOR_CUT")
        if waiting and w.cut_complete_button.isEnabled():
            pump(0.10)  # let any clamp/saw commands fire first
            w.cut_complete_pressed()
            pump_until(lambda: not w.cut_complete_button.isEnabled()
                       or w.auto_cycle_state == "FINISHED", 5, "advance after cut")
    assert w.auto_cycle_state == "FINISHED", f"stuck in {w.auto_cycle_state}"


# ---- Manual mode: zero cylinder/saw commands ----
w = make_window(auto_clamp=False)
drive_to_finish(w)
clamp_saw = [c for c in w._sent if c in ("C1", "C2", "C3", "D1", "D2", "D3", "V1")]
assert not clamp_saw, f"manual mode leaked clamp/saw commands: {clamp_saw}"
assert any(c.startswith("J") for c in w._sent), "no detect (J) command sent"
assert any(c.startswith("S") for c in w._sent), "no move (S) command sent"
w.toggle_connection(); w.close()
print("manual mode: NO clamp/saw commands, cycle reached FINISHED  OK")

# ---- Auto mode (simulator handles C1-3 safely): clamps + saw fire ----
w = make_window(auto_clamp=True)
drive_to_finish(w)
assert any(c in ("C1", "C2", "C3") for c in w._sent), "auto mode should extend cylinders"
assert any(c in ("D1", "D2", "D3") for c in w._sent), "auto mode should retract cylinders"
assert any(c == "V1" for c in w._sent), "auto mode should actuate saw (sim)"
w.toggle_connection(); w.close()
print("auto mode: cylinder + saw commands present  OK")

# ---- Firmware-matching home default ----
w = main.MinimalHMI()
assert abs(w.home_position - 160.5) < 1e-6, w.home_position
w.close()
print("home_position default 160.5  OK")

print("ALL MANUAL-MODE TESTS OK")
settings_dir.cleanup()
