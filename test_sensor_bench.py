"""Parser, command-boundary, and offscreen UI checks for the sensor bench."""

import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSettings as RealQSettings
from PyQt6.QtWidgets import QApplication

import sensor_bench.window as window_module
from sensor_bench.protocol import parse_int, parse_line
from sensor_bench.serial_link import is_allowed_command


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
    for command in ("HELLO", "status", "ARM 1", "ARM 0", "KEEPALIVE", "OFF", "OUT 0 1", "out 2 0"):
        assert is_allowed_command(command)
    for command in ("OUT 3 1", "OUT 0 2", "G0 X10", "$H", "EN 1", "M3", "RESET", "OUT 0 1 EXTRA"):
        assert not is_allowed_command(command)


def test_ui():
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as folder:
        settings_path = os.path.join(folder, "sensor-bench.ini")
        window_module.QSettings = lambda *args, **kwargs: RealQSettings(
            settings_path, RealQSettings.Format.IniFormat
        )
        window = window_module.SensorBenchWindow()
        assert "Saw Cylinder" in window_module.PNEUMATIC_OUTPUTS[0][1]
        assert "Main Clamp" in window_module.PNEUMATIC_OUTPUTS[1][1]
        assert "Spare" in window_module.PNEUMATIC_OUTPUTS[2][1]

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
        window.handle_line("BENCH_HELLO,PROTO:2,FW:test,MOTION:0,TEST_OUTPUTS:3")
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
        window.close()
        app.processEvents()


def main():
    test_protocol()
    test_command_boundary()
    test_ui()
    print("Sensor bench protocol and UI tests passed")


if __name__ == "__main__":
    main()
