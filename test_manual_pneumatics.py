"""Manual actuator preview, isolation, cancellation and native write boundaries."""
import os
import tempfile
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication
import main
from controller_backends import TEENSY_CARRIAGE
from test_teensy_carriage import FakeSerial, ready


def run():
    app = QApplication.instance() or QApplication([])
    def pump(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents(); time.sleep(.004)
    def until(condition, timeout=5):
        end = time.monotonic()+timeout
        while time.monotonic() < end:
            app.processEvents(); time.sleep(.004)
            if condition(): return
        raise AssertionError('Manual actuator phase did not complete')

    with tempfile.TemporaryDirectory() as folder:
        main.QSettings = lambda *a, **k: QSettings(folder+'/settings.ini', QSettings.Format.IniFormat)
        main.updater.check_for_update = lambda *a, **k: None
        w = main.MinimalHMI()
        w.show(); w.tabs.setCurrentWidget(w.legacy_tab)
        panel = w.manual_pneumatics
        # Even valid native carriage telemetry must not expose one-at-a-time raw
        # bench OUT/ARM commands as combined manual cutting.
        w.controller_combo.setCurrentIndex(w.controller_combo.findData(TEENSY_CARRIAGE))
        w.ser = FakeSerial(); wire = w.ser; w.set_controls_enabled(True)
        ready(w.carriage_tab); w.carriage_tab.consent.setChecked(True)
        panel.refresh()
        writes = list(wire.writes)
        for action in ('engage','release','lower','up','press','unpress','cycle'):
            assert not panel.request(action)
        assert not panel.stop() and not panel.cycle_button.isEnabled()
        assert all(not button.isEnabled() for button in panel.buttons.values())
        assert wire.writes == writes
        w._stop_listener(); w.set_controls_enabled(False)

        w.port_combo.setCurrentIndex(w.port_combo.findData('SIM')); w.toggle_connection()
        w.tabs.setCurrentWidget(w.legacy_tab)
        until(panel.available)
        assert not w.auto_clamp_enabled, 'Manual controls are independent of Auto simulation enable'
        for field in w.cylinder_timing.fields.values():
            if field.minimum() == 0: field.setValue(0)
        w.cylinder_timing.fields['main.engage_settle'].setValue(100)
        w.cylinder_timing.fields['trigger.spinup'].setValue(100)
        w.cylinder_timing.fields['trigger.brake_wait'].setValue(100)
        assert not panel.request('cycle') and not panel.request('lower') and not panel.request('press')
        assert panel.request('engage')
        assert not panel.request('cycle'), 'Wait for clamp settling'
        until(lambda: not panel.phase)
        assert w.clamp_left_engaged and panel.clamp_settled
        assert panel.cycle_button.isEnabled()
        position = w.ser.pos
        assert not w.send_command('S12') and not w.send_command('H') and not w.send_command('J10.8')
        assert not w.start_auto_cycle() and not w.resume_after_reset()
        assert not w.manual_home_button.isEnabled() and not w.keypad.isEnabled()
        pump(.1); assert w.ser.pos == position

        # Independent trigger and travel controls are available for virtual tests.
        assert panel.request('press'); until(lambda: not panel.phase)
        assert w.ser.blade_pressed and not panel.request('release')
        assert panel.request('unpress'); until(lambda: not panel.phase)
        assert not w.ser.blade_pressed
        assert panel.request('lower'); until(lambda: not panel.phase)
        assert w.ser.saw_down and not w.ser.saw_up
        assert not panel.request('release')
        assert panel.request('up'); until(lambda: not panel.phase)
        assert w.ser.saw_up and not w.ser.saw_down

        # Combined cycle leaves the clamp held and never consumes an Auto cut list.
        w.load_cut_list_lines(['18 A','24 B'])
        before = (list(w.cut_list), w.current_cut_index, w.sim_next_piece_index, w.auto_cycle_state)
        assert panel.request('cycle')
        until(lambda: not panel.phase)
        assert w.clamp_left_engaged and panel.clamp_settled
        assert w.ser.saw_up and not w.ser.blade_pressed
        assert (w.cut_list,w.current_cut_index,w.sim_next_piece_index,w.auto_cycle_state) == before
        assert panel.request('release'); until(lambda: not panel.phase)
        assert not w.clamp_left_engaged and not panel.motion_locked()
        assert w.manual_home_button.isEnabled()

        # Stop invalidates delayed trigger/stroke callbacks and retains the clamp.
        assert panel.request('engage'); until(lambda: not panel.phase)
        w.cylinder_timing.fields['trigger.press_delay'].setValue(250)
        assert panel.request('cycle')
        assert panel.stop()
        pump(.5)
        assert w.clamp_left_engaged and not w.ser.blade_pressed and not w.ser._saw_busy
        # Freshness loss revokes pending actions; no auto restart after recovery.
        assert panel.request('press')
        w._sim_health_received = time.monotonic()-3
        panel.refresh()
        assert not panel.phase and not w.ser.blade_pressed
        pump(.5)
        assert not w.ser.blade_pressed
        assert panel.request('cycle')
        w.toggle_connection(); pump(.5)
        assert not panel.phase and not panel.cycle_button.isEnabled()
        assert 'No hardware outputs' in panel.status.text()
        w.close(); app.processEvents()
    print('Manual pneumatics: native lockout, independent controls, retained clamp, motion exclusion, timing and cancellation OK')


if __name__ == '__main__':
    run()
