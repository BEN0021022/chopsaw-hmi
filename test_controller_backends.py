"""Command-contract tests for active controller backends (no hardware required)."""

from controller_backends import (
    CONTROLLER_MODES,
    LEGACY_MEGA,
    TEENSY_CARRIAGE,
    create_controller_backend,
)


def test_legacy_mega_is_simulator_only_not_selectable():
    assert LEGACY_MEGA not in {mode.key for mode in CONTROLLER_MODES}
    assert [mode.key for mode in CONTROLLER_MODES] == [TEENSY_CARRIAGE]
    backend = create_controller_backend(LEGACY_MEGA)
    # Retained solely for the offline VirtualController simulator.
    assert backend.capabilities.manual_motion_ready
    assert backend.capabilities.automatic_cycle_ready
    assert backend.capabilities.automatic_cutting_ready
    assert backend.move_absolute_inches(12.5) == ["S12.5000"]
    assert backend.clamp_extend(2) == ["C2"]
    assert backend.saw_actuate() == ["V1"]
    assert backend.truing_cycle(10.8) == ["J10.8000"]


def test_carriage_contract_has_no_legacy_or_automatic_fallback():
    backend = create_controller_backend(TEENSY_CARRIAGE)
    assert create_controller_backend("unknown_mode").key == TEENSY_CARRIAGE
    assert backend.capabilities.carriage_jog_ready
    assert not backend.capabilities.manual_motion_ready
    assert not backend.capabilities.automatic_cycle_ready
    assert backend.startup_commands() == ["HELLO", "PINMAP", "STATUS"]
    assert backend.stop_motion() == ["OFF"]
    assert backend.capabilities.homing_commands
    assert backend.home() == ["XHOME 254"]
    assert backend.move_absolute_inches(10) == ["XMOVE 10000"]
    assert backend.move_absolute_inches(float("nan")) == []
    assert backend.move_absolute_inches(-1) == []
    assert backend.clamp_extend(1) == backend.saw_actuate() == []
    assert backend.pid_control(True) == backend.current_monitoring(True) == []


def main():
    tests = [
        test_legacy_mega_is_simulator_only_not_selectable,
        test_carriage_contract_has_no_legacy_or_automatic_fallback,
    ]
    for test in tests:
        test()
        print(f"{test.__name__} OK")
    print(f"{len(tests)}/{len(tests)} backend contract tests passed")


if __name__ == "__main__":
    main()
