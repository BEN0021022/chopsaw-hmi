"""Controller command translation for Teensy Carriage and offline Simulator (Legacy Mega)."""

from dataclasses import dataclass
import math


LEGACY_MEGA = "legacy_mega"
TEENSY_CARRIAGE = "teensy_carriage"


@dataclass(frozen=True)
class ControllerMode:
    key: str
    label: str


@dataclass(frozen=True)
class ControllerCapabilities:
    """Safety-relevant features that the HMI may expose for a backend."""

    carriage_jog_ready: bool = False
    homing_commands: bool = False
    motion_commands: bool = False
    manual_motion_ready: bool = False
    automatic_cycle_ready: bool = False
    clamps: bool = False
    saw: bool = False
    saw_position_feedback: bool = False
    current_monitoring: bool = False

    @property
    def automatic_cutting_ready(self):
        return self.clamps and self.saw and self.saw_position_feedback


CONTROLLER_MODES = (
    ControllerMode(TEENSY_CARRIAGE, "Teensy Carriage"),
)


class ControllerBackend:
    key = ""
    label = ""
    capabilities = ControllerCapabilities()

    def startup_commands(self):
        return []

    def home(self):
        return []

    def near_calibrate(self, sensor_offset_inches):
        return []

    def motor_power(self, enabled):
        return []

    def pid_control(self, enabled):
        return []

    def move_absolute_inches(self, target_inches):
        return []

    def set_motor_parameters(self, speed, accel):
        return []

    def current_monitoring(self, enabled):
        return []

    def current_protection(self, limit_amps, trip_delay_ms):
        return []

    def reset_overcurrent(self):
        return []

    def calibration(self, measured_inches):
        return []

    def profile_select(self, profile_index):
        return []

    def clamp_extend(self, cylinder_id):
        return []

    def clamp_retract(self, cylinder_id):
        return []

    def clamp_all(self, enabled):
        return []

    def saw_actuate(self):
        return []

    def stop_motion(self):
        return []

    def truing_cycle(self, sensor_offset_inches):
        return []


class LegacyMegaBackend(ControllerBackend):
    """Internal backend retained solely for the offline VirtualController simulator."""

    key = LEGACY_MEGA
    label = "Legacy Arduino Mega"
    capabilities = ControllerCapabilities(
        homing_commands=True,
        motion_commands=True,
        manual_motion_ready=True,
        automatic_cycle_ready=True,
        clamps=True,
        saw=True,
        saw_position_feedback=True,
        current_monitoring=True,
    )

    def home(self):
        return ["H"]

    def near_calibrate(self, sensor_offset_inches):
        return [f"N{sensor_offset_inches:.4f}"]

    def motor_power(self, enabled):
        return ["E" if enabled else "X"]

    def pid_control(self, enabled):
        return ["K1" if enabled else "K0"]

    def move_absolute_inches(self, target_inches):
        return [f"S{target_inches:.4f}"]

    def set_motor_parameters(self, speed, accel):
        return [f"A{speed:.0f},{accel:.0f}"]

    def current_monitoring(self, enabled):
        return [f"W{1 if enabled else 0}"]

    def current_protection(self, limit_amps, trip_delay_ms):
        return [f"O{limit_amps:.2f},{int(trip_delay_ms)}"]

    def reset_overcurrent(self):
        return ["R"]

    def calibration(self, measured_inches):
        return [f"C{measured_inches:.4f}"]

    def profile_select(self, profile_index):
        return [f"Z{int(profile_index)}"]

    def clamp_extend(self, cylinder_id):
        return [f"C{int(cylinder_id)}"]

    def clamp_retract(self, cylinder_id):
        return [f"D{int(cylinder_id)}"]

    def clamp_all(self, enabled):
        return ["L" if enabled else "U"]

    def saw_actuate(self):
        return ["V1"]

    def stop_motion(self):
        return ["M0"]

    def truing_cycle(self, sensor_offset_inches):
        return [f"J{sensor_offset_inches:.4f}"]


class TeensyCarriageBackend(ControllerBackend):
    key = TEENSY_CARRIAGE
    label = "Teensy Carriage"
    capabilities = ControllerCapabilities(
        carriage_jog_ready=True,
        motion_commands=True,
        homing_commands=True,
    )

    def startup_commands(self):
        # Reads only. A connect never configures, arms or enables the driver.
        return ["HELLO", "PINMAP", "STATUS"]

    def move_absolute_inches(self, target_inches):
        if not isinstance(target_inches, (int, float)) or not math.isfinite(target_inches) or not 0 <= target_inches <= 160.5:
            return []
        return [f"XMOVE {int(math.floor(target_inches*1000+0.5))}"]

    def profile_select(self, profile_index):
        mapping = {0: 2, 1: 1, 2: 3}
        return [f"XPROFILE {mapping[profile_index]}"] if profile_index in mapping else []

    def home(self):
        return ["XHOME 254"]

    def stop_motion(self):
        return ["OFF"]


def create_controller_backend(mode_key):
    if mode_key == LEGACY_MEGA:
        # Retained only for the offline simulator; not selectable for live serial ports.
        return LegacyMegaBackend()
    return TeensyCarriageBackend()
