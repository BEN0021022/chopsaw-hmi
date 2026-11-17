"""Actual sketch + HMI: semi-auto, manual overrides, pause/resume, scrap modes."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import csv
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from PyQt6.QtCore import QSettings,QTimer
from PyQt6.QtGui import QFont,QFontDatabase
from PyQt6.QtWidgets import QApplication
import main
from controller_backends import TEENSY_CARRIAGE
from test_native_dry_run import Sketch


def run(exe):
    app=QApplication.instance() or QApplication([])
    if os.name=='nt':
        for font in ('segoeui.ttf','seguisb.ttf','consola.ttf'):QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+font)
        app.setFont(QFont('Segoe UI',10))
    with tempfile.TemporaryDirectory() as folder:
        main.QSettings=lambda *a,**k:QSettings(folder+'/settings.ini',QSettings.Format.IniFormat)
        main.get_app_dir=lambda:folder;main.updater.check_for_update=lambda *a,**k:None
        wire=Sketch(exe)
        with patch('time.monotonic',lambda:wire.now):
            w=main.MinimalHMI()
            for timer in w.findChildren(QTimer):timer.stop()
            w.controller_combo.setCurrentIndex(w.controller_combo.findData(TEENSY_CARRIAGE))
            w.ser=wire;w.set_controls_enabled(True);p=w.carriage_tab;d=w.dry_run
            w.status_label.setText('OFFLINE / emulated Teensy')
            def records(lines):
                for line in lines:w.update_message_log(line)
            def flush():
                for _ in range(100):
                    if not wire.commands:return
                    records(wire.exchange(wire.commands.popleft()))
                raise AssertionError('command loop')
            def tick(count=100):
                flush();records(wire.exchange(f'@TICK {count}'));p.tick();d.tick();flush()
                assert not p.local_fault and not d.local_fault,(p.local_fault,d.local_fault,d.message)
            def until(condition):
                for _ in range(2400):
                    if condition():return
                    tick()
                raise AssertionError((d.message,d.sequence,d.intervention.checkpoint,p.x,wire.writes[-15:]))
            def stage(name):return bool(d.sequence and d.sequence['stage']==name)
            def home():
                assert w.home_motor();flush();until(lambda:w.direct_controls.intent is None)
            records(wire.initial);tick();home()
            for profile,rate,accel in ((1,600,600),(2,2000,1500),(3,3500,2000)):
                assert p.edit_profile(profile,rate,accel);flush();tick()
            sup=d.supervision
            for key,value in dict(main_near=8.75,main_far=9.75,front_offset=0,rear_extent=16.75,
                                  keepout=1,margin=.5,max_clear_push=160).items():sup.fields[key].setValue(value)
            assert sup.save();w.kerf_input.setValue(.12)
            w.auto_modes.setCurrentIndex(1);w.tabs.setCurrentWidget(w.auto_tab);w.resize(1440,1000);w.show();app.processEvents()
            assert not w.operator_cut_button.isHidden() and not w.operator_cut_button.isEnabled()
            assert w.operator_cut_button.text().startswith('Clamp / Cut / Advance')
            assert w.auto_mode_label.text().startswith('SEMI-AUTO')
            assert w.start_cycle_button.text().startswith('Start Semi-Auto')
            w.load_cut_list_lines(['20 first','20 second','20 third'])
            def acquire():
                assert w.start_auto_cycle();flush();until(lambda:stage('SEARCH'))
                if d.sequence['semi']:
                    assert not w.operator_cut_button.isHidden() and not w.operator_cut_button.isEnabled()
                records(wire.exchange('@PIN 21 0'));until(lambda:stage('MOVE'))
                records(wire.exchange('@AUTO_SENSOR 1'))
            acquire();until(lambda:stage('WAIT_CUT_APPROVAL'))
            assert wire.strokes==0 and w.operator_cut_button.isEnabled(),(wire.strokes,d.can_approve_cut(),d.supervision.last_decision,d.data,p.x,w.operator_cut_button.isEnabled(),w.auto_modes.currentIndex())
            assert w.operator_cut_button.text().startswith('True-up / advance')
            # Semi-Auto waits even at truing and does not run a stroke on timers.
            tick(181000);assert wire.strokes==0 and stage('WAIT_CUT_APPROVAL')
            assert d.approve_cut();flush();until(lambda:stage('WAIT_CUT_APPROVAL') and d.sequence['index']==0)
            assert wire.strokes==1 and w._displayed_cut_index==0
            assert w.operator_cut_button.text().startswith('Clamp / Cut / Advance')
            position=sup.context().position
            # A jog is itself enough to enter the paused manual adjustment mode.
            assert w.auto_jog(-1);flush();until(lambda:d.intervention.paused() and w.direct_controls.intent is None)
            assert abs(sup.context().position-(position-1))<.02
            assert w.set_length(sup.context().position);flush();until(lambda:w.direct_controls.intent is None)
            assert d.sequence['index']==0 and d.progress_index==0 and wire.strokes==1
            output=Path('tmp/ui-intervention');output.mkdir(parents=True,exist_ok=True)
            app.processEvents();w.grab().save(str(output/'semi-adjusted.png'))
            assert d.can_approve_cut();assert d.approve_cut();flush()
            until(lambda:stage('WAIT_CUT_APPROVAL') and d.sequence['index']==1)
            assert wire.strokes==2 and abs(sup.context().position-(position-1-20.12))<.03
            # Pause during stroke finishes that cut and does not begin the next feed.
            assert d.approve_cut();flush();until(lambda:d.data['STATE']=='DESCEND')
            assert d.intervention.pause();assert d.intervention.after_cut
            until(lambda:d.intervention.paused())
            assert wire.strokes==3 and d.sequence['next_index']==2 and d.data['CLAMP']=='0' and d.data['TRIGGER']=='0'
            assert w.auto_resume_button.isEnabled() and w.auto_home_button.isEnabled()
            count=len(wire.writes);tick(181000)
            assert not any(c.startswith(('XMOVE','DCUT','DOPCUT')) for c in wire.writes[count:])
            # Return to Load and Home while paused preserve pending cut, but the
            # detached material cannot masquerade as a new board reference.
            assert w.load_position();flush();until(lambda:w.direct_controls.intent is None)
            home();assert d.intervention.checkpoint['home_changed']
            assert not d.intervention.resume_plan() # old board still blocks detector
            records(wire.exchange('@AUTO_SENSOR 0'));tick()
            assert d.intervention.resume_plan()[0]=='acquire'
            assert d.intervention.resume();flush();until(lambda:stage('SEARCH'))
            assert d.sequence['next_index']==2
            records(wire.exchange('@PIN 21 0'));until(lambda:stage('MOVE'));records(wire.exchange('@AUTO_SENSOR 1'))
            until(lambda:stage('WAIT_CUT_APPROVAL'))
            assert d.sequence['index']==-1 and d.sequence['next_index']==2
            assert d.approve_cut();flush();until(lambda:stage('WAIT_CUT_APPROVAL') and d.sequence['index']==2)
            assert d.approve_cut();flush();until(lambda:d.sequence is None)
            assert wire.strokes==5 and d.progress_index==3
            assert d.owner.cut_history.flush()
            with w.cut_history.path.open(newline='',encoding='utf-8') as stream:history=list(csv.DictReader(stream))
            cuts=[r for r in history if r['cut_type']=='cut']
            assert [r['cut_number'] for r in cuts]==['1','2','3']
            assert abs(float(cuts[0]['cut_length_in'])-21)<.03 and cuts[0]['cut_length_source']=='operator_adjusted_feed_estimate'
            assert cuts[1]['cut_length_in']=='20.0' and cuts[2]['cut_length_in']=='20.0'
            # Repeated pattern clears at the boundary, then waits for explicit
            # Continue instead of automatically launching the next board.
            records(wire.exchange('@AUTO_SENSOR 0'));tick()
            w.auto_modes.setCurrentIndex(0);w.repeat_pattern.setChecked(True)
            assert w.auto_mode_label.text().startswith('AUTOMATIC') and w.operator_cut_button.isHidden()
            assert not w.clear_at_list_end.isChecked() and w.clear_between_boards.isChecked()
            w.board_size_radios[1][0].setChecked(True)
            assert w.load_position();flush();until(lambda:w.direct_controls.intent is None)
            w.load_cut_list_lines(['34 a','34 b','34 c']);count=len(wire.writes)
            acquire();until(lambda:d.waiting_for_board())
            assert d.sequence['next_index']==0 and d.progress_index==0
            assert any(c.startswith('XMOVE 103') for c in wire.writes[count:])
            strokes=wire.strokes;tick(181000);assert wire.strokes==strokes and d.waiting_for_board()
            output=Path('tmp/ui-intervention');output.mkdir(parents=True,exist_ok=True)
            app.processEvents();w.grab().save(str(output/'repeat-ready.png'))
            w.auto_cancel_button.click();flush();tick();assert d.sequence is None
            # Finite list returns without moving the 50% remainder to detector.
            records(wire.exchange('@AUTO_SENSOR 0'));tick();w.repeat_pattern.setChecked(False)
            w.load_cut_list_lines(['34 retain remainder']);count=len(wire.writes)
            acquire();until(lambda:d.sequence is None)
            moves=[c for c in wire.writes[count:] if c.startswith('XMOVE ')]
            assert len(moves)==1,moves # XTRUING + one feed; no sensor-clearing push
            assert p.inputs['BOARD_EDGE']=='0' and not p.armed
            # Cancel during moving feed is immediate and never replays it.
            records(wire.exchange('@AUTO_SENSOR 0'));tick();w.load_cut_list_lines(['34 canceled'])
            acquire();w.auto_cancel_button.click();flush();tick();count=len(wire.writes)
            assert d.sequence is None and not d.intervention.resume()
            for _ in range(10):tick()
            assert not any(c.startswith(('XARM 1','DCUT','DOPCUT','XMOVE')) for c in wire.writes[count:])
            w.close()
        wire.close()
    print('Cycle intervention actual-sketch tests passed: Semi-Auto, adjusted baseline, pause-after-stroke, manual Home/reacquisition, repeat/finite scrap policy and Cancel.')


if __name__=='__main__':run(Path(sys.argv[1]) if len(sys.argv)>1 else Path('tmp/firmware-tests/dry_run_server.exe'))
