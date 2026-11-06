# serial_handler.py

import time

import serial
from PyQt6.QtCore import pyqtSignal, QObject

class SignalBridge(QObject):
    """A bridge for emitting signals from the non-GUI serial thread to the main GUI thread."""
    message_received = pyqtSignal(str)
    position_updated = pyqtSignal(float)
    homed_status_updated = pyqtSignal(int)
    motor_state_updated = pyqtSignal(str)
    sensor_state_updated = pyqtSignal(int)
    board_sensor_state_updated = pyqtSignal(int)
    saw_sensor_state_updated = pyqtSignal(int)
    current_voltage_updated = pyqtSignal(float)
    current_updated = pyqtSignal(float)
    overcurrent_updated = pyqtSignal(int)
    calibration_updated = pyqtSignal(float, float)
    home_position_updated = pyqtSignal(float)
    disconnected = pyqtSignal(str)


def _emit_number(signal, raw, cast):
    """Emit a numeric signal only if the raw field parses cleanly."""
    try:
        value = cast(raw)
    except (TypeError, ValueError):
        return
    signal.emit(value)


def _parse_status_line(line, signal_bridge):
    """Parse a 'POS:...,HOMED:...' status line and emit the matching signals."""
    fields = {}
    for part in line.split(','):
        if ':' in part:
            key, value = part.split(':', 1)
            fields[key] = value
    if 'POS' in fields:
        _emit_number(signal_bridge.position_updated, fields['POS'], float)
    if 'HOMED' in fields:
        _emit_number(signal_bridge.homed_status_updated, fields['HOMED'], int)
    if 'STATE' in fields:
        signal_bridge.motor_state_updated.emit(fields['STATE'])
    if 'SEN' in fields:
        _emit_number(signal_bridge.sensor_state_updated, fields['SEN'], int)
    if 'BSEN' in fields:
        _emit_number(signal_bridge.board_sensor_state_updated, fields['BSEN'], int)
    if 'SSEN' in fields:
        _emit_number(signal_bridge.saw_sensor_state_updated, fields['SSEN'], int)
    if 'CV' in fields:
        _emit_number(signal_bridge.current_voltage_updated, fields['CV'], float)
    if 'CUR' in fields:
        _emit_number(signal_bridge.current_updated, fields['CUR'], float)
    if 'OCT' in fields:
        _emit_number(signal_bridge.overcurrent_updated, fields['OCT'], int)


def _safe_emit(signal, *args):
    """Return False when Qt has already destroyed the receiving QObject."""
    try:
        signal.emit(*args)
        return True
    except RuntimeError:
        return False


def listen_for_data(ser, signal_bridge, stop_event=None):
    """
    Listens for incoming data from the serial port in a separate thread
    and emits signals via the signal_bridge.
    """
    while stop_event is None or not stop_event.is_set():
        try:
            if not ser.is_open:
                if stop_event is None or not stop_event.is_set():
                    _safe_emit(signal_bridge.disconnected, "Serial port closed.")
                break
            if ser.in_waiting > 0:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    signal_bridge.message_received.emit(line)
                    if line.startswith("POS:"):
                        _parse_status_line(line, signal_bridge)
                    elif line.startswith("CAL_SUCCESS:"):
                        try:
                            vals = line.split(':', 1)[1].split(',')
                            signal_bridge.calibration_updated.emit(float(vals[0]), float(vals[1]))
                        except (IndexError, ValueError):
                            signal_bridge.message_received.emit(f"Malformed calibration line: '{line}'")
                    elif line.startswith("STATUS:HOME_POS:"):
                        try:
                            home_pos = float(line.split(':')[2])
                            signal_bridge.home_position_updated.emit(home_pos)
                        except (IndexError, ValueError):
                            signal_bridge.message_received.emit(f"Malformed home position line: '{line}'")
            else:
                time.sleep(0.01)
        except (serial.SerialException, OSError) as error:
            if stop_event is None or not stop_event.is_set():
                _safe_emit(
                    signal_bridge.disconnected,
                    str(error) or "Serial connection lost.",
                )
            break
        except RuntimeError:
            # Qt has destroyed the bridge during application shutdown.
            break
        except Exception as error:
            if stop_event is None or not stop_event.is_set():
                _safe_emit(signal_bridge.disconnected, f"Listener error: {error}")
            break
