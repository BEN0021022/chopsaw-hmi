"""Unit tests for serial_handler Teensy USB auto-detection and listener reads."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import threading
from types import SimpleNamespace
import unittest

import serial
from PyQt6.QtWidgets import QApplication

from serial_handler import (
    SignalBridge,
    TEENSY_USB_VID,
    is_teensy_port,
    listen_for_data,
    pick_preferred_serial_port,
)


class _FakeBlockingSerial(serial.Serial):
    """Subclass of serial.Serial that exercises the blocking readline() path without OS ports."""

    def __init__(self, lines):
        self.is_open = True
        self._lines = list(lines)

    def readline(self, size=-1):
        if self._lines:
            return self._lines.pop(0)
        self.is_open = False
        return b""


class SerialHandlerTests(unittest.TestCase):
    def test_teensy_port_detection_and_preference(self):
        bt = SimpleNamespace(device="COM3", description="Standard Serial over Bluetooth", vid=0x0A12, manufacturer="")
        teensy = SimpleNamespace(device="COM7", description="USB Serial Device", vid=TEENSY_USB_VID, manufacturer="PJRC")
        named = SimpleNamespace(device="COM9", description="Teensy 4.1 Serial", vid=None, manufacturer="")

        self.assertFalse(is_teensy_port(bt))
        self.assertTrue(is_teensy_port(teensy))
        self.assertTrue(is_teensy_port(named))

        # Reassigned COM port (saved COM4 is gone) -> auto-selects Teensy COM7 instead of Bluetooth COM3
        self.assertEqual(pick_preferred_serial_port([bt, teensy], "COM4"), "COM7")
        # Saved port still present -> keep it
        self.assertEqual(pick_preferred_serial_port([bt, teensy], "COM3"), "COM3")
        # Explicit SIM preference preserved
        self.assertEqual(pick_preferred_serial_port([bt, teensy], "SIM"), "SIM")
        # No ports -> SIM
        self.assertEqual(pick_preferred_serial_port([], "COM4"), "SIM")

    def test_blocking_serial_listener_dispatches_lines_without_polling(self):
        app = QApplication.instance() or QApplication([])
        bridge = SignalBridge()
        messages = []
        positions = []
        bridge.message_received.connect(messages.append)
        bridge.position_updated.connect(positions.append)

        fake = _FakeBlockingSerial([b"BENCH_HELLO,FW:0.27.0\n", b"POS:42.50,HOMED:1\n"])
        stop_event = threading.Event()
        listen_for_data(fake, bridge, stop_event)
        self.assertEqual(messages, ["BENCH_HELLO,FW:0.27.0", "POS:42.50,HOMED:1"])
        self.assertEqual(positions, [42.5])
        _ = app


if __name__ == "__main__":
    unittest.main()
