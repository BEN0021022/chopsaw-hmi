"""Real sketch/Qt: profiles, operator-held last cut, early return and progress."""
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


def run(exe,overlap=False):
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
            w.ser=wire;w.set_controls_enabled(True)
            p=w.carriage_tab;d=w.dry_run
            seen=[]
            def records(lines):
                for line in lines:
                    w.update_message_log(line)
                    if line.startswith('BENCH_X,') and d.sequence:
                        seen.append((d.sequence['stage'],p.x.copy()))
                    if line.startswith('BENCH_DRY,') and d.data.get('OPERATOR')=='1':
                        assert d.data['CLAMP']=='0' and d.data['CYCLE']=='1'
            def flush():
                for _ in range(100):
                    if not wire.commands:return
                    records(wire.exchange(wire.commands.popleft()))
                raise AssertionError('command loop')
            def tick(count=100):
                flush();records(wire.exchange(f'@TICK {count}'));p.tick();d.tick();flush()
                assert not p.local_fault and not d.local_fault,(p.local_fault,d.local_fault,d.message)
            def until(condition,seconds=180):
                for _ in range(seconds*10):
                    if condition():return
                    tick()
                raise AssertionError((d.sequence,d.message,p.x,d.data,wire.writes[-15:]))
            records(wire.initial);tick()
            assert w.home_motor();flush();until(lambda:w.direct_controls.intent is None)
            for profile,rate,accel in ((1,600,600),(2,2000,1500),(3,3500,2000)):
                assert p.edit_profile(profile,rate,accel);flush();tick()
            sup=d.supervision
            for key,value in dict(main_near=8.75,main_far=9.75,front_offset=0,rear_extent=16.75,
                                  keepout=1,margin=.5,sensor_near=10.8,sensor_far=10.8,max_clear_push=160).items():
                sup.fields[key].setValue(value)
            assert sup.save();w.kerf_input.setValue(.12)
            w.load_cut_list_lines(['142 first','2 last usable','40 next board'])
            original=tuple(w.cut_list)
            w.tabs.setCurrentWidget(w.auto_tab);w.resize(1280,900);w.show();app.processEvents()
            def acquire():
                assert w.start_auto_cycle();flush();until(lambda:d.sequence and d.sequence['stage']=='SEARCH')
                assert p.x['PROFILE_ID']=='1' and p.x['RATE_PPS']=='600'
                records(wire.exchange('@PIN 21 0'))
                until(lambda:d.sequence and d.sequence['stage']=='MOVE')
                assert p.x['PROFILE_ID']=='1' and p.x['TRIM_MILLI']=='120'
                records(wire.exchange('@AUTO_SENSOR 1'))
            acquire()
            until(lambda:d.sequence and d.sequence['stage']=='WAIT_OPERATOR_CUT')
            assert d.sequence['index']==0 and not d.sequence['early_return']
            assert p.x['PROFILE_ID']=='2' and d.data['ARMED']=='0'
            assert w._displayed_cut_index==0 and '> Cut 1:' in w.cut_list_display.toPlainText()
            assert d.can_confirm_operator_cut() and not w.send_command('DCUT')
            assert not w.send_command(f"DOPCUT {d.token} {int(d.data['REQ'])+1}")
            count=len(wire.writes);tick(181000)
            assert d.sequence['stage']=='WAIT_OPERATOR_CUT' and w._displayed_cut_index==0
            assert not any(c.startswith(('DOPCUT','DARM','XLOAD')) for c in wire.writes[count:])
            assert d.confirm_operator_cut();assert not d.confirm_operator_cut()
            flush();until(lambda:d.sequence and d.sequence['stage']=='EARLY_RETURN_ARM')
            assert not w.operator_cut_button.isHidden() and not w.operator_cut_button.isEnabled()
            assert w.operator_cut_button.property('earlyReturnAttention') is True
            app.processEvents();button_image=w.operator_cut_button.grab().toImage()
            amber=button_image.pixelColor(button_image.width()//2,5)
            assert amber.red()>220 and amber.green()>100 and amber.blue()<80,amber.name()
            output=Path('tmp/ui-operator');output.mkdir(parents=True,exist_ok=True)
            w.grab().save(str(output/'waiting-before-return.png'))
            count=len(wire.writes);w.operator_cut_button.click();assert len(wire.writes)==count
            assert d.sequence['index']==1 and w._displayed_cut_index==1
            assert not d.can_confirm_operator_cut()
            assert d.intervention.pause();flush();until(lambda:d.intervention.paused())
            assert d.intervention.resume_plan()[0]=='early_return'
            assert d.intervention.resume();flush()
            until(lambda:d.sequence and d.sequence['stage']=='EARLY_RETURN_WAIT')
            assert w.operator_cut_button.property('earlyReturnAttention') is True and w.operator_cut_button.isEnabled()==p.parallel_supported()
            if overlap:
                assert d.can_confirm_operator_cut() and p.armed and int(p.x['REMAINING'])>0
                strokes=wire.strokes;w.operator_cut_button.click();flush()
                until(lambda:wire.strokes==strokes+1)
                assert p.armed and int(p.x['REMAINING'])>0 and d.data['OPERATOR']=='1'
                assert not d.can_confirm_operator_cut()
                until(lambda:d.waiting_for_board())
                assert d.sequence['next_index']==2 and p.x['REMAINING']=='0' and not p.armed
                assert any(c.startswith('DRETURN ') for c in wire.writes) and d.data['CLAMP_MASK']=='0'
                w.close();wire.close();print('Operator cut during Fast return passed: immediate stroke, no clamps, both finish before next board.');return
            until(lambda:d.sequence and d.sequence['stage']=='WAIT_OPERATOR_CUT')
            assert d.sequence['early_return'] and p.x['PROFILE_ID']=='3'
            assert abs(sup.context().position-w.native_load_target())<.02
            assert not sup.coordinator.material.contact and d.data['CLAMP']=='0'
            assert w._displayed_cut_index==1 and '> Cut 2:' in w.cut_list_display.toPlainText()
            assert d.intervention.pause();flush();until(lambda:d.intervention.paused())
            assert d.intervention.resume_plan()[0]=='returned_operator'
            assert d.intervention.resume();tick();assert d.can_confirm_operator_cut()
            w.refresh_teensy_tabs();app.processEvents()
            assert not w.operator_cut_button.isHidden() and w.operator_cut_button.isEnabled()
            assert w.operator_cut_button.property('earlyReturnAttention') is False
            assert 'Waiting for operator' in w.live_health_label.text()
            output=Path('tmp/ui-operator');output.mkdir(parents=True,exist_ok=True)
            w.grab().save(str(output/'waiting-returned.png'))
            # No cleanup push or cycle occurs while waiting at Load.
            count=len(wire.writes);strokes=wire.strokes;tick(181000)
            assert wire.strokes==strokes and not p.armed
            assert not any(c.startswith(('XMOVE','DCUT','DOPCUT','DARM')) for c in wire.writes[count:])
            # Loading the next board too soon blocks the explicit cut gesture.
            records(wire.exchange('@AUTO_SENSOR 0'));records(wire.exchange('@PIN 21 0'));tick()
            assert not d.can_confirm_operator_cut() and not d.confirm_operator_cut()
            records(wire.exchange('@PIN 21 1'));tick()
            assert d.can_confirm_operator_cut();w.operator_cut_button.click();flush()
            until(lambda:d.waiting_for_board())
            assert d.sequence['next_index']==2 and w._displayed_cut_index==2
            assert '> Cut 3:' in w.cut_list_display.toPlainText()
            assert wire.strokes==strokes+1 and d.data['CLAMP']=='0'
            assert len([c for c in wire.writes if c.startswith('DOPCUT ')])==2
            assert not any(c.startswith('XMOVE') for c in wire.writes[count:])
            # Continue explicitly acquires a new board, without repeating cuts.
            acquire();until(lambda:d.sequence is None)
            assert wire.strokes==5 and w._displayed_cut_index==3
            assert tuple(w.cut_list)==original and w.current_cut_index==0
            assert d.progress_index==3 and '> Cut' not in w.cut_list_display.toPlainText()
            assert d.message.startswith('Unloaded dry list complete')
            assert d.data['CLAMP']=='0' and d.data['SAW']=='0' and d.data['TRIGGER']=='0'
            # Search + first truing stay Gentle. Later feed is Normal; Load Fast.
            for stage,x in seen:
                if x['MOVE_KIND']=='EDGE':assert x['PROFILE_ID']=='1'
            assert d.owner.cut_history.flush()
            with w.cut_history.path.open(newline='',encoding='utf-8') as stream:history=list(csv.DictReader(stream))
            assert [float(r['cut_length_in']) for r in history if r['cut_type']=='cut']==[142,2,40]
            assert sum(r['cut_type']=='truing' for r in history)==2
            # Stop during an operator pause revokes the pending cut entirely.
            records(wire.exchange('@AUTO_SENSOR 0'));w.load_cut_list_lines(['142 stop me'])
            acquire();until(lambda:d.sequence and d.sequence['stage']=='WAIT_OPERATOR_CUT')
            d.stop();flush();tick();count=len(wire.writes)
            assert not d.confirm_operator_cut() and d.sequence is None
            for _ in range(10):tick()
            assert not any(c.startswith(('DOPCUT','DARM','XLOAD','XMOVE')) for c in wire.writes[count:])
            w.close()
        wire.close()
    print('Operator-return actual-sketch test passed: Gentle acquisition/truing, Normal feed, Fast return, stay for fitting cut, explicit no-clamp stroke, next-board continuation, highlight and Stop.')


if __name__=='__main__':
    executable=Path(sys.argv[1]) if len(sys.argv)>1 else Path('tmp/firmware-tests/dry_run_server.exe')
    run(executable);run(executable,overlap=True)
