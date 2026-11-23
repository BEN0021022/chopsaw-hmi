"""Actual-sketch multi-board regression for the reported 181-inch cut list."""
import csv
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
from PyQt6.QtCore import QSettings, QTimer
from PyQt6.QtWidgets import QApplication
import main
from controller_backends import TEENSY_CARRIAGE
from test_native_dry_run import Sketch


def run_case(exe, lengths, needs_cleanup):
    app=QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as folder:
        main.QSettings=lambda *a,**k: QSettings(folder+'/settings.ini',QSettings.Format.IniFormat)
        main.get_app_dir=lambda:folder
        main.updater.check_for_update=lambda *a,**k:None
        wire=Sketch(exe)
        with patch('time.monotonic',lambda:wire.now):
            w=main.MinimalHMI()
            for timer in w.findChildren(QTimer): timer.stop()
            w.controller_combo.setCurrentIndex(w.controller_combo.findData(TEENSY_CARRIAGE))
            w.ser=wire; w.set_controls_enabled(True)
            p=w.carriage_tab; d=w.dry_run
            def records(lines):
                for line in lines: w.update_message_log(line)
            def flush():
                for _ in range(100):
                    if not wire.commands:return
                    records(wire.exchange(wire.commands.popleft()))
                raise AssertionError('Command loop')
            def tick(count=100):
                flush(); records(wire.exchange(f'@TICK {count}')); p.tick(); d.tick(); flush()
                assert not p.local_fault and not d.local_fault,(p.local_fault,d.local_fault,d.message)
            def until(condition,seconds=180):
                for _ in range(seconds*10):
                    if condition():return
                    tick()
                raise AssertionError((d.message,p.x,d.data,wire.writes[-10:]))
            records(wire.initial); tick()
            assert w.home_motor(); flush(); until(lambda:p.x.get('POS_KNOWN')=='1')
            for profile,rate,accel in ((1,1200,1500),(2,1500,1500),(3,2000,1500)):
                assert p.edit_profile(profile,rate,accel); flush(); tick()
            w.kerf_input.setValue(.12)
            sup=d.supervision
            # Test-only footprint avoids clamp overlap so this case isolates
            # board capacity. Production dimensions are never changed by tests.
            for key,value in dict(main_near=2,main_far=3,front_offset=0,rear_extent=6,
                                  keepout=1,margin=.25,max_clear_push=160).items():
                sup.fields[key].setValue(value)
            assert sup.save()
            w.load_cut_list_lines([f'{length} test' for length in lengths])
            original=(list(w.cut_list),w.current_cut_index,w.sim_next_piece_index)
            def acquire():
                assert w.start_auto_cycle(),d.message
                flush(); until(lambda:d.sequence and d.sequence['stage']=='SEARCH')
                records(wire.exchange('@PIN 21 0'))
                until(lambda:d.sequence and d.sequence['stage']=='MOVE')
                assert int(p.x['EDGE_MILLI'])-int(p.x['TRUING_MILLI'])==10920
                assert p.x['TRIM_MILLI']=='120'
                records(wire.exchange('@AUTO_SENSOR 1'))
            acquire()
            until(lambda:d.waiting_for_board())
            assert d.sequence['stage']=='WAIT_NEW_BOARD',d.message
            expected_index=3 if len(lengths)==5 else 1
            assert d.sequence['next_index']==expected_index,d.sequence
            assert not p.armed and all(d.data[k]=='0' for k in ('ARMED','CLAMP','SAW','TRIGGER'))
            # No queue consumption or sensor-triggered automatic restart.
            start=len(wire.writes)
            records(wire.exchange('@PIN 21 0')); assert not d.can_begin_auto()
            tick(181000)
            assert d.sequence['stage']=='WAIT_NEW_BOARD'
            assert not any(c.startswith(('XARM 1','DARM','DCUT','XEDGE','XMOVE')) for c in wire.writes[start:])
            records(wire.exchange('@AUTO_SENSOR 0')); tick()
            assert d.can_begin_auto()
            frozen=list(w.cut_list); w.cut_list.append((99,1,'changed'))
            assert not d.can_begin_auto() and not w.start_auto_cycle()
            w.cut_list=frozen
            if needs_cleanup: assert any(c.startswith('XMOVE 10550') for c in wire.writes)
            acquire()
            until(lambda:d.sequence is None)
            assert d.message.startswith('Cut list complete'),d.message
            assert wire.strokes==len(lengths)+2
            assert (w.cut_list,w.current_cut_index,w.sim_next_piece_index)==original
            assert w.cut_history.flush()
            with w.cut_history.path.open(newline='',encoding='utf-8') as stream:rows=list(csv.DictReader(stream))
            assert [float(r['cut_length_in']) for r in rows if r['cut_type']=='cut']==lengths
            assert len({r['board_id'] for r in rows})==2
            assert sum(r['cut_type']=='truing' for r in rows)==2
            assert not p.armed and d.data['STATE']=='OFF'
            # Oversized first cut pauses BEFORE truing or pneumatic arm.
            records(wire.exchange('@AUTO_SENSOR 0')); tick()
            w.load_cut_list_lines(['200 impossible'])
            assert w.start_auto_cycle(); flush(); until(lambda:d.sequence and d.sequence['stage']=='SEARCH')
            previous_strokes=wire.strokes; start=len(wire.writes)
            records(wire.exchange('@PIN 21 0')); until(lambda:d.sequence and d.sequence['stage']=='BOARD_TOO_SHORT')
            assert wire.strokes==previous_strokes and not p.armed
            assert not any(c.startswith(('XTRUING','DARM','DCUT')) for c in wire.writes[start:])
            d.stop(); flush(); tick(); w.close()
        wire.close()
    print(f'Multi-board actual-sketch regression passed: {lengths}; cleanup={needs_cleanup}')


if __name__=='__main__':
    executable=Path(sys.argv[1]) if len(sys.argv)>1 else Path('tmp/firmware-tests/dry_run_server.exe')
    from qt_test_cases import isolated_cases
    isolated_cases(2,lambda i:run_case(executable,[90.,90.] if i else [57.75,57.75,24.,24.,17.5],bool(i)),executable)
