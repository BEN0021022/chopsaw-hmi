"""Reported two-inch stop: delayed detector, bounded exhaustion, fault reason."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
import math
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from PyQt6.QtCore import QSettings,QTimer
from PyQt6.QtWidgets import QApplication
import main
from controller_backends import TEENSY_CARRIAGE
from test_native_dry_run import Sketch


def run(exe):
    app=QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as folder:
        main.QSettings=lambda *a,**k:QSettings(folder+'/settings.ini',QSettings.Format.IniFormat)
        main.get_app_dir=lambda:folder;main.updater.check_for_update=lambda *a,**k:None
        wire=Sketch(exe)
        with patch('time.monotonic',lambda:wire.now):
            w=main.MinimalHMI()
            for timer in w.findChildren(QTimer):timer.stop()
            w.controller_combo.setCurrentIndex(w.controller_combo.findData(TEENSY_CARRIAGE))
            w.ser=wire;w.set_controls_enabled(True);p=w.carriage_tab;d=w.dry_run
            def records(lines):
                for line in lines:w.update_message_log(line)
            def flush():
                for _ in range(100):
                    if not wire.commands:return
                    records(wire.exchange(wire.commands.popleft()))
                raise AssertionError('command loop')
            def tick(count=100):
                flush();records(wire.exchange(f'@TICK {count}'));p.tick();d.tick();flush()
            def until(condition):
                for _ in range(1800):
                    if condition():return
                    tick()
                    if p.local_fault or d.local_fault:
                        report={'x':p.x,'dry':d.data,'reason':d.message,'commands':wire.writes[-20:]}
                        Path('tmp/acquisition-failure.json').write_text(json.dumps(report,indent=2))
                        raise AssertionError(report)
                raise AssertionError((d.message,p.x))
            records(wire.initial);tick();assert w.home_motor();flush()
            until(lambda:w.direct_controls.intent is None)
            assert p.edit_profile(1,600,600);flush();tick()
            sup=d.supervision
            for key,value in dict(main_near=8.75,main_far=9.75,front_offset=0,rear_extent=16.75,
                                  keepout=1,margin=.5,sensor_near=10.8,sensor_far=10.8,max_clear_push=160).items():
                sup.fields[key].setValue(value)
            assert sup.save();w.kerf_input.setValue(.12);w.load_cut_list_lines(['20 delayed detection'])
            assert p.edge_search.value()==2 # commissioning widget must not cap Auto
            saved=p.x.copy()
            for offset in (-14,-5000,-12000):
                p.x=dict(saved,HOME_OFFSET=str(offset))
                count=int(d.acquisition_command().split()[1])
                capture=160.5+(offset-count)/127.12
                assert offset-count>=int(saved['SOFT_MIN_OFFSET']) and count>0
                assert capture-10.8-.12>sup.coordinator.geometry.cut_keepout
            p.x=dict(saved,HOME_OFFSET=str(math.ceil((11.92-160.5)*127.12)))
            assert d.acquisition_command() is None
            p.x=dict(saved,POS_KNOWN='0');assert d.acquisition_command() is None
            p.x=saved
            assert p.edge_command().split()[1]=='254' # advanced bench remains bounded separately
            assert w.start_auto_cycle();flush();until(lambda:d.sequence and d.sequence['stage']=='SEARCH')
            origin=int(p.x['HOME_OFFSET'])
            until(lambda:origin-int(p.x['HOME_OFFSET'])>=int(8*127.12))
            assert d.sequence['stage']=='SEARCH' and p.x['FAULT']=='NONE' and p.x['PROFILE_ID']=='1'
            records(wire.exchange('@PIN 21 0'));until(lambda:d.sequence and d.sequence['stage']=='MOVE')
            assert int(p.x['EDGE_MILLI'])-int(p.x['TRUING_MILLI'])==10920
            assert p.x['PROFILE_ID']=='1'
            d.stop();flush();tick();records(wire.exchange('@PIN 21 1'));tick()
            # New acquisition without detector must stop at its geometric bound,
            # preserve the actual cause, and never send a truing/cylinder command.
            assert w.start_auto_cycle();flush();until(lambda:d.sequence and d.sequence['stage']=='SEARCH')
            command=next(c for c in reversed(wire.writes) if c.startswith('XEDGE '))
            search_pulses=int(command.split()[1]);assert search_pulses>254
            start=len(wire.writes);initial=int(p.x['HOME_OFFSET'])
            for _ in range(1800):
                tick()
                if d.local_fault:break
            assert p.x['EDGE_ERROR']=='NOT_FOUND' and p.x['FAULT']=='EDGE_FAILED'
            assert 'Board detector not found' in d.local_fault,d.local_fault
            assert d.sequence is None and p.x['ARMED']=='0' and p.x['POS_KNOWN']=='0'
            assert initial-int(p.x['HOME_OFFSET'])==search_pulses
            assert not any(c.startswith(('XTRUING','DARM','DCUT','DOPCUT')) for c in wire.writes[start:])
            assert all(d.data[k]=='0' for k in ('CLAMP','SAW','TRIGGER','CYCLE'))
            # A later generic stop reason must not erase the first controller cause.
            cause=d.local_fault;d.tick();assert d.local_fault==cause
            w.close()
        wire.close()
    print('Auto acquisition regression passed: detector after eight inches, Gentle truing, bounded no-detection stop and specific first fault.')


if __name__=='__main__':run(Path(sys.argv[1]) if len(sys.argv)>1 else Path('tmp/firmware-tests/dry_run_server.exe'))
