"""Saved native defaults survive old RAM readback and load before explicit motion."""
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

EXPECTED={1:(600,600),2:(2500,900),3:(3500,2000)}

def run(exe,drop_ack=False):
 app=QApplication.instance() or QApplication([])
 with tempfile.TemporaryDirectory() as folder:
  settings=QSettings(folder+'/settings.ini',QSettings.Format.IniFormat);settings.setValue('fast_speed',4321)
  with patch.object(main,'QSettings',lambda *a,**k:settings),patch.object(main,'get_app_dir',lambda:folder),patch.object(main.updater,'check_for_update',lambda *a,**k:None):
   wire=Sketch(exe)
   with patch('time.monotonic',lambda:wire.now):
    w=main.MinimalHMI()
    for timer in w.findChildren(QTimer):timer.stop()
    w.controller_combo.setCurrentIndex(w.controller_combo.findData(TEENSY_CARRIAGE))
    assert w.saved_motion_profiles()==EXPECTED
    assert {i:tuple(int(v.value()) for v in fields) for i,fields in w.profile_setting_widgets().items()}==EXPECTED
    w.ser=wire;w.set_controls_enabled(True);p=w.carriage_tab;d=w.dry_run
    def records(lines):
     for line in lines:
      if drop_ack and p.profile_pending and line.startswith('BENCH_X,') and 'PROFILE_RATE1:600' in line:
       # An old but otherwise consistent readback cannot acknowledge the write.
       line=line.replace('PROFILE_RATE1:600','PROFILE_RATE1:150').replace('PROFILE_ACCEL1:600','PROFILE_ACCEL1:200').replace('RATE_PPS:600','RATE_PPS:150').replace('ACCEL_PPS2:600','ACCEL_PPS2:200')
      w.update_message_log(line)
    def flush():
     for _ in range(100):
      if not wire.commands:return
      records(wire.exchange(wire.commands.popleft()))
     raise AssertionError('command loop')
    def tick():
     flush();records(wire.exchange('@TICK 100'));p.tick();d.tick();flush()
    def until(check):
     for _ in range(1800):
      if check():return
      tick()
     raise AssertionError((p.local_fault,d.local_fault,w.direct_controls.intent,wire.writes[-15:]))
    records(wire.initial);tick()
    assert not wire.writes and p.profile_values[1]==(150,200)
    assert {i:tuple(int(v.value()) for v in fields) for i,fields in w.profile_setting_widgets().items()}==EXPECTED
    assert w.home_motor();flush();until(lambda:w.direct_controls.intent is None)
    assert not p.local_fault and p.x['POS_KNOWN']=='1'
    start=len(wire.writes);assert w.set_length(159);flush()
    until(lambda:w.direct_controls.intent is None)
    commands=wire.writes[start:]
    if drop_ack:
     assert p.local_fault=='Profile acknowledgment timed out',p.local_fault
     assert not any(c.startswith(('XMOVE','XARM 1')) for c in commands)
     assert p.x['ARMED']=='0' and p.profile_pending is None
     assert not any(c.startswith(('XPROFILE 2','XPROFILE 3')) for c in commands)
    else:
     assert not p.local_fault and not d.local_fault,(p.local_fault,d.local_fault)
     assert all(p.profile_values[k]==v for k,v in EXPECTED.items())
     for i,(rate,accel) in EXPECTED.items():assert commands.index(f'XPROFILE {i} {rate} {accel}')<commands.index('XARM 1')
     assert p.x['RATE_PPS']=='2500' and p.x['ACCEL_PPS2']=='900'
     w.settings_profile_combo.setCurrentIndex(w.settings_profile_combo.findData('NORMAL'))
     w.norm_speed.setValue(2600);w.norm_accel.setValue(950)
     assert w.apply_current_profile_params();flush();tick()
     assert w.saved_motion_profiles()[2]==(2600,950)
    w.close();app.processEvents()
    assert int(settings.value('fast_speed'))==4321 # archived simulation settings are separate
    if not drop_ack:
     other=main.MinimalHMI()
     for timer in other.findChildren(QTimer):timer.stop()
     assert other.norm_speed.value()==2600 and other.norm_accel.value()==950
     assert other.gentle_speed.value()==600 and other.fast_accel.value()==2000
     other.close();app.processEvents()
   wire.close()
 print(f'Startup profiles passed: defaults, non-actuating connect, ACK before motion, persistence; dropped_ack={drop_ack}')

if __name__=='__main__':
 exe=Path(sys.argv[1]) if len(sys.argv)>1 else Path('tmp/firmware-tests/dry_run_server.exe')
 run(exe);run(exe,drop_ack=True)
