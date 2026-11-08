"""Parser, command-boundary, and offscreen UI checks for the sensor bench."""

import os
import tempfile
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSettings as RealQSettings
from PyQt6.QtWidgets import QApplication

import sensor_bench.window as window_module
from sensor_bench.protocol import parse_int, parse_line
from sensor_bench.serial_link import SerialLink, is_allowed_command


def test_protocol():
    hello = parse_line("BENCH_HELLO,PROTO:2,FW:0.3.0,MOTION:0,TEST_OUTPUTS:3")
    assert hello and hello.kind == "BENCH_HELLO"
    assert hello.fields["FW"] == "0.3.0"

    inputs = parse_line("BENCH_INPUTS,SEQ:8,HOME:1,BOARD_EDGE:0")
    assert inputs and inputs.fields["BOARD_EDGE"] == "0"

    old = parse_line("KLF_IO,HOME[X_LIMIT/D20]:0,BOARD_EDGE[PROBE/D15]:1")
    assert old and old.kind == "LEGACY_INPUTS"
    assert old.fields == {"HOME": "0", "BOARD_EDGE": "1"}

    found = parse_line("I2C: found 0x27")
    assert found and found.fields["ADDRESS"] == "0X27"
    assert parse_int("0xFF") == 255
    assert parse_int("broken") is None

    outputs = parse_line("BENCH_OUTPUTS,ARMED:1,CLAMP1:1,CLAMP2:0,CLAMP3:0,FAULT:NONE")
    assert outputs and outputs.fields["CLAMP1"] == "1"


def test_command_boundary():
    for command in ("HELLO", "status", "ARM 1", "ARM 0", "KEEPALIVE", "OFF", "RESET", "OUT 0 1", "out 2 0",
                    "XLEVEL 0 1", "XCONFIG 1 0", "XARM 1", "XARM 0", "XSTEP -1", "XSTEP 1", "XJOG -1 13", "XJOG 1 64", "XJOG 1 127"):
        assert is_allowed_command(command)
    for command in ("OUT 3 1", "OUT 0 2", "G0 X10", "$H", "EN 1", "M3", "REBOOT", "OUT 0 1 EXTRA",
                    "XJOG 1 254", "XJOG 0 13", "XJOG 1 127 EXTRA", "XSTEP 10", "XSTEP 0", "XSTEP 1 EXTRA", "XCONFIG 2 0", "XARM 2"):
        assert not is_allowed_command(command)


def test_listener_shutdown():
    started, cancelled = threading.Event(), threading.Event()

    class BlockingPort:
        is_open = True

        def readline(self):
            started.set()
            assert cancelled.wait(2), "Closing must wake the pending read"
            assert self.is_open, "The port must remain valid until the read returns"
            return b""

        def cancel_read(self):
            cancelled.set()

        def close(self):
            self.is_open = False

    link = SerialLink()
    port = BlockingPort()
    link._serial = port
    listener = threading.Thread(target=link._listen, daemon=True)
    link._thread = listener
    listener.start()
    assert started.wait(1)
    link.close(emit=False)
    assert not listener.is_alive() and not port.is_open


def test_ui():
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as folder:
        settings_path = os.path.join(folder, "sensor-bench.ini")
        window_module.QSettings = lambda *args, **kwargs: RealQSettings(
            settings_path, RealQSettings.Format.IniFormat
        )
        settings = RealQSettings(settings_path, RealQSettings.Format.IniFormat)
        settings.setValue("polarity/SAW_UP", False)
        settings.setValue("polarity/SAW_DOWN", False)
        settings.setValue("polarity/SAW_UP/D17", False)
        settings.sync()
        window = window_module.SensorBenchWindow()
        for key, terminal, pin in (("SAW_UP", "Limit Z", "D22"), ("SAW_DOWN", "Fd/Hld", "D16")):
            row = window.sensor_rows[key]
            assert (row.definition.connection, row.definition.pin) == (terminal, pin)
            assert row.polarity.isChecked(), "Old ST polarity must not invert the new opto input"
            window.handle_line(f"BENCH_INPUTS,{key}:1")
            assert row.state.text() == "OFF"
            window.handle_line(f"BENCH_INPUTS,{key}:0")
            assert row.state.text() == "ON"
        assert "Saw Cylinder" in window_module.PNEUMATIC_OUTPUTS[0][1]
        assert "Main Clamp" in window_module.PNEUMATIC_OUTPUTS[1][1]
        assert "Blade Trigger" in window_module.PNEUMATIC_OUTPUTS[2][1]
        assert window_module.PNEUMATIC_OUTPUTS[0][2:4] == ("AUX2 TTL", "D33")
        assert window_module.PNEUMATIC_OUTPUTS[2][2:4] == ("Flood TTL", "D19")

        class FakeSerial:
            is_open = True

            def __init__(self):
                self.writes = []

            def write(self, data):
                self.writes.append(data.decode("ascii").strip())

            def flush(self):
                pass

            def close(self):
                self.is_open = False

        fake_serial = FakeSerial()
        window.link._serial = fake_serial
        for output_map in ("", ",OUTPUT_MAP:OLD_MAP", ",OUTPUT_MAP:AUX2_AUX1_FLOOD"):
            window.handle_line(f"BENCH_HELLO,PROTO:2,FW:0.3.1,MOTION:0,TEST_OUTPUTS:3{output_map}")
            window.output_confirmation.setChecked(True)
            assert not window.output_capable
            assert not window.output_arm_button.isEnabled()
            window.output_arm_button.click()
            assert not any(command == "ARM 1" for command in fake_serial.writes)
        window.output_confirmation.setChecked(False)
        window.handle_line(
            "BENCH_HELLO,PROTO:2,FW:0.4.0,MOTION:0,TEST_OUTPUTS:3,OUTPUT_MAP:AUX2_AUX1_FLOOD,"
            "INTERLOCKS:DOOR_POSITION_V1,COMMISSIONING:LOGIC_ONLY"
        )
        assert not window.output_capable, "Old Cyc/St firmware must not drive Limit Z controls"
        window.handle_line(
            "BENCH_HELLO,PROTO:2,FW:0.4.1,MOTION:0,TEST_OUTPUTS:3,OUTPUT_MAP:AUX2_AUX1_FLOOD,INPUT_MAP:DOOR29_UP22_DOWN16,"
            "INTERLOCKS:DOOR_POSITION_V1,COMMISSIONING:LOGIC_ONLY"
        )
        window.handle_line(
            "BENCH_HEALTH,SEQ:1,UP_MS:50,MCP_ACK:1,MCP_IO:1,"
            "INA_ACK:1,INA_ID:1,INA_MFG:0x5449,INA_DEV:0x228"
        )
        window.handle_line(
            "BENCH_INPUTS,SEQ:1,HOME:1,BOARD_EDGE:0,FENCE_DOOR:1,"
            "CL57T_ALM:1,SAW_UP:1,SAW_DOWN:1,FENCE_CLOSED:1,OUTFEED:1"
        )
        window.handle_line("BENCH_MCP,SEQ:1,GPIOA:0xFE,GPIOB:0xFF")
        window.handle_line("BENCH_OUTPUTS,ARMED:0,CLAMP1:0,CLAMP2:0,CLAMP3:0,FAULT:NONE")
        app.processEvents()

        assert window.teensy_card.status.text() == "HEALTHY"
        assert window.mcp_card.status.text() == "HEALTHY"
        assert window.ina_card.status.text() == "HEALTHY"
        assert window.sensor_rows["BOARD_EDGE"].state.text() == "ON"
        assert window.mcp_pills["PA0"].text() == "LOW / ON"
        assert window.mcp_pills["PB7"].text() == "HIGH / OFF"
        assert not window.output_buttons[0].isEnabled()

        window.output_confirmation.setChecked(True)
        assert not window.output_arm_button.isEnabled(), "No controller permit received"
        window.handle_line(
            "BENCH_SAFETY,DOOR_CLOSED:0,SAW_POSITION:UP,READY:0,RESET_READY:0,FAULT:NONE,BLOCKER:DOOR_OPEN"
        )
        assert not window.output_arm_button.isEnabled()
        window.handle_line(
            "BENCH_SAFETY,DOOR_CLOSED:1,SAW_POSITION:UP,READY:1,RESET_READY:1,FAULT:NONE,BLOCKER:NONE"
        )
        assert window.output_arm_button.isEnabled()
        window.output_arm_button.click()
        assert fake_serial.writes[-1] == "ARM 1"
        window.handle_line("BENCH_OUTPUTS,ARMED:1,CLAMP1:0,CLAMP2:0,CLAMP3:0,FAULT:NONE")
        assert window.output_buttons[0].isEnabled()
        window.output_buttons[0].pressed.emit()
        window.handle_line("BENCH_OUTPUTS,ARMED:1,CLAMP1:1,CLAMP2:0,CLAMP3:0,FAULT:NONE")
        assert fake_serial.writes[-1] == "OUT 0 1"
        assert window.output_state_pills["CLAMP1"].text() == "ENERGIZED"
        window.output_buttons[0].released.emit()
        assert fake_serial.writes[-1] == "OUT 0 0"
        window.output_buttons[2].pressed.emit()
        assert fake_serial.writes[-1] == "OUT 2 1"
        window.handle_line("BENCH_OUTPUTS,ARMED:1,CLAMP1:0,CLAMP2:0,CLAMP3:1,FAULT:NONE")
        assert window.output_state_pills["CLAMP3"].text() == "ENERGIZED"
        window.output_buttons[2].released.emit()
        assert fake_serial.writes[-1] == "OUT 2 0"
        window.handle_line("BENCH_OUTPUTS,ARMED:0,CLAMP1:0,CLAMP2:0,CLAMP3:0,FAULT:DOOR_OPEN")
        window.handle_line(
            "BENCH_SAFETY,DOOR_CLOSED:0,SAW_POSITION:UP,READY:0,RESET_READY:0,FAULT:DOOR_OPEN,BLOCKER:DOOR_OPEN"
        )
        assert not window.output_arm_button.isEnabled()
        assert not window.output_reset_button.isEnabled()
        writes_before = len(fake_serial.writes)
        window.handle_line(
            "BENCH_SAFETY,DOOR_CLOSED:1,SAW_POSITION:UP,READY:0,RESET_READY:1,FAULT:DOOR_OPEN,BLOCKER:DOOR_OPEN"
        )
        assert not window.output_arm_button.isEnabled(), "Closing door cannot rearm"
        assert len(fake_serial.writes) == writes_before
        assert window.output_reset_button.isEnabled()
        window.output_reset_button.click()
        assert fake_serial.writes[-1] == "RESET"
        window.handle_line(
            "BENCH_SAFETY,DOOR_CLOSED:1,SAW_POSITION:UP,READY:1,RESET_READY:1,FAULT:NONE,BLOCKER:NONE"
        )
        assert not window.outputs_armed
        assert not window.output_buttons[0].isEnabled(), "Reset must not arm or energize"
        assert fake_serial.writes[-1] == "RESET"
        window.outputs_armed = True
        window.last_safety_at -= 3
        window._send_output_keepalive()
        assert fake_serial.writes[-1] == "RESET", "Stale controller checks must stop keepalive"
        window._update_age()
        assert fake_serial.writes[-1] == "OFF"
        assert not window.output_arm_button.isEnabled()
        window.handle_line("BENCH_HELLO,X_TEST:SINGLE_STEP_V1")
        assert not window.x_capable, "Old or absent X map must block stepper controls"
        window.handle_line("BENCH_HELLO,X_TEST:SINGLE_STEP_V1,X_MAP:STEP2_DIR3_EN10")
        assert not window.x_capable, "Wrong enable map must block stepper controls"
        window.handle_line(
            "BENCH_HELLO,PROTO:2,FW:0.6.0,MOTION:1,TEST_OUTPUTS:3,OUTPUT_MAP:AUX2_AUX1_FLOOD,"
            "INPUT_MAP:DOOR29_UP22_DOWN16,INTERLOCKS:DOOR_POSITION_V1,COMMISSIONING:VALVES_ISOLATED,X_TEST:BOUNDED_JOG_V1,X_MAP:STEP2_DIR3_EN40"
        )
        window.handle_line(
            "BENCH_SAFETY,DOOR_CLOSED:1,SAW_POSITION:UP,READY:1,RESET_READY:1,FAULT:NONE,BLOCKER:NONE"
        )
        window.handle_line("BENCH_X,ARMED:0,CONFIGURED:0,READY:0,HOME_VERIFIED:0,ALARM_RAW:1,HOME_RAW:1,STEP:0,DIR:0,ENA:1,BUDGET:0,FAULT:NONE")
        window._show_x_dialog()
        assert not window.x_level_buttons[0].isEnabled()
        assert not window.x_step_buttons[0].isEnabled()
        window.x_pin_confirmation.setChecked(True)
        window.x_level_buttons[0].click()
        assert fake_serial.writes[-1] == "XLEVEL 0 1"
        window.x_enable_combo.setCurrentIndex(1)
        window.x_alarm_combo.setCurrentIndex(2)
        window.x_confirmation.setChecked(True)
        assert not window.x_pin_confirmation.isChecked(), "Signal checks must not stay enabled for powered setup"
        assert not window.x_config_button.isEnabled(), "Home input must be tested"
        window.handle_line("BENCH_X,ARMED:0,CONFIGURED:0,READY:0,HOME_VERIFIED:1,ALARM_RAW:1,HOME_RAW:1,STEP:0,DIR:0,ENA:1,BUDGET:0,FAULT:NONE")
        window.x_config_button.click()
        assert fake_serial.writes[-1] == "XCONFIG 0 1"
        assert not window.x_arm_button.isEnabled(), "Wait for controller acknowledgment"
        window.handle_line("BENCH_X,ARMED:0,CONFIGURED:1,READY:1,HOME_VERIFIED:1,ALARM_RAW:1,HOME_RAW:1,STEP:0,DIR:0,ENA:1,BUDGET:0,FAULT:NONE")
        window.x_arm_button.click()
        assert fake_serial.writes[-1] == "XARM 1"
        window.handle_line("BENCH_X,ARMED:1,CONFIGURED:1,READY:0,HOME_VERIFIED:1,ALARM_RAW:1,HOME_RAW:1,STEP:0,DIR:0,ENA:0,BUDGET:254,REMAINING:0,FAULT:NONE")
        assert not window.output_arm_button.isEnabled()
        window.x_step_buttons[0].click()
        assert fake_serial.writes[-1] == "XJOG -1 13"
        window.handle_line("BENCH_X,ARMED:1,CONFIGURED:1,READY:0,HOME_VERIFIED:1,ALARM_RAW:1,HOME_RAW:1,STEP:0,DIR:0,ENA:0,BUDGET:254,REMAINING:13,FAULT:NONE")
        assert not window.x_step_buttons[0].isEnabled()
        assert not window.x_increment_combo.isEnabled()
        window.handle_line("BENCH_X,ARMED:1,CONFIGURED:1,READY:0,HOME_VERIFIED:1,ALARM_RAW:1,HOME_RAW:1,STEP:0,DIR:0,ENA:0,BUDGET:241,REMAINING:0,FAULT:NONE")
        window.x_increment_combo.setCurrentIndex(3)
        window.x_step_buttons[1].click()
        assert fake_serial.writes[-1] == "XJOG 1 127"
        assert not window.x_step_buttons[0].autoRepeat()
        window._send_output_keepalive()
        assert fake_serial.writes[-1] == "KEEPALIVE"
        window.x_dialog.close()
        assert fake_serial.writes[-1] == "OFF"
        window.close()
        app.processEvents()


def main():
    test_protocol()
    test_command_boundary()
    test_listener_shutdown()
    test_ui()
    print("Sensor bench protocol and UI tests passed")


if __name__ == "__main__":
    main()
