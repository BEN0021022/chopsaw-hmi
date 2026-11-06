"""Small, deliberately constrained serial transport for the sensor bench."""

from __future__ import annotations

import threading
import re

import serial
from serial.tools import list_ports
from PyQt6.QtCore import QObject, pyqtSignal


READ_COMMANDS = frozenset({"HELLO", "PING", "PINMAP", "I2C", "STATUS"})
CONTROL_COMMANDS = frozenset({"ARM 0", "ARM 1", "KEEPALIVE", "OFF"})
OUTPUT_COMMAND = re.compile(r"OUT [0-2] [01]")


def is_allowed_command(command: str) -> bool:
    """Allow only telemetry and the three guarded clamp-test outputs."""
    normalized = " ".join(command.strip().upper().split())
    return (
        normalized in READ_COMMANDS
        or normalized in CONTROL_COMMANDS
        or OUTPUT_COMMAND.fullmatch(normalized) is not None
    )


class SerialLink(QObject):
    line_received = pyqtSignal(str)
    connected = pyqtSignal(str)
    disconnected = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._serial: serial.Serial | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._write_lock = threading.Lock()

    @property
    def is_connected(self) -> bool:
        return bool(self._serial and self._serial.is_open)

    @staticmethod
    def ports() -> list[tuple[str, str, int | None]]:
        result = []
        for port in list_ports.comports():
            label = f"{port.device} - {port.description or 'Serial device'}"
            result.append((port.device, label, port.vid))
        return sorted(result, key=lambda item: item[0])

    def open(self, port: str, baudrate: int = 115200) -> None:
        self.close(emit=False)
        try:
            self._serial = serial.Serial(
                port=port,
                baudrate=baudrate,
                timeout=0.15,
                write_timeout=1.0,
            )
        except (serial.SerialException, OSError) as error:
            self._serial = None
            self.disconnected.emit(str(error) or f"Unable to open {port}")
            return

        self._stop.clear()
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()
        self.connected.emit(port)

    def send(self, command: str) -> bool:
        normalized = " ".join(command.strip().upper().split())
        if not is_allowed_command(normalized) or not self.is_connected:
            return False
        try:
            with self._write_lock:
                assert self._serial is not None
                self._serial.write((normalized + "\n").encode("ascii"))
                self._serial.flush()
            return True
        except (serial.SerialException, OSError) as error:
            self.disconnected.emit(str(error) or "Serial write failed")
            self.close(emit=False)
            return False

    def close(self, emit: bool = True) -> None:
        was_connected = self.is_connected
        self._stop.set()
        if self._serial is not None:
            try:
                self._serial.close()
            except (serial.SerialException, OSError):
                pass
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)
        self._serial = None
        self._thread = None
        if emit and was_connected:
            self.disconnected.emit("Disconnected")

    def _listen(self) -> None:
        try:
            while not self._stop.is_set() and self._serial and self._serial.is_open:
                data = self._serial.readline()
                if not data:
                    continue
                line = data.decode("utf-8", errors="replace").strip()
                if line:
                    self.line_received.emit(line)
        except (serial.SerialException, OSError) as error:
            if not self._stop.is_set():
                self.disconnected.emit(str(error) or "Serial connection lost")

    def shutdown(self) -> None:
        self.close(emit=False)
