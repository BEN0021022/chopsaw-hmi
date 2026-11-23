# config.py

# =============== SERIAL CONFIG ==================
SERIAL_PORT = 'COM3'
BAUD_RATE = 115200

# =============== MACHINE KINEMATICS =============
HOME_POSITION_INCHES = 160.5
STEPS_PER_INCH = 127.12

# =============== PROFILE MAPPING =================
# Legacy Mega / offline simulator profile indices:
PROFILE_MAP = {"NORMAL": 0, "GENTLE": 1, "FAST": 2}
# Teensy native controller profile indices:
TEENSY_PROFILE_MAP = {"COMMISSIONING": 0, "GENTLE": 1, "NORMAL": 2, "FAST": 3}
