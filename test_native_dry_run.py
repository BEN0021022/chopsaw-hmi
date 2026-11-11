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
from PyQt6.QtCore import QSettings, QTimer
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
            p.consent.setChecked(True)
            assert w.send_command('XCONFIG 0 1'); flush(); tick()
            assert p.home(); flush(); until(lambda:p.x.get('POS_KNOWN')=='1')
            assert not p.armed and p.x['HOME_STATE']=='DONE'
            # Keep short test movements; engine still uses the actual saved profiles.
            assert p.edit_profile(2,1000,1000); flush(); tick()
            assert p.edit_profile(3,1500,1500); flush(); tick()
            for key in TIMING_KEYS:
                if 'timeout' not in key: w.cylinder_timing.fields[key].setValue(100)
            d.consent.setChecked(True)
            assert d.configure(); flush(); tick()
            assert not d.pending and d.settings_match()
            assert d.data['HASH']==str(timing_hash(d.loaded))
            # Combined Manual actions and source guards.
            assert d.request('arm'); assert not d.request('engage'); flush(); tick()
            # New manual trigger feature is opt-in, one shot, and never Auto.
            assert not d.request('trigger_arm') and not d.request('press')
            d.trigger_consent.setChecked(True)
            assert d.request('trigger_arm'); flush(); tick()
            assert d.data['LOCK']=='0' and d.data['TRIGGER']=='0'
            assert not d.request('engage') and not d.request('cycle')
            assert not w.send_command('XARM 1')
            assert w.manual_pneumatics.request('press'); flush(); tick()
            assert d.data['TRIGGER']=='1' and not d.request('press')
            until(lambda:d.data['LOCK']=='1')
            assert d.data['TRIGGER']=='0' and not d.request('press')
            assert d.request('trigger_arm'); flush(); tick()
            assert d.request('press'); flush(); tick()
            assert d.request('unpress'); flush(); tick()
            assert d.data['TRIGGER']=='0' and d.data['LOCK']=='1'
            assert d.request('trigger_arm'); flush(); tick()
            d.trigger_consent.setChecked(False); flush(); tick()
            assert d.data['LOCK']=='1' and not d.request('trigger_arm')
            assert d.request('engage'); flush(); until(lambda:d.data['STATE']=='CLAMPED')
            assert not w.send_command('XARM 1') and not w.send_command('XDISABLE')
            assert d.request('cycle'); flush(); until(lambda:d.data['STATE']=='DESCEND')
            assert not d.request('release')
            until(lambda:d.data['STATE']=='CLAMPED')
            assert d.data['CLAMP']=='1' and wire.strokes==1
            assert d.request('release'); flush(); until(lambda:d.data['STATE']=='READY')
            d.stop(); assert d.awaiting_stop and not d.allowed('KEEPALIVE'); flush(); tick()
            assert not d.motion_locked()
            # One truing stroke plus one stroke per list item, then stored FAST Load.
            w.load_cut_list_lines(['2 A','3 B'])
            w.board_sensor_location_input.setValue(10.5)
            before=(list(w.cut_list),w.current_cut_index,w.sim_next_piece_index)
            before_trigger_commands=sum(c in ('DTARM','DTPRESS') for c in wire.writes)
            assert d.can_start(), (d.message,p.x)
            w.status_label.setText('OFFLINE TEST FIXTURE')
            w.resize(1280,900); w.tabs.setCurrentWidget(w.auto_tab); w.show(); app.processEvents()
            Path('tmp/ui-dry-run').mkdir(parents=True,exist_ok=True)
            w.grab().save('tmp/ui-dry-run/native-auto.png')
            w.tabs.setCurrentWidget(w.legacy_tab); app.processEvents()
            w.grab().save('tmp/ui-dry-run/native-manual.png')
            w.manual_pneumatics.grab().save('tmp/ui-dry-run/trigger-controls.png')
            w.tabs.setCurrentWidget(w.auto_tab)
            assert d.start_sequence(); flush()
            until(lambda:d.sequence and d.sequence['stage']=='SEARCH')
            for _ in range(3): tick()
            assert p.edge_searching and wire.strokes==1
            records(wire.exchange('@PIN 21 0'))  # operator trips real detector
            until(lambda:d.sequence and d.sequence['stage']=='MOVE')
            records(wire.exchange('@PIN 21 1'))  # release after truing accepted
            until(lambda:d.sequence is None)
            assert d.message.startswith('Unloaded dry list complete'), d.message
            assert wire.strokes==4 and d.data['STATE']=='OFF' and not p.armed
            assert (w.cut_list,w.current_cut_index,w.sim_next_piece_index)==before
            assert 'XPROFILE 2' in wire.writes and any(c.startswith('XLOAD ') for c in wire.writes)
            assert sum(c=='DCYCLE' for c in wire.writes)==4
            assert sum(c in ('DTARM','DTPRESS') for c in wire.writes)==before_trigger_commands
            assert any(c.startswith('XEDGE ') and c.split()[2]=='10500' for c in wire.writes), 'Use shared Settings geometry'
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
            # Lost feedback cancels pending actuation and never restores consent/arm.
            assert d.request('arm'); flush(); tick()
            d.trigger_consent.setChecked(True)
            assert d.request('trigger_arm'); flush(); tick()
            assert d.request('press'); flush(); tick()
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
            w._stop_listener(); w.set_controls_enabled(False); w.close()
        wire.close()
    print('Native unloaded dry run: actual sketch + Qt manual controls, Home, real detector, 2-cut list, truing, return, ACK/hash, exclusion, stop/stale/readback guards OK')


if __name__=='__main__':
    run(Path(sys.argv[1]) if len(sys.argv)>1 else Path('tmp/firmware-tests/dry_run_server.exe'))
