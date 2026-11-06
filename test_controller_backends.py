"""Command-contract tests for every controller backend (no hardware required)."""

from controller_backends import (
    CONTROLLER_MODES,
    LEGACY_MEGA,
    TEENSY_GRBLHAL,
    TEENSY_HARDWARE_TEST,
    create_controller_backend,
)


def test_legacy_mega_is_archived_not_selectable():
    assert LEGACY_MEGA not in {mode.key for mode in CONTROLLER_MODES}
    backend = create_controller_backend(LEGACY_MEGA)
    # The implementation remains only to support the offline simulator and the
    # archived baseline; the live Teensy UI cannot select it.
    assert backend.capabilities.manual_motion_ready
    assert backend.capabilities.automatic_cycle_ready
    assert backend.capabilities.automatic_cutting_ready
    assert backend.move_absolute_inches(12.5) == ["S12.5000"]
    assert backend.clamp_extend(2) == ["C2"]
    assert backend.saw_actuate() == ["V1"]
    assert backend.truing_cycle(10.8) == ["J10.8000"]


def test_teensy_test_contract_is_diagnostics_only():
    backend = create_controller_backend(TEENSY_HARDWARE_TEST)
    assert not backend.capabilities.manual_motion_ready
    assert not backend.capabilities.automatic_cycle_ready
    assert not backend.capabilities.clamps
    assert not backend.capabilities.actuator
    assert backend.startup_commands() == ["PINMAP", "I2C", "STATUS"]
    assert backend.clamp_extend(1) == []
    assert backend.clamp_retract(1) == []
    assert backend.actuator_direction("forward") == []
    assert backend.actuator_direction("invalid") == []


def test_grblhal_is_motion_prototype_only():
    backend = create_controller_backend(TEENSY_GRBLHAL)
    assert backend.capabilities.homing_commands
    assert backend.capabilities.motion_commands
    assert not backend.capabilities.manual_motion_ready
    assert not backend.capabilities.automatic_cycle_ready
    assert backend.home() == ["$H", "?"]
    assert backend.move_absolute_inches(12.5) == ["G20 G90", "G1 X12.5000", "?"]
    assert backend.clamp_extend(1) == []
    assert backend.saw_actuate() == []


def main():
    tests = [
        test_legacy_mega_is_archived_not_selectable,
        test_teensy_test_contract_is_diagnostics_only,
        test_grblhal_is_motion_prototype_only,
    ]
    for test in tests:
        test()
        print(f"{test.__name__} OK")
    print(f"{len(tests)}/{len(tests)} backend contract tests passed")


if __name__ == "__main__":
    main()
