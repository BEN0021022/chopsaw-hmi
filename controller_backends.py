"""Controller command translation for Mega, Teensy validation, and grblHAL modes."""

from dataclasses import dataclass


LEGACY_MEGA = "legacy_mega"
TEENSY_HARDWARE_TEST = "teensy_hardware_test"
TEENSY_GRBLHAL = "teensy_grblhal"


@dataclass(frozen=True)
class ControllerMode:
    key: str
    label: str


@dataclass(frozen=True)
class ControllerCapabilities:
    """Safety-relevant features that the HMI may expose for a backend."""

    homing_commands: bool = False
    motion_commands: bool = False
    manual_motion_ready: bool = False
    automatic_cycle_ready: bool = False
    clamps: bool = False
    saw: bool = False
    saw_position_feedback: bool = False
    actuator: bool = False
    current_monitoring: bool = False

    @property
    def automatic_cutting_ready(self):
        return self.clamps and self.saw and self.saw_position_feedback


CONTROLLER_MODES = (
    ControllerMode(LEGACY_MEGA, "Legacy Arduino Mega"),
    ControllerMode(TEENSY_HARDWARE_TEST, "Teensy Hardware Test"),
    ControllerMode(TEENSY_GRBLHAL, "Teensy grblHAL"),
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

    def actuator_forward(self, enabled):
        return []

    def actuator_reverse(self, enabled):
        return []

    def actuator_direction(self, direction):
        """Return an interlocked command sequence for off/forward/reverse."""
        return []

    def stop_motion(self):
        return []

    def truing_cycle(self, sensor_offset_inches):
        return []


class LegacyMegaBackend(ControllerBackend):
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


class TeensyHardwareTestBackend(ControllerBackend):
    key = TEENSY_HARDWARE_TEST
    label = "Teensy Hardware Test"
    capabilities = ControllerCapabilities(
        clamps=True,
        actuator=True,
    )

    _CLAMP_OUTPUTS = {
        1: 0,
        2: 1,
        3: 2,
    }

    def startup_commands(self):
        return ["PINMAP", "I2C", "STATUS"]

    def clamp_extend(self, cylinder_id):
        output = self._CLAMP_OUTPUTS.get(int(cylinder_id))
        return [] if output is None else [f"OUT {output} 1"]

    def clamp_retract(self, cylinder_id):
        output = self._CLAMP_OUTPUTS.get(int(cylinder_id))
        return [] if output is None else [f"OUT {output} 0"]

    def clamp_all(self, enabled):
        value = 1 if enabled else 0
        return [f"OUT {output} {value}" for output in self._CLAMP_OUTPUTS.values()]

    def actuator_forward(self, enabled):
        return self.actuator_direction("forward" if enabled else "off")

    def actuator_reverse(self, enabled):
        return self.actuator_direction("reverse" if enabled else "off")

    def actuator_direction(self, direction):
        direction = str(direction).strip().lower()
        if direction == "off":
            return ["OUT 3 0", "OUT 4 0"]
        if direction == "forward":
            # De-energize both directions before selecting one. Firmware and
            # hardware must enforce the same mutual exclusion independently.
            return ["OUT 3 0", "OUT 4 0", "OUT 3 1"]
        if direction == "reverse":
            return ["OUT 3 0", "OUT 4 0", "OUT 4 1"]
        return []

    def motor_power(self, enabled):
        return [f"EN {1 if enabled else 0}"]

    def stop_motion(self):
        return ["OFF"]


class TeensyGrblHalBackend(ControllerBackend):
    key = TEENSY_GRBLHAL
    label = "Teensy grblHAL"
    capabilities = ControllerCapabilities(
        homing_commands=True,
        motion_commands=True,
        # Prototype commands exist, but the UI remains locked until grblHAL
        # acknowledgements, alarms, and status reports are parsed.
        manual_motion_ready=False,
        automatic_cycle_ready=False,
    )

    def startup_commands(self):
        return ["$I", "$$", "$G", "?"]

    def home(self):
        return ["$H", "?"]

    def move_absolute_inches(self, target_inches):
        return ["G20 G90", f"G1 X{target_inches:.4f}", "?"]

    def stop_motion(self):
        return ["!"]

    def saw_actuate(self):
        return []


def create_controller_backend(mode_key):
    if mode_key == TEENSY_HARDWARE_TEST:
        return TeensyHardwareTestBackend()
    if mode_key == TEENSY_GRBLHAL:
        return TeensyGrblHalBackend()
    return LegacyMegaBackend()
