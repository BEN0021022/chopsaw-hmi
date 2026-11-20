"""Main HMI + Teensy contract tests; all serial writes are in-memory."""
import os
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QSettings as RealQSettings
from PyQt6.QtWidgets import QApplication
import main
from controller_backends import TEENSY_CARRIAGE, create_controller_backend
from teensy_carriage import IDENTITY


class FakeSerial:
    def __init__(self):
        self.is_open = True
        self.writes = []

    def write(self, data):
        self.writes.append(data.decode().strip())
        return len(data)

    def close(self):
        self.is_open = False


def packet(panel, **changes):
    fields = dict(ARMED=0, CONFIGURED=0, READY=0, HOME_VERIFIED=0, HOME_RAW=1,
                  ALARM_RAW=1, STEP=0, DIR=0, ENA=1, MAX_JOG=254, RATE_PPS=40, JOG_READY=0, REMAINING=0,
                  POS_STEPS=0, MOVE_ID=0, UP_MS=1000, CAL_SPI="127.12", FAULT="NONE",
                  POS_KNOWN=0, HOME_OFFSET=0, HOME_REF="160.5", HOME_STATE="IDLE", HOME_ERROR="NONE",
                  SOFT_MIN_OFFSET=-20402, SOFT_MAX_OFFSET=-14, SOFT_MAX_MILLI=160389,
                  MAX_MOVE=20594, TARGET_OFFSET=0, MOVE_KIND="IDLE", PROFILE_ID=0, ACCEL_PPS2=0,
                  EDGE_STATE="IDLE", EDGE_ERROR="NONE", EDGE_VALID=0, EDGE_MILLI=0,
                  TRUING_MILLI=0, SENSOR_OFFSET_MILLI=10800, TRIM_MILLI=250,
                  JOG_PULSES=0,JOG_TIME_US=0,JOG_PEAK_PPS=0,JOG_LATE_US=0,
                  PROFILE_RATE0=40,PROFILE_ACCEL0=0,PROFILE_RATE1=150,PROFILE_ACCEL1=200,
                  PROFILE_RATE2=1000,PROFILE_ACCEL2=500,PROFILE_RATE3=2500,PROFILE_ACCEL3=1500)
    fields.update(changes)
    if fields["ARMED"] == 1 and "JOG_READY" not in changes:
        fields["JOG_READY"] = 1
    panel.handle_line("BENCH_X," + ",".join(f"{k}:{v}" for k, v in fields.items()))


def ready(panel):
    panel.session(True)
    panel.handle_line("BENCH_HELLO," + ",".join(f"{k}:{v}" for k, v in IDENTITY.items()))
    panel.handle_line("BENCH_SAFETY,READY:1,RESET_READY:1,DOOR_CLOSED:1,SAW_POSITION:UP,FAULT:NONE,BLOCKER:NONE")
    panel.handle_line("BENCH_INPUTS,HOME:1,BOARD_EDGE:0,FENCE_DOOR:0,SAW_UP:0,SAW_DOWN:1,CL57T_ALM:1")
    packet(panel)  # manual setup must work without ever tripping Home


def run():
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as folder:
        main.QSettings = lambda *a, **k: RealQSettings(os.path.join(folder, "settings.ini"), RealQSettings.Format.IniFormat)
        main.updater.check_for_update = lambda *a, **k: None
        w = main.MinimalHMI()
        w.controller_combo.setCurrentIndex(w.controller_combo.findData(TEENSY_CARRIAGE))
        w.ser = FakeSerial()
        wire = w.ser
        w.set_controls_enabled(True)
        p = w.carriage_tab
        assert p.connected
        assert w.legacy_tab.isEnabled() and w.auto_tab.isEnabled() and w.full_auto_tab.isEnabled()
        assert w.full_auto_legacy.isEnabled() and not w.fa_start_cycle_button.isEnabled(), 'Readable view cannot bypass readiness'
        assert not w.start_cycle_button.isEnabled() and not hasattr(w,'cut_complete_button')
        assert w.enable_chk.isHidden() and not w.enable_chk.isEnabled()
        assert not w.manual_home_button.isEnabled()
        for retired in ('pid_chk','near_cal_btn','target_input','manual_go','rel_input',
                        'manual_jog','calibrate_input','manual_motor_params','max_speed','acceleration'):
            assert not hasattr(w,retired), retired
        assert not w.active_controller().capabilities.automatic_cycle_ready
        assert not w.active_controller().capabilities.manual_motion_ready
        assert w.active_controller().capabilities.carriage_jog_ready
        assert create_controller_backend(TEENSY_CARRIAGE).startup_commands() == ["HELLO", "PINMAP", "STATUS"]
        assert not wire.writes, "Connecting must not enable/arm or move"
        for cmd in ("S12.5", "V1", "C1", "OUT 0 1", "ARM 1", "XLEVEL 1 0", "G1 X1", "XARM 1", "OFF\nXARM 1"):
            assert not w.send_command(cmd), cmd
        ready(p)
        assert p.sensor_labels["FENCE_DOOR"].text() == "ACTIVE"
        assert p.sensor_labels["CL57T_ALM"].text() == "NORMAL"
        assert p.sensor_labels["BOARD_EDGE"].text() == "ACTIVE"
        assert not p.configure_button.isEnabled()
        p.consent.setChecked(True)
        assert p.configure_button.isEnabled()
        assert p.x["HOME_VERIFIED"] == "0", "A fresh restart must not require a Home trip"
        packet(p, HOME_RAW=0)
        assert p.configure_button.isEnabled(), "Home setup must also work when already on its sensor"
        packet(p, HOME_RAW=1)
        assert p.configure_button.isEnabled()
        p.configure_button.click()
        assert wire.writes[-1] == "XCONFIG 0 1"
        assert not p.arm_button.isEnabled(), "Wait for configuration ACK"
        packet(p, CONFIGURED=1, READY=1, HOME_VERIFIED=1)
        p.arm_button.click()
        assert wire.writes[-1] == "XARM 1"
        assert not p.toward_saw.isEnabled(), "Wait for arm ACK"
        packet(p, ARMED=1, CONFIGURED=1, HOME_VERIFIED=1, ENA=0)
        packet(p, ARMED=1, CONFIGURED=1, HOME_VERIFIED=1, ENA=0, JOG_READY=0)
        assert not p.toward_saw.isEnabled(), "Wait for enable settling in firmware"
        packet(p, ARMED=1, CONFIGURED=1, HOME_VERIFIED=1, ENA=0, JOG_READY=1)
        assert p.toward_saw.isEnabled() and not p.toward_saw.autoRepeat()
        p.toward_saw.click()
        assert wire.writes[-1] == "XJOG -1 13"
        before = len(wire.writes)
        p.jog(1)
        assert len(wire.writes) == before, "No duplicate while awaiting ACK"
        packet(p, ARMED=1, CONFIGURED=1, HOME_VERIFIED=1, ENA=0)
        assert p.pending is not None, "Old telemetry must not acknowledge a new move"
        packet(p, ARMED=1, CONFIGURED=1, HOME_VERIFIED=1, ENA=0, REMAINING=9, POS_STEPS=-4, MOVE_ID=1)
        assert p.pending is None and not p.toward_home.isEnabled() and not p.distance.isEnabled()
        p.tick()
        assert wire.writes[-1] == "KEEPALIVE"
        packet(p, ARMED=1, CONFIGURED=1, HOME_VERIFIED=1, ENA=0, POS_STEPS=-13, MOVE_ID=1)
        assert "-0.1023" in p.position.text()
        assert w.homed_label.text() == "NOT HOMED", "Pulse count is not an absolute or encoder position"
        for distance, count in ((0.25, 32), (0.5, 64), (1, 127), (2, 254)):
            packet(p, ARMED=1, CONFIGURED=1, HOME_VERIFIED=1, ENA=0, MOVE_ID=count)
            p.distance.setValue(distance)
            p.toward_home.click()
            assert wire.writes[-1] == f"XJOG 1 {count}"
            packet(p, ARMED=1, CONFIGURED=1, HOME_VERIFIED=1, ENA=0, MOVE_ID=count+1)
        packet(p, ARMED=1, CONFIGURED=1, HOME_VERIFIED=1, ENA=0)
        assert p.toward_saw.isEnabled(), "Completed jogs do not exhaust a session allowance"
        for move in range(20):
            packet(p, ARMED=1, CONFIGURED=1, HOME_VERIFIED=1, ENA=0,
                   POS_STEPS=move*254, MOVE_ID=move+100)
            p.distance.setValue(2)
            p.toward_home.click()
            assert wire.writes[-1] == "XJOG 1 254"
            packet(p, ARMED=1, CONFIGURED=1, HOME_VERIFIED=1, ENA=0,
                   POS_STEPS=(move+1)*254, MOVE_ID=move+101)
        assert "session travel budget" not in p.progress.text()
        assert not w.send_command("XJOG 1 255") and not w.send_command("XJOG 1 1 EXTRA")

        packet(p, ARMED=1, CONFIGURED=1, HOME_VERIFIED=1, ENA=0)
        p.stop()
        assert p.stopping and not p.allowed("XJOG 1 13"), "Wait for stop ACK"
        packet(p, ARMED=0, CONFIGURED=1, HOME_VERIFIED=1, ENA=0)
        assert not p.stopping
        packet(p, ARMED=1, CONFIGURED=1, HOME_VERIFIED=1, ENA=0)
        # Stale safety alone must stop, even with fresh motion telemetry.
        p.received["SAFETY"] -= 3
        p.tick()
        assert wire.writes[-1] == "OFF" and p.local_fault and not p.consent.isChecked()
        p.handle_line("BENCH_SAFETY,READY:1,DOOR_CLOSED:1,SAW_POSITION:UP,FAULT:NONE")
        assert not p.toward_home.isEnabled(), "Late telemetry must not rearm"
        packet(p, UP_MS=2000)
        p.acknowledge()
        assert wire.writes[-1] == "RESET" and not p.consent.isChecked()
        ready(p)
        p.consent.setChecked(True)
        packet(p, ARMED=1, CONFIGURED=1, HOME_VERIFIED=1, ENA=0, UP_MS=3000)
        packet(p, UP_MS=100)
        assert "restarted" in p.local_fault and not p.consent.isChecked()

        # Homing: explicit bounded command, sensor expected active in-cycle,
        # no jog overlap, completion is disarmed and only then referenced.
        ready(p)
        p.consent.setChecked(True)
        packet(p, CONFIGURED=1, READY=1, HOME_RAW=0)
        assert p.home_button.isEnabled() and not p.arm_button.isEnabled()
        p.home_button.click()
        assert wire.writes[-1] == "XHOME 254" and p.pending is not None
        packet(p, ARMED=1, CONFIGURED=1, HOME_RAW=0, HOME_STATE="RELEASE", MOVE_ID=1, JOG_READY=0)
        assert p.homing and not p.toward_home.isEnabled() and not p.home_button.isEnabled()
        assert not p.home_search.isEnabled() and p.pending is None
        p.tick()
        assert wire.writes[-1] == "KEEPALIVE", "Expected Home assertion must not trip the PC watchdog"
        assert "HOMING: RELEASE" in p.status.text()
        packet(p, CONFIGURED=1, READY=1, HOME_STATE="DONE", MOVE_ID=1,
               POS_KNOWN=1, HOME_OFFSET=-14)
        assert "HOMED" in p.machine_position.text()
        assert w.homed_label.text() == "HOMED"
        assert abs(w.current_position - (160.5-14/127.12)) < 1e-8
        assert not p.armed and wire.writes[-1] == "KEEPALIVE", "Completion must not auto-arm or jog"
        packet(p, CONFIGURED=1, FAULT="DRIVER_ALARM", POS_KNOWN=0, HOME_STATE="DONE")
        assert "UNKNOWN" in p.machine_position.text() and w.homed_label.text() == "NOT HOMED"
        ready(p)
        p.consent.setChecked(True)
        packet(p, CONFIGURED=1, READY=1)
        p.home_search.setValue(162)
        p.home_button.click()
        assert wire.writes[-1] == "XHOME 20593"
        assert not w.send_command("XHOME 20595")
        packet(p, ARMED=1, CONFIGURED=1, HOME_STATE="SEEK", MOVE_ID=1, JOG_READY=0)
        p.stop()
        assert wire.writes[-1] == "OFF" and not p.allowed("XHOME 254")
        packet(p, HOME_STATE="CANCELLED")
        assert "UNKNOWN" in p.machine_position.text() and not p.armed

        # Absolute moves and load presets require a valid Home reference.
        ready(p)
        p.consent.setChecked(True)
        packet(p, CONFIGURED=1, READY=1)
        assert not p.go_button.isEnabled() and not p.load_button.isEnabled()
        assert not p.move_to(135)
        packet(p, CONFIGURED=1, READY=1, POS_KNOWN=1, HOME_OFFSET=-14, HOME_STATE="DONE")
        assert p.target.value() == 160.389, "New reference should default to current position, not zero"
        assert not p.go_button.isEnabled(), "Still needs explicit motion ARM"
        packet(p, ARMED=1, CONFIGURED=1, POS_KNOWN=1, HOME_OFFSET=-14, HOME_STATE="DONE")
        assert not p.toward_home.isEnabled(), "Homed jogs cannot exceed the pull-off limit"
        before_position = w.current_position
        assert p.move_to(159.39)
        assert wire.writes[-1] == "XMOVE 159390"
        assert w.current_position == before_position, "Do not predict an absolute completion"
        packet(p, ARMED=1, CONFIGURED=1, POS_KNOWN=1, HOME_OFFSET=-20, HOME_STATE="DONE",
               MOVE_KIND="ABSOLUTE", REMAINING=121, MOVE_ID=1, TARGET_OFFSET=-141)
        assert p.local_fault == "" and not p.go_button.isEnabled() and not p.home_button.isEnabled()
        packet(p, ARMED=1, CONFIGURED=1, POS_KNOWN=1, HOME_OFFSET=-141, HOME_STATE="DONE", MOVE_ID=1)
        assert abs(w.current_position - (160.5-141/127.12)) < 1e-8
        for index, target in ((1,135000),(2,111000),(3,87000),(4,63000),(0,160389)):
            p.load_preset.setCurrentIndex(index)
            p.load_button.click()
            assert wire.writes[-1] == f"XLOAD {target}"
            packet(p, ARMED=1, CONFIGURED=1, POS_KNOWN=1, HOME_OFFSET=-141,
                   HOME_STATE="DONE", MOVE_ID=index+10)
        assert not p.move_to(160.5) and not p.move_to(float("nan")) and not p.move_to(-1)
        assert not w.send_command("XMOVE 160500") and not w.send_command("XMOVE 1 EXTRA")
        assert p.move_to(135)  # Low-level protocol; direct-gesture path has its own actual-sketch test.
        assert wire.writes[-1] == "XMOVE 135000"
        packet(p, ARMED=1, CONFIGURED=1, POS_KNOWN=1, HOME_OFFSET=-200, HOME_STATE="DONE",
               MOVE_KIND="ABSOLUTE", REMAINING=10000, MOVE_ID=30, TARGET_OFFSET=-12394)
        assert not p.local_fault, "Long absolute moves are allowed beyond the two-inch jog cap"
        p.stop()
        packet(p, CONFIGURED=1, READY=1, POS_KNOWN=1, HOME_OFFSET=-200, HOME_STATE="DONE")
        assert not p.armed and not p.go_button.isEnabled()
        packet(p, FAULT="DRIVER_ALARM", POS_KNOWN=0)
        assert not p.move_to(135) and not p.go_button.isEnabled()
        assert "Stage 4" in w.migration_checklist.toPlainText()

        ready(p)
        p.consent.setChecked(True)
        assert p.select_profile(2)
        assert wire.writes[-1] == "XPROFILE 2"
        assert p.x["PROFILE_ID"] == "0", "Wait for actual controller profile ACK"
        packet(p, PROFILE_ID=2, RATE_PPS=1000, ACCEL_PPS2=500)
        assert "1000 pulses/s" in p.profile_label.text()
        assert w.active_profile_name == "NORMAL"
        assert w.switch_profile("GENTLE") and wire.writes[-1] == "XPROFILE 1"
        assert w.active_profile_name == "NORMAL", "Legacy buttons also wait for controller ACK"
        assert create_controller_backend(TEENSY_CARRIAGE).profile_select(2) == ["XPROFILE 3"]
        packet(p, PROFILE_ID=1, RATE_PPS=150, ACCEL_PPS2=200)
        assert w.active_profile_name == "GENTLE" and p.profile_pending is None
        packet(p, ARMED=1, PROFILE_ID=2, RATE_PPS=1000, ACCEL_PPS2=500)
        assert not p.select_profile(3) and not p.profile_apply.isEnabled()
        packet(p, ARMED=0, PROFILE_ID=2, RATE_PPS=40, ACCEL_PPS2=160)
        assert p.local_fault, "Inconsistent profile limits must fail closed"

        # Editable rate/acceleration: explicit apply, controller store/readback,
        # no silent reuse of MEGA's persisted maximum-valued UI settings.
        ready(p); p.consent.setChecked(True)
        p.profile_combo.setCurrentIndex(p.profile_combo.findData(3))
        assert p.rate_input.value() == 2500 and p.accel_input.value() == 1500
        p.rate_input.setValue(1700); p.accel_input.setValue(2200)
        assert p.x['RATE_PPS'] == '40'
        p.profile_apply.click()
        assert wire.writes[-1] == 'XPROFILE 3 1700 2200' and p.profile_pending
        assert not p.allowed('XARM 1') and not p.profile_apply.isEnabled()
        packet(p)
        assert p.profile_pending, 'Old telemetry cannot acknowledge new parameters'
        packet(p,PROFILE_ID=3,RATE_PPS=1700,ACCEL_PPS2=2200,PROFILE_RATE3=1700,PROFILE_ACCEL3=2200)
        assert p.profile_pending is None and w.active_profile_name == 'FAST'
        assert p.rate_input.value() == 1700 and '13.37 in/s max' in p.profile_label.text()
        packet(p,ARMED=1,PROFILE_ID=3,RATE_PPS=1700,ACCEL_PPS2=2200,PROFILE_RATE3=1700,PROFILE_ACCEL3=2200,
               JOG_PULSES=127,JOG_PEAK_PPS=650,JOG_TIME_US=500000,JOG_LATE_US=18)
        assert not p.rate_input.isEnabled() and not p.accel_input.isEnabled()
        assert '650 pulses/s' in p.pulse_timing.text()
        assert not p.allowed('XPROFILE 3 20001 1000') and not p.allowed('XPROFILE 3 1000 50001')
        ready(p); p.consent.setChecked(True)
        assert not p.allowed('XPROFILE 0 1000 1000') and not p.allowed('XPROFILE 3 1000 0')
        assert p.select_profile(3)
        p.profile_pending = (*p.profile_pending[:3],time.monotonic()-2)
        p.tick()
        assert p.local_fault == 'Profile acknowledgment timed out'

        # Edge search uses the referenced position and clear sensor, then stops.
        # A fresh controller-owned capture is required for the separate truing move.
        ready(p)
        p.consent.setChecked(True)
        packet(p, ARMED=1, CONFIGURED=1, POS_KNOWN=1, HOME_OFFSET=-14, HOME_STATE="DONE")
        assert not p.find_edge(), "Cannot start searching when the sensor is already active"
        p.handle_line("BENCH_INPUTS,HOME:1,BOARD_EDGE:1,FENCE_DOOR:0,SAW_UP:0,SAW_DOWN:1,CL57T_ALM:1")
        assert p.find_edge() and wire.writes[-1] == "XEDGE 254 10800 250"
        assert not p.move_to(135) and not p.find_edge(), "No overlapping commands before ACK"
        packet(p, ARMED=1, CONFIGURED=1, POS_KNOWN=1, HOME_OFFSET=-20, HOME_STATE="DONE",
               MOVE_KIND="EDGE", REMAINING=248, MOVE_ID=1, EDGE_STATE="SEEK")
        assert p.edge_searching and "FINDING BOARD EDGE" in p.status.text()
        assert not p.toward_saw.isEnabled() and not p.edge_button.isEnabled()
        assert not p.sensor_offset.isEnabled() and not p.edge_search.isEnabled()
        p.tick()
        assert wire.writes[-1] == "KEEPALIVE"
        edge_fields = dict(CONFIGURED=1, POS_KNOWN=1, HOME_OFFSET=-27, HOME_STATE="DONE",
                           MOVE_ID=1, EDGE_STATE="FOUND", EDGE_VALID=1, EDGE_MILLI=160287,
                           TRUING_MILLI=149237)
        packet(p, **edge_fields)
        assert not p.armed and p.pending is None
        assert "149.237" in p.edge_result.text() and not p.truing_button.isEnabled()
        assert not p.move_to_truing(), "Detection must not arm or advance automatically"
        packet(p, ARMED=1, **edge_fields)
        assert p.truing_button.isEnabled()
        assert not w.send_command("XTRUING 0"), "Capture token must match the last acquisition"
        assert p.move_to_truing() and wire.writes[-1] == "XTRUING 1"
        packet(p, ARMED=1, CONFIGURED=1, POS_KNOWN=1, HOME_OFFSET=-30, HOME_STATE="DONE",
               REMAINING=1300, MOVE_KIND="ABSOLUTE", TARGET_OFFSET=-1432, MOVE_ID=2)
        assert not p.truing_button.isEnabled() and "No valid" in p.edge_result.text()
        p.stop()
        packet(p, CONFIGURED=1, POS_KNOWN=1, HOME_OFFSET=-30, HOME_STATE="DONE")
        assert not p.allowed("XEDGE 20595 10800 250") and not p.allowed("XEDGE 13 160501 250")
        assert not p.allowed("XEDGE 13 10800 -1") and not p.allowed("XTRUING 1 EXTRA")
        ready(p); p.consent.setChecked(True)
        packet(p, **dict(edge_fields,TRUING_MILLI=149238))
        assert p.local_fault == "Invalid board-edge telemetry"

        # Manual shows Home only; one Home gesture performs setup and full search.
        ready(p)
        w.tabs.setCurrentWidget(w.legacy_tab)
        assert w.position_label.text() == 'UNKNOWN'
        assert w.keypad.display.isReadOnly() is False
        assert w.manual_teensy_setup.isHidden() and w.manual_teensy_actions.isHidden() and w.enable_chk.isHidden()
        # Home and keypad now prepare their controller mode automatically.
        # That acknowledged multi-step flow is exercised in test_direct_controls.
        p.home_search.setValue(2)
        assert w.manual_home_search.value() == 2

        # Old hidden enable-checkbox gestures are retired. Direct mode handoff,
        # Home, Enter, Stop and actuator exclusion use the actual-sketch harness.

        # Settings use controller RAM, preserve unsent drafts and wait for ACK.
        ready(p); p.consent.setChecked(True)
        assert w.norm_speed.value() == 2500 and w.gentle_speed.value() == 600,(w.norm_speed.value(),w.gentle_speed.value(),w.saved_motion_profiles(),w._teensy_settings_dirty)
        w.tabs.setCurrentWidget(w.speed_tab)
        w.settings_profile_combo.setCurrentIndex(w.settings_profile_combo.findData('FAST'))
        before=len(wire.writes)
        w.fast_speed.setValue(3500); w.fast_accel.setValue(1500)
        assert len(wire.writes)==before and 'UNAPPLIED' in w.settings_profile_feedback.text()
        packet(p)
        assert w.fast_speed.value()==3500, 'Periodic old telemetry cannot erase an unapplied draft'
        w.apply_profile_btn.click()
        assert wire.writes[-1]=='XPROFILE 3 3500 1500' and p.profile_pending
        assert not w.apply_profile_btn.isEnabled() and not w.fast_speed.isEnabled()
        assert not w.manual_home_button.isEnabled()
        assert w.active_profile_name=='COMMISSIONING', 'No optimistic profile application'
        packet(p,PROFILE_ID=3,RATE_PPS=3500,ACCEL_PPS2=1500,PROFILE_RATE3=3500,PROFILE_ACCEL3=1500)
        assert p.profile_pending is None and w.active_profile_name=='FAST'
        assert p.rate_input.value()==3500 and not w._teensy_settings_dirty
        assert '3500 pulses/s' in w.settings_profile_feedback.text()
        p.profile_combo.setCurrentIndex(p.profile_combo.findData(2))
        p.rate_input.setValue(1800); p.accel_input.setValue(900); p.profile_apply.click()
        assert wire.writes[-1]=='XPROFILE 2 1800 900'
        packet(p,PROFILE_ID=2,RATE_PPS=1800,ACCEL_PPS2=900,PROFILE_RATE2=1800,PROFILE_ACCEL2=900,
               PROFILE_RATE3=3500,PROFILE_ACCEL3=1500)
        assert w.norm_speed.value()==1800 and w.norm_accel.value()==900
        assert w.settings_profile_combo.currentData()=='NORMAL'
        packet(p,ARMED=1,CONFIGURED=1,PROFILE_ID=2,RATE_PPS=1800,ACCEL_PPS2=900,
               PROFILE_RATE2=1800,PROFILE_ACCEL2=900)
        assert not w.norm_speed.isEnabled() and not w.apply_profile_btn.isEnabled()
        assert not w.home_motor(), 'Manual handler cannot bypass disarmed homing requirement'
        p.received['X']-=3; p.refresh()
        assert not w.manual_home_button.isEnabled() and not w.apply_profile_btn.isEnabled()
        assert w.homed_label.text()=='NOT HOMED'
        assert not w.apply_current_profile_params(), 'Settings cannot bypass stale feedback'
        ready(p)
        w.settings.setValue('fast_speed',4321)
        w._save_settings()
        assert int(w.settings.value('fast_speed'))==4321, 'Do not overwrite archived simulator profile settings'
        assert w.auto_tab.isEnabled() and not w.start_cycle_button.isEnabled() and w.full_auto_tab.isEnabled()
        assert w.full_auto_legacy.isEnabled() and not w.fa_start_cycle_button.isEnabled()

        # AUTO exposes planning and guarded carriage controls, never a cycle.
        from PyQt6.QtWidgets import QPushButton
        ready(p); w.tabs.setCurrentWidget(w.auto_tab)
        assert w.auto_tab.isEnabled() and not w.start_cycle_button.isEnabled()
        assert not any(button.text()=='CUT COMPLETE' for button in w.findChildren(QPushButton))
        assert not w.resume_on_reset_button.isEnabled() and w.resume_on_reset_button.isHidden()
        assert w.current_group.isHidden() and w.auto_clamp_status_label.text()=='UNKNOWN'
        assert w.auto_homing_sensor_label.text()=='OFF' and w.auto_board_sensor_label.text()=='ON'
        assert w.auto_sensor_pills['FENCE_DOOR'].text()=='CLOSED'
        assert w.auto_sensor_pills['SAW_UP'].text()=='ACTIVE'
        assert w.auto_sensor_pills['CL57T_ALM'].text()=='NORMAL'
        before=len(wire.writes)
        w.start_auto_cycle(); w.resume_after_reset(); w.advance_auto_cycle(); w.cut_complete_pressed()
        assert len(wire.writes)==before and not w.start_cycle_button.isEnabled()
        w.clear_list_button.click()
        w.cut_length_input.setValue(18); w.add_cut_button.click()
        assert w.cut_list==[(1,18,'')] and len(wire.writes)==before
        w.cut_list_display.setPlainText('12 A\n24 B')
        w.update_from_box_button.click()
        assert [cut[1] for cut in w.cut_list]==[12,24] and len(wire.writes)==before
        # Imports preserve the list's own tab route; switching to AUTO never arms.
        w.load_cut_list_lines(['18 A','24 B','30 C'])
        assert len(w.cut_list)==3 and len(wire.writes)==before
        # Only partial carriage telemetry is provided here: the new action
        # broker requires pneumatic feedback too and must not infer readiness.
        assert w.auto_teensy_setup.isHidden()
        assert not w.qjog_left_01.isEnabled() and not w.load_button.isEnabled()
        assert not w.auto_jog(3) and not w.load_position()
        packet(p,CONFIGURED=1,POS_KNOWN=1,HOME_OFFSET=-200,HOME_STATE='DONE')
        for index,target in ((0,160.389),(1,135),(2,111),(3,87),(4,63)):
            w.board_size_radios[index][0].setChecked(True)
            assert abs(w.native_load_target()-target)<.001
        w.current_cut_index=1
        w.cancel_cycle_button.click(); assert wire.writes[-1]=='OFF' and w.current_cut_index==1
        packet(p,CONFIGURED=1,POS_KNOWN=1,HOME_OFFSET=-200,HOME_STATE='DONE')
        assert not w.load_button.isEnabled() and not w.qjog_left_01.isEnabled()
        p.handle_line('BENCH_INPUTS,HOME:0,BOARD_EDGE:1,FENCE_DOOR:1,SAW_UP:1,SAW_DOWN:0,CL57T_ALM:0')
        assert w.auto_homing_sensor_label.text()=='ON' and w.auto_board_sensor_label.text()=='OFF'
        assert w.auto_sensor_pills['FENCE_DOOR'].text()=='OPEN'
        assert w.auto_sensor_pills['SAW_DOWN'].text()=='ACTIVE'
        assert w.auto_sensor_pills['CL57T_ALM'].text()=='ALARM'
        p.received['INPUTS']-=3; p.refresh()
        assert w.auto_board_sensor_label.text()=='UNKNOWN'
        assert all(label.text()=='UNKNOWN' for label in w.auto_sensor_pills.values())
        p.session(False)
        before=len(wire.writes); w.add_cut_button.click()
        assert len(wire.writes)==before and w.auto_tab.isEnabled(), 'Disconnected cut-list planning stays available'

        # Invalid packets and missing move ACKs fail closed.
        ready(p)
        p.handle_line("BENCH_X,ARMED:1")
        assert p.local_fault and wire.writes[-1] == "OFF"
        ready(p)
        p.consent.setChecked(True)
        packet(p, ARMED=1, CONFIGURED=1, HOME_VERIFIED=1, ENA=0)
        p.pending = (0, time.monotonic()-2)
        p.tick()
        assert p.local_fault == "Move acknowledgment timed out" and wire.writes[-1] == "OFF"
        ready(p)
        p.consent.setChecked(True)
        wrong = dict(IDENTITY, X_MAP="STEP2_DIR3_EN10")
        p.handle_line("BENCH_HELLO," + ",".join(f"{k}:{v}" for k,v in wrong.items()))
        assert not p.compatible and wire.writes[-1] == "OFF"
        ready(p)
        p.release_button.click()
        assert wire.writes[-1] == "XDISABLE"
        p.received["INPUTS"] -= 3
        p.refresh()
        assert p.sensor_labels["HOME"].text() == "UNKNOWN"
        # The real main serial message handler routes Teensy telemetry to this tab.
        w.update_message_log("BENCH_INPUTS,HOME:0,BOARD_EDGE:1,FENCE_DOOR:0,SAW_UP:0,SAW_DOWN:1,CL57T_ALM:1")
        assert p.sensor_labels["HOME"].text() == "ACTIVE"
        w._stop_listener()
        assert wire.writes[-1] == "OFF" and not wire.is_open and not p.connected
        w.update_message_log("BENCH_HELLO," + ",".join(f"{k}:{v}" for k,v in IDENTITY.items()))
        assert not p.compatible, "Disconnected/old-session telemetry must be ignored"
        w.close()
        app.processEvents()
    print("Teensy main-app carriage integration tests passed")


if __name__ == "__main__":
    run()
