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
    current_voltage_updated = pyqtSignal(float)
    current_updated = pyqtSignal(float)
    overcurrent_updated = pyqtSignal(int)
    calibration_updated = pyqtSignal(float, float)
    home_position_updated = pyqtSignal(float)

def listen_for_data(ser, signal_bridge):
    """
    Listens for incoming data from the serial port in a separate thread
    and emits signals via the signal_bridge.
    """
    while True:
        try:
            if not ser.is_open:
                break
            if ser.in_waiting > 0:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    signal_bridge.message_received.emit(line)
                    if line.startswith("POS:"):
                        parts = line.split(',')
                        d = {p.split(':')[0]: p.split(':')[1] for p in parts if ':' in p}
                        if 'POS' in d:
                            try: signal_bridge.position_updated.emit(float(d['POS']))
                            except: pass
                        if 'HOMED' in d:
                            try: signal_bridge.homed_status_updated.emit(int(d['HOMED']))
                            except: pass
                        if 'STATE' in d: signal_bridge.motor_state_updated.emit(d['STATE'])
                        if 'SEN' in d:
                            try: signal_bridge.sensor_state_updated.emit(int(d['SEN']))
                            except: pass
                        if 'BSEN' in d:
                            try: signal_bridge.board_sensor_state_updated.emit(int(d['BSEN']))
                            except: pass
                        if 'CV' in d:
                            try: signal_bridge.current_voltage_updated.emit(float(d['CV']))
                            except: pass
                        if 'CUR' in d:
                            try: signal_bridge.current_updated.emit(float(d['CUR']))
                            except: pass
                        if 'OCT' in d:
                            try: signal_bridge.overcurrent_updated.emit(int(d['OCT']))
                            except: pass
                    elif line.startswith("CAL_SUCCESS:"):
                        try:
                            vals = line.split(':')[1].split(',')
                            signal_bridge.calibration_updated.emit(float(vals[0]), float(vals[1]))
                        except: pass
                    elif line.startswith("STATUS:HOME_POS:"):
                        try:
                            home_pos = float(line.split(':')[2])
                            signal_bridge.home_position_updated.emit(home_pos)
                        except: pass
            else:
                time.sleep(0.01)
        except (serial.SerialException, OSError):
            break
        except Exception as e:
            print(f"Listener error: {e}")
