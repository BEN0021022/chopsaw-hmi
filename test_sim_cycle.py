import time
from PyQt6.QtWidgets import QApplication

app = QApplication([])
import main

w = main.MinimalHMI()
w.show()

# Connect to the simulator port
idx = w.port_combo.findData("SIM")
assert idx >= 0, "SIM port entry missing"
w.port_combo.setCurrentIndex(idx)
assert w.selected_serial_port == "SIM"
w.toggle_connection()
assert w.ser is not None and w.ser.is_open
assert w.status_label.text() == "SIM MODE"
print("connected to virtual controller")

seen_bsen = {"v": False}
w.signal_bridge.board_sensor_state_updated.connect(
    lambda s: seen_bsen.__setitem__("v", seen_bsen["v"] or s == 1))


def pump_until(cond, timeout, what):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)
        if cond():
            return
    raise AssertionError("timeout waiting for " + what)


# Speed everything up for the test
for sb in (w.norm_speed, w.gentle_speed, w.fast_speed):
    sb.setValue(20000)
for sb in (w.norm_accel, w.gentle_accel, w.fast_accel):
    sb.setValue(50000)
w.fa_clamp_engage_delay.setValue(40)
w.fa_saw_start_delay.setValue(60)

w.home_motor()
pump_until(lambda: w.homed_label.text() == "HOMED", 15, "homing")
assert abs(w.current_position - 160.5) < 0.01
print(f"homed at {w.current_position:.2f}")

w.load_cut_list_lines(["18 A", "24 B", "30 C"])
w.start_auto_cycle()

# Truing cut: wait for the stroke to finish (board trimmed), then acknowledge
pump_until(lambda: w.sim_board_trimmed and not w.clamps_engaged_cutting
           and w.auto_cycle_state == "WAITING_FOR_TRUING_CUT", 25, "truing cut")
assert seen_bsen["v"], "board sensor never tripped during detect"
print(f"truing done, board remaining {w.sim_board_remaining:.2f}")
assert abs(w.sim_board_remaining - 144.5) < 0.01
w.cut_complete_pressed()

# Cuts 1 and 2 need CUT COMPLETE; cut 3 is the early-return cut
for n in (1, 2):
    pump_until(lambda: w.sim_next_piece_index == n and not w.clamps_engaged_cutting
               and w.auto_cycle_state == "WAITING_FOR_CUT", 30, f"cut {n}")
    print(f"cut {n} done, board remaining {w.sim_board_remaining:.2f}, "
          f"ejected: {w.saw_sim._eject['label']}")
    w.cut_complete_pressed()

# Cut 3 runs with early return; cycle finishes on its own. The carriage can
# arrive home before the saw stroke completes, so wait for both.
pump_until(lambda: w.auto_cycle_state == "FINISHED", 40, "cycle complete")
pump_until(lambda: w.sim_next_piece_index == 3 and not w.clamps_engaged_cutting,
           15, "final saw stroke")
assert "Complete" in w.auto_status_label.text(), w.auto_status_label.text()
print(f"cycle complete; ejected: {w.saw_sim._eject['label']}")

expected_remaining = 145.5 - 1.0 - (18 + 0.1) - (24 + 0.1) - (30 + 0.1)
assert abs(w.sim_board_remaining - expected_remaining) < 0.01, w.sim_board_remaining
assert w.sim_next_piece_index == 3
assert w.saw_sim._eject["label"] == '30"'
assert abs(w.current_position - 160.5) < 0.01, "carriage should be back at load"

# Widget paints without errors
img = w.saw_sim.grab()
assert not img.isNull() and img.width() > 0

w.toggle_connection()
assert not w.ser.is_open
w.close()
print("FULL CYCLE SIM TEST OK")
