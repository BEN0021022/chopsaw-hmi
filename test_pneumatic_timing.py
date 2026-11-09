"""Timing migration, independent sequencing and cancellation without hardware."""
import heapq
import os
import tempfile
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication
import main
from controller_backends import TEENSY_CARRIAGE
from pneumatic_timing import FIELDS, simulation_clamps
from simulator import VirtualController
from test_teensy_carriage import FakeSerial


class Scheduler:
    def __init__(self):
        self.now = 0
        self.jobs = []
        self.sequence = 0

    def schedule(self, delay, callback):
        self.sequence += 1
        heapq.heappush(self.jobs, (self.now+delay, self.sequence, callback))

    def until(self, limit):
        while self.jobs and self.jobs[0][0] <= limit:
            self.now, _, callback = heapq.heappop(self.jobs)
            callback()
        self.now = limit


def run():
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as folder:
        main.QSettings = lambda *a, **k: QSettings(folder+'/settings.ini', QSettings.Format.IniFormat)
        main.updater.check_for_update = lambda *a, **k: None
        old = main.QSettings()
        old.setValue('clamp_engage_delay', 475)
        old.setValue('saw_start_delay', 925)
        w = main.MinimalHMI()
        w.health_timer.stop(); w.carriage_tab.timer.stop()
        fields = w.cylinder_timing.fields
        assert fields['board.settle'].value() == 475
        for device in ('main','outfeed','fence'):
            assert fields[f'{device}.engage_settle'].value() == 925
        assert not hasattr(w, 'fa_clamp_engage_delay') and not hasattr(w, 'fa_saw_start_delay')
        assert w.speed_tab.isAncestorOf(w.cylinder_timing)
        assert w.speed_tab.isAncestorOf(w.auto_clamp_checkbox)
        assert not w.full_auto_tab.isAncestorOf(w.cylinder_timing)
        fields['main.engage_settle'].setValue(1100)
        w.cylinder_timing.save_button.click()
        fields['main.engage_settle'].setValue(0)
        w.cylinder_timing.load()
        assert fields['main.engage_settle'].value() == 1100, 'New keys take precedence over migration aliases'
        # Save/planning and old virtual geometry cannot issue live pneumatic commands.
        w.controller_combo.setCurrentIndex(w.controller_combo.findData(TEENSY_CARRIAGE))
        w.ser = FakeSerial(); w.set_controls_enabled(True)
        wire = w.ser
        fields['saw.down_delay'].setValue(321)
        w.cylinder_timing.save_button.click()
        assert not w.auto_clamp_checkbox.isEnabled()
        assert not w._engage_clamps_for_cut() and not w._actuate_saw()
        assert not wire.writes
        w._stop_listener()

        # Use a stopped virtual controller with a deterministic callback clock.
        sim = VirtualController(); sim.close(); sim.is_open = True
        w.ser = sim; w.set_controls_enabled(True)
        w.auto_clamp_checkbox.setChecked(True)
        assert w.auto_clamp_enabled
        for field in FIELDS:
            if not field.planned_limit:
                fields[field.key].setValue(0)
        values = {'board.settle':20, 'main.engage_delay':40, 'main.engage_settle':60,
                  'outfeed.engage_delay':10, 'outfeed.engage_settle':120, 'fence.engage_settle':30,
                  'saw.up_settle':25, 'trigger.release_delay':35, 'trigger.brake_wait':45,
                  'main.release_delay':30, 'main.release_clearance':40,
                  'outfeed.release_delay':5, 'outfeed.release_clearance':60,
                  'fence.release_clearance':10}
        for key, value in values.items(): fields[key].setValue(value)
        scheduler = Scheduler()
        sent = []
        original_send = w.send_command
        w.send_command = lambda command: (sent.append((scheduler.now,command)), original_send(command))[1]
        w._record_sim_piece = lambda *a: None
        completed = []
        w._on_cut_finished = lambda: completed.append(scheduler.now)
        w.current_position = 10
        w.auto_cycle_state = 'WAITING_FOR_CUT'
        with patch('main.QTimer.singleShot', side_effect=scheduler.schedule):
            assert w._engage_clamps_for_cut()
            scheduler.until(19)
            assert not sent
            scheduler.until(149)
            assert [item for item in sent if item[1].startswith('C')] == [(20,'C3'),(30,'C2'),(60,'C1')]
            assert not any(command == 'V1' for _,command in sent)
            scheduler.until(150)
            assert sent[-1] == (150,'V1'), 'Wait for the slowest participating clamp'
            assert not w.cut_complete_pressed(), 'Legacy simulator ACK cannot skip timing phases'
            assert not w.start_auto_cycle() and not w.resume_after_reset()
            fields['main.release_delay'].setValue(999)
            w._last_saw_sensor = 0
            w.update_saw_position_sensor_status(1)
            scheduler.until(254)
            assert not any(command.startswith('D') for _,command in sent)
            scheduler.until(324)
            assert [item for item in sent if item[1].startswith('D')] == [(255,'D3'),(260,'D2'),(285,'D1')]
            assert not completed
            scheduler.until(325)
            assert completed == [325] and not w._simulation_pneumatic_pending
            assert w._legacy_cut_completion_ready
            # Cancel at the board-settle stage; no delayed extension or stroke survives.
            sent.clear(); completed.clear()
            assert w._engage_clamps_for_cut()
            w.cancel_auto_cycle()
            scheduler.until(2000)
            assert not any(command.startswith('C') or command == 'V1' for _,command in sent)
            assert not completed and not sim._events and not sim._saw_busy
            # Disconnect/port replacement also invalidates delayed actions.
            assert w._engage_clamps_for_cut()
            w._stop_listener()
            sent.clear(); scheduler.until(4000)
            assert not sent

        assert simulation_clamps(10, True) == (1,3)
        assert simulation_clamps(10, False) == (1,2,3)
        assert simulation_clamps(2, False) == (2,)
        # Saw timing is injected into the virtual travel model, not hard-coded waits.
        sim.is_open = True
        sim.configure_saw_timing({'trigger.press_delay':100, 'trigger.spinup':200,
                                  'saw.down_delay':300, 'saw.bottom_dwell':400, 'saw.up_delay':500})
        sim._events.clear()
        with patch('simulator.time.monotonic', return_value=10):
            sim._start_saw_stroke()
        assert [round(due-10, 3) for due,_ in sim._events] == [1,2.2,4.1]
        sim.cancel_saw_cycle(); sim.close()
        w.close(); app.processEvents()
    print('Cylinder timing: migration, persistence, per-clamp barriers, snapshots, saw delays, cancellation and native lockout OK')


if __name__ == '__main__':
    run()
