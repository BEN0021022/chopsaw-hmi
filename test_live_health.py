"""Health/freshness policy and Qt display integration; no physical hardware."""
import os
import tempfile
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication
from live_health import native_health, simulator_health, TelemetryActivity, SensorRule, NATIVE_SENSORS
import main
from controller_backends import TEENSY_CARRIAGE
from test_teensy_carriage import FakeSerial, ready, packet


def policy_tests():
    records = {
        'X': {'FAULT':'NONE', 'ALARM_RAW':'1'},
        'SAFETY': {'FAULT':'NONE', 'DOOR_CLOSED':'1', 'SAW_POSITION':'UP', 'BLOCKER':'NONE'},
        'INPUTS': {'HOME':'1', 'BOARD_EDGE':'1', 'FENCE_DOOR':'0', 'SAW_UP':'0',
                   'SAW_DOWN':'1', 'CL57T_ALM':'1'},
    }
    received = {'X':100, 'SAFETY':100, 'INPUTS':100}
    args = dict(connected=True, compatible=True, records=records, received=received, started=100, now=100)
    assert native_health(**args).level == 'healthy', 'Inactive Home/Board and deferred clamp are healthy'
    records['SAFETY']['BLOCKER'] = 'ALREADY_ARMED'
    assert native_health(**args).level == 'healthy', 'Already armed is not a feedback fault'
    records['SAFETY']['BLOCKER'] = 'NONE'
    assert native_health(**dict(args, connected=False)).level == 'neutral'
    assert native_health(**dict(args, compatible=False, received={})).level == 'neutral'
    assert native_health(**dict(args, compatible=False, received={'HELLO':100})).level == 'fault'
    assert native_health(**dict(args, compatible=False, received={}, now=103)).level == 'fault'
    assert native_health(**dict(args, received={'X':100})).level == 'neutral'
    assert native_health(**dict(args, received={'X':103}, now=103)).level == 'fault'
    # New X records or an operating GUI cannot keep old inputs/safety green.
    assert native_health(**dict(args, received=dict(received, X=103), now=103)).level == 'fault'
    assert 'Sensor data stale' in native_health(**dict(args, received=dict(received, X=103, SAFETY=103), now=103)).details
    for key in tuple(records['INPUTS']):
        old = records['INPUTS'].pop(key)
        assert native_health(**args).level == 'fault', key
        records['INPUTS'][key] = 'INVALID'
        assert native_health(**args).level == 'fault', key
        records['INPUTS'][key] = old
    for key, value, reason in (('FENCE_DOOR','1','Guard open'), ('CL57T_ALM','0','Driver alarm'),
                               ('SAW_DOWN','0','conflict'), ('SAW_UP','1','not fully UP')):
        old = records['INPUTS'][key]
        records['INPUTS'][key] = value
        assert any(reason in detail for detail in native_health(**args).details)
        records['INPUTS'][key] = old
    records['X']['ALARM_RAW'] = '0'
    assert 'Driver alarm' in native_health(**args).details
    records['X']['ALARM_RAW'] = '1'
    records['X']['FAULT'] = 'SOFT_LIMIT'
    assert 'SOFT_LIMIT' in native_health(**args).text
    records['X']['FAULT'] = 'NONE'
    assert 'latched' in native_health(**dict(args, local_fault='Local latched fault')).text
    future = SensorRule('PRESSURE_OK', 'Air pressure', healthy_value='1', fault_text='Air pressure low')
    assert native_health(**dict(args, sensors=(*NATIVE_SENSORS, future))).level == 'fault'
    records['INPUTS']['PRESSURE_OK'] = '1'
    assert native_health(**dict(args, sensors=(*NATIVE_SENSORS, future))).level == 'healthy'
    records['INPUTS']['PRESSURE_OK'] = '0'
    assert 'Air pressure low' in native_health(**dict(args, sensors=(*NATIVE_SENSORS, future))).details

    fields = dict(POS='0', STATE='IDLE', SEN='0', BSEN='0', SSEN='1', OCT='0')
    sim = dict(connected=True, fields=fields, received=100, started=100, now=100)
    assert simulator_health(**sim).text == 'System healthy'
    assert simulator_health(**dict(sim, now=103)).level == 'fault'
    assert simulator_health(**dict(sim, received=None)).level == 'neutral'
    fields['OCT'] = '1'
    assert simulator_health(**sim).level == 'fault'
    fields['OCT'] = '0'
    fields.pop('SEN')
    assert simulator_health(**sim).level == 'fault'
    activity = TelemetryActivity()
    assert activity.update(100,100) == 0
    assert abs(activity.update(100.75,100.75) - .5) < 1e-6
    for elapsed in (1.5, 2, 3, 3.5):
        assert activity.update(100+elapsed,100+elapsed) == 1
    assert abs(activity.update(104.25,104.25) - .5) < 1e-6
    assert activity.update(105,105) == 0
    assert activity.update(105.75,105.75) > 0
    assert activity.update(105.75,108) == 0, 'Stale data must stop breathing'
    assert activity.update(105.75,109) == 0, 'GUI ticks alone cannot restart a cycle'
    assert activity.update(109,109) == 0, 'New data resumes with a gentle fade-in'
    assert activity.update(None,110) == 0


def ui_tests():
    app = QApplication.instance() or QApplication([])
    now = [100.0]
    with tempfile.TemporaryDirectory() as folder, patch('main.time.monotonic', side_effect=lambda: now[0]):
        main.QSettings = lambda *a, **k: QSettings(folder+'/settings.ini', QSettings.Format.IniFormat)
        main.updater.check_for_update = lambda *a, **k: None
        w = main.MinimalHMI()
        w.health_timer.stop(); w.carriage_tab.timer.stop()
        w.controller_combo.setCurrentIndex(w.controller_combo.findData(TEENSY_CARRIAGE))
        w.ser = FakeSerial(); wire = w.ser
        w.set_controls_enabled(True)
        assert w.auto_live_status.property('healthState') == 'neutral'
        p = w.carriage_tab
        ready(p)
        assert w.auto_live_status.property('healthState') == 'healthy'
        assert w.live_health_label.text() == 'System healthy'
        assert w.live_health_dot.property('intensity') == 0
        before = list(wire.writes)
        now[0] = 100.3; w.refresh_live_health()
        assert 0 < w.live_health_dot.property('intensity') < 255
        now[0] = 103
        packet(p)  # X is new, safety/inputs are still old
        assert w.auto_live_status.property('healthState') == 'fault'
        assert 'stale' in w.live_health_label.toolTip()
        p.handle_line('BENCH_SAFETY,READY:1,DOOR_CLOSED:1,SAW_POSITION:UP,FAULT:NONE,BLOCKER:NONE')
        p.handle_line('BENCH_INPUTS,HOME:1,BOARD_EDGE:1,FENCE_DOOR:0,SAW_UP:0,SAW_DOWN:1,CL57T_ALM:1')
        assert w.auto_live_status.property('healthState') == 'healthy'
        p.handle_line('BENCH_INPUTS,HOME:1,BOARD_EDGE:1,FENCE_DOOR:1,SAW_UP:0,SAW_DOWN:1,CL57T_ALM:1')
        assert 'Guard open' in w.live_health_label.text()
        assert 'ef4444' in w.auto_live_status.styleSheet()
        assert wire.writes == before, 'Health display itself cannot stop, reset, arm or move hardware'
        w._stop_listener(); w.set_controls_enabled(False)
        assert w.auto_live_status.property('healthState') == 'neutral'
        assert not w.live_health_dot.property('active')
        # Real simulator protocol handling, but no worker thread/hardware access.
        from simulator import VirtualController
        sim = VirtualController(); sim.close(); sim.is_open = True
        w.ser = sim
        w.refresh_live_health()
        assert w.live_health_label.text() == 'Waiting for simulator data'
        w.update_message_log('POS:12,HOMED:0,STATE:IDLE,SEN:0,BSEN:0,SSEN:1,OCT:0')
        assert w.live_health_label.text() == 'System healthy'
        now[0] = 106; w.refresh_live_health()
        assert w.auto_live_status.property('healthState') == 'fault'
        assert not w.live_health_dot.property('active')
        w.update_message_log('POS:12,HOMED:0,STATE:IDLE,SEN:0,BSEN:0,SSEN:1,OCT:0')
        assert w.auto_live_status.property('healthState') == 'healthy'
        w.update_message_log('POS:bad,SEN:0')
        assert w.auto_live_status.property('healthState') == 'fault'
        w.close(); app.processEvents()
    print('Live health: faults, freshness, required/future sensors, simulator separation, heartbeat and read-only UI OK')


if __name__ == '__main__':
    policy_tests()
    ui_tests()
