"""Saved preferences -> profile ACK -> one Home; 0.22 fallback and lost ACK."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys,tempfile
from pathlib import Path
from unittest.mock import patch
from PyQt6.QtCore import QSettings,QTimer
from PyQt6.QtWidgets import QApplication
import main
from controller_backends import TEENSY_CARRIAGE
from test_native_dry_run import Sketch


def case(exe,legacy=False,drop_ack=False):
    app=QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as folder:
        main.QSettings=lambda *a,**k:QSettings(folder+'/settings.ini',QSettings.Format.IniFormat)
        main.get_app_dir=lambda:folder;main.updater.check_for_update=lambda *a,**k:None
        wire=Sketch(exe)
        with patch('time.monotonic',lambda:wire.now):
            w=main.MinimalHMI()
            for timer in w.findChildren(QTimer):timer.stop()
            w.controller_combo.setCurrentIndex(w.controller_combo.findData(TEENSY_CARRIAGE))
            w.homing_speed.setValue(1200);w.homing_accel.setValue(1500);w.save_homing_settings()
            assert w.saved_homing_settings()==(1200,1500) and not wire.writes
            w.ser=wire;w.set_controls_enabled(True);p=w.carriage_tab;d=w.dry_run
            def records(lines):
                for line in lines:
                    if legacy and line.startswith('BENCH_HELLO,'):
                        line=line.replace('FW:0.23.0','FW:0.22.0').replace('FW:0.24.0','FW:0.22.0').replace('CARRIAGE_V17','CARRIAGE_V16').replace(',HOME_PROFILE:EDITABLE_V1','').replace(',SECOND_CLAMP:D18_MASK_V1','')
                    if drop_ack and line.startswith('BENCH_X,'):
                        line=line.replace('HOME_RATE_PPS:1200','HOME_RATE_PPS:40').replace('HOME_ACCEL_PPS2:1500','HOME_ACCEL_PPS2:200')
                    w.update_message_log(line)
            def flush():
                for _ in range(100):
                    if not wire.commands:return
                    records(wire.exchange(wire.commands.popleft()))
                raise AssertionError('command loop')
            def tick():
                flush();records(wire.exchange('@TICK 100'));p.tick();d.tick();flush()
            records(wire.initial);tick()
            assert p.compatible and d.compatible and p.home_profile_supported is not legacy
            assert not any(c.startswith(('XHOMEPROFILE','XHOME','XARM')) for c in wire.writes)
            profiles=dict(p.profile_values)
            assert w.home_motor();flush()
            for _ in range(1800):
                tick()
                if p.local_fault or d.local_fault:break
                if p.x.get('POS_KNOWN')=='1' and not w.direct_controls.intent:break
            if drop_ack:
                assert p.local_fault=='Profile acknowledgment timed out',(p.local_fault,d.local_fault,wire.writes[-10:])
                assert not any(c.startswith('XHOME ') for c in wire.writes)
                assert not w.direct_controls.intent and p.x['ARMED']=='0'
            else:
                assert not p.local_fault and not d.local_fault,(p.local_fault,d.local_fault,d.message)
                assert p.x['POS_KNOWN']=='1' and p.x['HOME_OFFSET']=='-14'
                assert wire.writes.count('XHOME 20594')==1 and p.profile_values==profiles
                if legacy:
                    assert not any(c.startswith('XHOMEPROFILE') for c in wire.writes)
                    assert 'fixed homing speed' in w.homing_feedback.text()
                else:
                    assert p.x['HOME_RATE_PPS']=='1200' and p.x['HOME_ACCEL_PPS2']=='1500'
                    assert wire.writes.index('XHOMEPROFILE 1200 1500')<wire.writes.index('XHOME 20594')
                    # Saving while idle applies settings but never starts Home.
                    count=wire.writes.count('XHOME 20594')
                    w.homing_speed.setValue(900);w.homing_accel.setValue(800);w.save_homing_settings();flush();tick()
                    assert p.x['HOME_RATE_PPS']=='900' and p.x['HOME_ACCEL_PPS2']=='800'
                    assert wire.writes.count('XHOME 20594')==count and p.x['POS_KNOWN']=='1'
            w.close();app.processEvents()
        wire.close()
    print(f'Homing settings actual-sketch passed: legacy={legacy}, dropped_ack={drop_ack}')


if __name__=='__main__':
    exe=Path(sys.argv[1]) if len(sys.argv)>1 else Path('tmp/firmware-tests/dry_run_server.exe')
    case(exe);case(exe,legacy=True);case(exe,drop_ack=True)
