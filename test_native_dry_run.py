"""Real Qt app <-> real sketch over an in-memory pipe; no serial/hardware access.

The C++ process mocks only GPIO, clock and Serial. Home is driven by physical
model position; board detection is explicitly tripped/released by this test.
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
import subprocess
import tempfile
from collections import deque
from pathlib import Path
from unittest.mock import patch
from PyQt6.QtCore import QSettings, QTimer, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import QApplication
import main
from controller_backends import TEENSY_CARRIAGE
from dry_run_control import TIMING_KEYS, timing_hash


class Sketch:
    def __init__(self, exe):
        self.process=subprocess.Popen([str(exe)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1)
        self.now=0; self.strokes=0; self.pulses=0; self.is_open=True; self.commands=deque(); self.writes=[]
        self.initial=self.read()

    def read(self):
        records=[]
        while True:
            line=self.process.stdout.readline().strip()
            if not line: raise AssertionError('Sketch process terminated')
            if line=='@END': return records
            if line.startswith('@WORLD,'):
                _,world,strokes,pulses,now=line.split(',')
                self.strokes=int(strokes); self.pulses=int(pulses); self.now=int(now)/1000
            else: records.append(line)

    def exchange(self,line):
        self.process.stdin.write(line+'\n'); self.process.stdin.flush()
        return self.read()

    def write(self,data):
        line=data.decode().strip(); self.writes.append(line); self.commands.append(line)
        return len(data)

    def close(self):
        if self.is_open:
            self.is_open=False; self.process.stdin.close(); self.process.wait(timeout=3)


def run(exe):
    app=QApplication.instance() or QApplication([])
    if os.name=='nt':
        for font in ('segoeui.ttf','seguisb.ttf','consola.ttf'):
            QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+font)
        app.setFont(QFont('Segoe UI',10))
    with tempfile.TemporaryDirectory() as folder:
        main.QSettings=lambda *a,**k: QSettings(folder+'/settings.ini',QSettings.Format.IniFormat)
        main.get_app_dir=lambda: folder  # Metrics and other writable test data stay isolated.
        main.updater.check_for_update=lambda *a,**k: None
        wire=Sketch(exe)
        with patch('time.monotonic',lambda: wire.now):
            w=main.MinimalHMI()
            for timer in w.findChildren(QTimer): timer.stop()
            w.controller_combo.setCurrentIndex(w.controller_combo.findData(TEENSY_CARRIAGE))
            w.ser=wire; w.set_controls_enabled(True)
            p=w.carriage_tab; d=w.dry_run
            def records(lines):
                for line in lines: w.update_message_log(line)
            def flush():
                for _ in range(100):
                    if not wire.commands: return
                    records(wire.exchange(wire.commands.popleft()))
                raise AssertionError('Command loop')
            def tick(count=100):
                flush(); records(wire.exchange(f'@TICK {count}'))
                p.tick(); d.tick(); flush()
                assert not p.local_fault, (p.local_fault,d.message,wire.writes[-10:])
            def until(condition, seconds=120):
                for _ in range(seconds*10):
                    if condition(): return
                    tick()
                    assert not d.local_fault, (d.local_fault,d.message,wire.writes[-15:])
                    assert p.x.get('FAULT')=='NONE', (p.x,d.message)
                raise AssertionError((d.message,p.x,wire.writes[-15:]))
            records(wire.initial); flush(); tick()
            assert d.compatible and p.compatible
            assert not d.can_start() and not w.send_command('DARM 1')
            assert not w.manual_pneumatics.request('press')
            assert not w.send_command('OUT 2 1')
            assert not any(c.startswith(('XARM','DARM','XHOME','XMOVE')) for c in wire.writes)
            assert w.home_motor(); flush(); until(lambda:p.x.get('POS_KNOWN')=='1')
            assert 'XCONFIG 0 1' in wire.writes and 'XHOME 20594' in wire.writes
            assert not p.armed and p.x['HOME_STATE']=='DONE'
            # Keep short test movements; engine still uses the actual saved profiles.
            assert p.edit_profile(2,1000,1000); flush(); tick()
            assert p.edit_profile(3,1500,1500); flush(); tick()
            assert p.edit_profile(1,1200,1500); flush(); tick()
            # Measured geometry in this test fixture; live defaults remain
            # uncommissioned and cannot authorize automatic cuts.
            sup=d.supervision
            for key,value in dict(main_near=9,main_far=10,front_offset=0,rear_extent=6,
                                  keepout=1,margin=.25,sensor_near=10.8,sensor_far=10.8,max_clear_push=162).items():
                sup.fields[key].setValue(value)
            sup.verified.setChecked(True); sup.automatic_clear.setChecked(True)
            assert sup.save()
            assert sup.register_stock(), 'Explicit operator material registration, no actuator write'
            for key in TIMING_KEYS:
                if 'timeout' not in key: w.cylinder_timing.fields[key].setValue(100)
            # Observed phase coverage needs a spin-up longer than the 100ms
            # host sample interval; do not depend on Home's clock alignment.
            w.cylinder_timing.fields['trigger.spinup'].setValue(300)
            d.consent.setChecked(True)
            assert d.configure(); flush(); tick()
            assert not d.pending and d.settings_match()
            assert d.data['HASH']==str(timing_hash(d.loaded))
            # One explicit Manual-enable gesture configures/arms without output.
            w.resize(1280,900); w.tabs.setCurrentWidget(w.legacy_tab); w.show(); w.activateWindow(); app.processEvents()
            assert d.enable_manual(); flush(); until(lambda:d.data.get('MANUAL')=='1' and not d.manual_start)
            assert d.data['TRIGGER']=='0' and d.data['CLAMP']=='0' and d.data['SAW']=='0'
            panel=w.manual_pneumatics; panel.refresh(); press=panel.buttons['press']
            assert press.isEnabled() and not d.request('press')
            QTest.mousePress(press,Qt.MouseButton.LeftButton); flush(); tick()
            assert d.data['TRIGGER']=='1'
            assert not d.request('engage') and not d.request('cycle')
            assert not w.send_command('XARM 1')
            for _ in range(35): tick()
            assert d.data['TRIGGER']=='1', 'Hold is not a two-second timed pulse'
            QTest.mouseRelease(press,Qt.MouseButton.LeftButton); flush(); tick()
            assert d.data['TRIGGER']=='0' and d.data['MANUAL']=='1'
            panel.refresh(); QTest.mousePress(press,Qt.MouseButton.LeftButton); flush(); tick()
            assert d.data['TRIGGER']=='1', 'No per-action rearm'
            w.tabs.setCurrentWidget(w.auto_tab); tick()
            assert d.data['TRIGGER']=='0' and not d.trigger_held
            QTest.mouseRelease(press,Qt.MouseButton.LeftButton)
            w.tabs.setCurrentWidget(w.legacy_tab); panel.refresh()
            QTest.mousePress(press,Qt.MouseButton.LeftButton); flush(); tick()
            assert d.data['TRIGGER']=='1'
            with patch.object(w,'isActiveWindow',return_value=False): tick()
            assert d.data['TRIGGER']=='0' and not d.trigger_held
            QTest.mouseRelease(press,Qt.MouseButton.LeftButton); flush(); tick()
            assert not w.send_command('XARM 1') and not w.send_command('XDISABLE')
            assert d.request('cycle'); flush(); until(lambda:d.data['STATE']=='DESCEND')
            assert d.data['CLAMP']=='1' and d.data['TRIGGER']=='1'
            assert not d.request('release')
            until(lambda:d.data['STATE']=='READY' and d.data['DONE']=='1')
            assert d.data['CLAMP']=='0' and d.data['TRIGGER']=='0' and wire.strokes==1
            d.stop(); assert d.awaiting_stop and not d.allowed('KEEPALIVE'); flush(); tick()
            assert not d.motion_locked()
            # One truing stroke plus one stroke per list item, then stored FAST Load.
            w.load_cut_list_lines(['2 A','3 B'])
            w.clear_at_list_end.setChecked(True) # explicit end-of-list clearing mode
            w.board_sensor_location_input.setValue(10.5)
            sup.fields['sensor_near'].setValue(10.5); sup.fields['sensor_far'].setValue(10.5)
            records(wire.exchange('@SENSOR_ZONE 10.5'))
            sup.verified.setChecked(True); assert sup.save()  # explicitly verify changed test-fixture truing datum
            before=(list(w.cut_list),w.current_cut_index,w.sim_next_piece_index)
            before_trigger_commands=sum(c=='DTPRESS' or c.startswith('DMANUAL ') for c in wire.writes)
            assert d.can_begin_auto(), (d.message,p.x)
            w.status_label.setText('OFFLINE TEST FIXTURE')
            w.resize(1280,900); w.tabs.setCurrentWidget(w.auto_tab); w.show(); app.processEvents()
            Path('tmp/ui-dry-run').mkdir(parents=True,exist_ok=True)
            w.grab().save('tmp/ui-dry-run/native-auto.png')
            w.tabs.setCurrentWidget(w.legacy_tab); app.processEvents()
            w.grab().save('tmp/ui-dry-run/native-manual.png')
            w.manual_pneumatics.grab().save('tmp/ui-dry-run/trigger-controls.png')
            w.tabs.setCurrentWidget(w.auto_tab)
            assert w.start_auto_cycle(); flush()
            until(lambda:d.sequence and d.sequence['stage']=='SEARCH')
            for _ in range(3): tick()
            assert p.edge_searching and wire.strokes==1
            records(wire.exchange('@PIN 21 0'))  # operator trips real detector
            until(lambda:d.sequence and d.sequence['stage']=='MOVE')
            assert int(p.x['SENSOR_OFFSET_MILLI'])==10500 and int(p.x['TRIM_MILLI'])==100
            assert int(p.x['TRUING_MILLI'])==int(p.x['EDGE_MILLI'])-10600, 'Sensor + kerf, not sensor minus trim'
            records(wire.exchange('@PIN 21 1'))  # release after truing accepted
            records(wire.exchange('@AUTO_SENSOR 1'))  # independent push-only remnant physics
            until(lambda:d.sequence is None)
            assert d.message.startswith('Unloaded dry list complete'), d.message
            assert wire.strokes==4 and d.data['STATE']=='OFF' and not p.armed
            import csv
            assert w.cut_history.flush()
            with w.cut_history.path.open(newline='',encoding='utf-8') as stream:
                history=list(csv.DictReader(stream))
            assert len(history)==4, history  # Manual, truing, then two list cuts.
            assert [row['cut_type'] for row in history]==['cut','truing','cut','cut']
            assert [row['cut_length_in'] for row in history[-2:]]==['2.0','3.0']
            assert all(row['run_type']=='dry_run' for row in history)
            assert history[0]['cut_length_in']=='' and history[0]['board_length_in']==''
            assert all(row['board_length_source']=='edge_estimate' for row in history[1:])
            assert len({row['board_id'] for row in history[1:]})==1
            assert len({row['board_length_in'] for row in history[1:]})==1
            assert all(float(row['board_length_in'])>3 for row in history[1:])
            for _ in range(3): tick()
            assert w.cut_history.flush()
            with w.cut_history.path.open(newline='',encoding='utf-8') as stream:
                assert len(list(csv.DictReader(stream)))==4, 'Repeated DONE must not duplicate a cut'
            assert (w.cut_list,w.current_cut_index,w.sim_next_piece_index)==before
            assert 'XPROFILE 2' in wire.writes and any(c.startswith('XLOAD ') for c in wire.writes)
            assert sum(c=='DCUT' for c in wire.writes)==4
            assert any(c=='XPROFILE 1' for c in wire.writes), 'Clearance uses Gentle, not return speed'
            assert any(c.startswith('XMOVE 10250') for c in wire.writes), 'Minimum sensor-zone clearing, not zero/full ejection'
            assert d.supervision.coordinator.material.stock.far<10.5
            assert sum(c=='DTPRESS' or c.startswith('DMANUAL ') for c in wire.writes)==before_trigger_commands
            assert any(c.startswith(('XEDGE ','XACQUIRE ')) and c.split()[2]=='10500' for c in wire.writes), 'Use shared Settings geometry'
            # Diagnostics observe the actual sketch; they never insert commands.
            observed=d.diagnostics.report(wire.now)
            assert any(r['controller']=='DESCEND' and r['timing_kind']=='travel limit' for r in observed['phases'])
            assert any(r['controller']=='SPINUP' and r['timing_source']=='controller hash acknowledged' for r in observed['phases'])
            assert any(e['event']=='CLEAR_ACQUISITION_ZONE' for e in observed['events'])
            assert any(e['event']=='PHASE' and e.get('snapshot',{}).get('controller_readback',{}).get('TRIGGER')=='1'
                       for e in observed['events']), 'Per-phase export retains actual output readback'
            assert observed['latest']['controller_readback']['STATE']=='OFF'
            assert observed['latest']['acknowledged_timings_ms'] == dict(zip(TIMING_KEYS,d.loaded))
            w.machine_workbench.pages.setCurrentIndex(1); app.processEvents()
            w.tabs.setCurrentWidget(w.full_auto_tab); app.processEvents()
            w.grab().save('tmp/ui-dry-run/diagnostics.png')
            assert w.machine_workbench.export_report(path=Path(folder)/'actual-sketch-report.json')
            # Stop during the acknowledged preparation cannot later start motion.
            records(wire.exchange('@AUTO_SENSOR 0'))
            # Geometric interference pauses Auto before DARM/clamp/trigger.
            sup.fields['main_near'].setValue(149); sup.fields['main_far'].setValue(151)
            assert sup.save()
            before_cycles=sum(c=='DCUT' for c in wire.writes)
            assert w.start_auto_cycle(); flush(); until(lambda:d.sequence and d.sequence['stage']=='SEARCH')
            records(wire.exchange('@PIN 21 0'))
            until(lambda:d.sequence and d.sequence['stage']=='OPERATOR_REQUIRED')
            assert d.data['ARMED']=='0' and d.data['CLAMP']=='0' and d.data['TRIGGER']=='0'
            assert not w.send_command('DCUT') and not w.send_command('DCLAMP 1')
            panel.refresh(); assert not panel.cycle_button.isEnabled() and 'review' in panel.cycle_button.text()
            w.tabs.setCurrentWidget(w.legacy_tab); app.processEvents()
            w.grab().save('tmp/ui-dry-run/operator-required.png')
            panel.cycle_button.click(); flush(); tick()
            assert sum(c=='DCUT' for c in wire.writes)==before_cycles
            assert d.sequence['stage']=='OPERATOR_REQUIRED', 'A button click cannot invent holding or bypass main-clamp interference'
            assert not p.armed and d.data['CLAMP']=='0' and d.data['TRIGGER']=='0'
            assert not sup.save(), 'Geometry cannot change under a paused live plan'
            d.stop(); flush(); tick()
            records(wire.exchange('@PIN 21 1'))
            sup.fields['main_near'].setValue(9); sup.fields['main_far'].setValue(10); assert sup.save()
            assert w.start_auto_cycle()
            w.cancel_auto_cycle(); flush(); tick()
            assert d.auto_start is None and d.sequence is None and d.data['STATE']=='OFF'
            count=len(wire.writes)
            for _ in range(5): tick()
            assert not any(c.startswith(('XARM 1','DARM','DMANUAL','DCUT','XEDGE')) for c in wire.writes[count:])
            # No silent timing changes; a fresh acknowledged snapshot is required.
            w.cylinder_timing.fields['main.engage_settle'].setValue(200)
            assert not d.settings_match() and not d.can_start()
            assert d.configure(); flush(); tick()
            # STOP revokes a live sequence without progressing after recovery.
            assert d.start_sequence(); flush(); until(lambda:p.edge_searching)
            d.stop(); flush(); tick()
            assert d.sequence is None and not p.armed and d.data['STATE']=='OFF'
            count=len(wire.writes)
            for _ in range(10): tick()
            assert not any(c.startswith(('XARM 1','DARM','DCLAMP','DCYCLE','XMOVE','XEDGE')) for c in wire.writes[count:])
            # Manual combined Stop retains clamp until UP/brake wait + explicit release.
            assert d.enable_manual(); flush(); until(lambda:d.data.get('MANUAL')=='1' and not d.manual_start)
            assert sup.register_stock()
            assert d.request('cycle'); flush(); until(lambda:d.data['STATE']=='DESCEND')
            d.stop(); flush(); until(lambda:d.data['STATE']=='STOPPED' and d.data['RELEASE_READY']=='1')
            assert d.data['CLAMP']=='1' and d.data['TRIGGER']=='0' and not d.can_begin_auto()
            assert d.request('recover_release'); flush(); tick()
            assert d.data['CLAMP']=='0' and d.data['STATE']=='OFF'
            # Lost feedback cancels pending actuation and never restores consent/arm.
            w.tabs.setCurrentWidget(w.legacy_tab); w.activateWindow(); app.processEvents()
            assert d.enable_manual(); flush(); until(lambda:d.data.get('MANUAL')=='1' and not d.manual_start)
            panel.refresh(); QTest.mousePress(press,Qt.MouseButton.LeftButton); flush(); tick()
            assert d.data['TRIGGER']=='1'
            d.received=wire.now-3; d.tick(); assert d.local_fault
            assert not d.allowed('DCLAMP 1'); flush(); tick()
            assert d.data['STATE']=='OFF' and not d.can_start()
            assert d.data['TRIGGER']=='0' and d.data['LOCK']=='1'
            d.acknowledge(); flush(); tick()
            assert not d.local_fault and not d.consent.isChecked()
            # Contradictory outputs/phase must be rejected before enabling a control.
            corrupt=dict(d.data,STATE='OFF',CLAMP='1')
            d.handle('BENCH_DRY,'+','.join(f'{k}:{v}' for k,v in corrupt.items()))
            assert d.local_fault=='Invalid dry-run readback'
            flush()
            assert w.cut_history.flush()
            with w.cut_history.path.open(newline='',encoding='utf-8') as stream:
                assert len(list(csv.DictReader(stream)))==4, 'Cancelled/faulted/rejected cycles are not completed cuts'
            w._stop_listener(); w.set_controls_enabled(False); w.close()
        wire.close()
    print('Native unloaded dry run: actual sketch + Qt manual controls, Home, real detector, 2-cut list, truing, return, ACK/hash, exclusion, stop/stale/readback guards OK')


if __name__=='__main__':
    run(Path(sys.argv[1]) if len(sys.argv)>1 else Path('tmp/firmware-tests/dry_run_server.exe'))
