"""Actual app/sketch: door stop on cut two, manual withdrawal and fresh acquisition."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import csv,sys,tempfile
from pathlib import Path
from unittest.mock import patch
from PyQt6.QtCore import QSettings,QTimer
from PyQt6.QtWidgets import QApplication
import main
from controller_backends import TEENSY_CARRIAGE
from test_native_dry_run import Sketch


def run(exe,during_saw=False):
 app=QApplication.instance() or QApplication([])
 with tempfile.TemporaryDirectory() as folder:
  with patch.object(main,'QSettings',lambda *a,**k:QSettings(folder+'/prefs.ini',QSettings.Format.IniFormat)),patch.object(main,'get_app_dir',lambda:folder),patch.object(main.updater,'check_for_update',lambda:None):
   wire=Sketch(exe)
   with patch('time.monotonic',lambda:wire.now):
    w=main.MinimalHMI()
    for timer in w.findChildren(QTimer):timer.stop()
    w.controller_combo.setCurrentIndex(w.controller_combo.findData(TEENSY_CARRIAGE));w.ser=wire;w.set_controls_enabled(True)
    p=w.carriage_tab;d=w.dry_run;sup=d.supervision
    def records(lines):
     for line in lines:w.update_message_log(line)
    def flush():
     for _ in range(100):
      if not wire.commands:return
      records(wire.exchange(wire.commands.popleft()))
     raise AssertionError('command loop')
    def tick(ms=100):
     flush();records(wire.exchange(f'@TICK {ms}'));p.tick();d.tick();flush()
    def stage(name):return bool(d.sequence and d.sequence['stage']==name)
    def until(check):
     for _ in range(2400):
      if check():return
      tick()
     raise AssertionError((d.message,d.sequence,d.intervention.checkpoint,p.x,wire.writes[-15:]))
    def acquire(resume=False):
     assert (d.intervention.resume() if resume else w.start_auto_cycle()),d.message
     flush();until(lambda:stage('SEARCH'));assert p.x['PROFILE_ID']=='1'
     records(wire.exchange('@PIN 21 0'));until(lambda:stage('MOVE'))
     records(wire.exchange('@AUTO_SENSOR 1'))
    records(wire.initial);tick();assert w.home_motor();flush();until(lambda:w.direct_controls.intent is None)
    for key,value in dict(main_near=8.75,main_far=9.75,front_offset=0,rear_extent=16.75,keepout=1,margin=.5,max_clear_push=160).items():sup.fields[key].setValue(value)
    assert sup.save();w.kerf_input.setValue(.12);w.board_sensor_location_input.setValue(10.5)
    w.load_cut_list_lines(['20 first','20 second','20 third']);w.repeat_pattern.setChecked(False);w.clear_at_list_end.setChecked(False)
    acquire()
    if during_saw:until(lambda:d.sequence and d.sequence['index']==1 and d.data.get('SAW')=='1')
    else:until(lambda:stage('MOVE') and d.sequence['index']==1);tick(200)
    assert d.data['DONE']=='2'
    records(wire.exchange('@PIN 29 1'));tick();assert d.intervention.recovering()
    stopped=p.x['HOME_OFFSET'];pulses=wire.pulses;tick(500)
    assert p.x['POS_KNOWN']=='1' and p.x['HOME_OFFSET']==stopped and wire.pulses==pulses
    assert d.sequence['next_index']==1 and d.progress_index==1
    records(wire.exchange('@PIN 29 0'));tick(400)
    if during_saw:
     assert d.data['CLAMP']=='1' and w.auto_release_clamps.isEnabled()
     assert not w.auto_clear_error.isEnabled() and not w.load_button.isEnabled()
     w.auto_release_clamps.click();flush();tick()
    w.auto_clear_error.click();flush();tick(500)
    assert p.x['FAULT']==d.data['FAULT']=='NONE' and not d.local_fault,(p.x,d.data,d.message)
    assert w.load_button.isEnabled() and w.qjog_left_1.isEnabled() and w.auto_cancel_button.isEnabled() and w.cancel_cycle_button.isEnabled()
    assert not w.auto_pause_button.isEnabled() and not w.auto_resume_button.isEnabled()
    assert w.load_position();flush();until(lambda:w.direct_controls.intent is None)
    assert d.intervention.recovering() and d.sequence['next_index']==1
    count=len(wire.writes);records(wire.exchange('@AUTO_SENSOR 0'));tick()
    assert w.auto_resume_button.isEnabled()
    assert not any(c.startswith(('XARM 1','DCUT','XACQUIRE')) for c in wire.writes[count:])
    acquire(resume=True);assert d.sequence['next_index']==1
    until(lambda:d.sequence is None)
    assert d.progress_index==3 and d.data['DONE']=='5' and not p.armed and d.data['CLAMP']=='0'
    assert w.cut_history.flush()
    with w.cut_history.path.open(newline='',encoding='utf-8') as stream:rows=list(csv.DictReader(stream))
    cuts=[row for row in rows if row['cut_type']=='cut']
    assert [int(row['cut_number']) for row in cuts]==[1,2,3],cuts
    assert sum(row['cut_type']=='truing' for row in rows)==2
    # A fault captured after a confirmed DONE advances exactly once.
    d.sequence=dict(stage='SAW_WAIT',index=1,next_index=1,done=4)
    d.intervention.capture_fault('late door readback');d.intervention.observe_fault_completion()
    assert d.sequence['next_index']==2
    d.cancel_cycle();flush();tick();assert d.sequence is None and d.intervention.checkpoint is None
    assert not d.intervention.resume();w.close()
   wire.close()
 print('Fault recovery passed:', 'saw stroke' if during_saw else 'feed', '-> retained position -> manual Load -> Gentle/truing -> cuts 2/3 only',flush=True)


if __name__=='__main__':
 exe=Path(sys.argv[1]) if len(sys.argv)>1 else Path('tmp/firmware-tests/dry_run_server.exe')
 from qt_test_cases import isolated_cases
 isolated_cases(2,lambda i:run(exe,during_saw=i==1),exe)
