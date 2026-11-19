"""Actual Qt HMI / actual controller sketch; mocked GPIO, no serial ports."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys,tempfile
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
from PyQt6.QtCore import QSettings,QTimer
from PyQt6.QtWidgets import QApplication
import main
from controller_backends import TEENSY_CARRIAGE
from automation_supervision import Geometry,Clamp,Span,Material,Context,assess_cut_holding,assess_manual_cycle
from test_native_dry_run import Sketch


def policies():
 g=Geometry(True,(Clamp('main',Span(8.75,9.75)),Clamp('outfeed',Span(-12.5,-11.5),'cut_piece',True,True,2)),0,16.75,0,1,.5)
 c=Context(g,Material(Span(-34,7),'estimated',True),7,reference_known=True,holding_channels=(1,2))
 assert assess_cut_holding(c).permitted_clamps==('outfeed',)
 assert not assess_cut_holding(replace(c,holding_channels=(1,))).proceeds
 assert not assess_cut_holding(replace(c,material=Material(Span(-5,7),'estimated',True))).proceeds
 assert assess_cut_holding(replace(c,position=40,material=Material(Span(-34,40),'estimated',True))).permitted_clamps==('main','outfeed')
 manual=replace(c,fresh=True,door_closed=True,saw_up=True,trigger_off=True,carriage_idle=True,fault_free=True)
 assert not assess_manual_cycle(manual).proceeds
 assert assess_manual_cycle(replace(manual,held_channels=(2,))).permitted_clamps==('outfeed',)


def run(exe,legacy=False,old_return=False):
 app=QApplication.instance() or QApplication([])
 with tempfile.TemporaryDirectory() as folder:
  with patch.object(main,'QSettings',lambda *a,**k:QSettings(folder+'/settings.ini',QSettings.Format.IniFormat)),patch.object(main,'get_app_dir',lambda:folder),patch.object(main.updater,'check_for_update',lambda *a,**k:None):
   wire=Sketch(exe)
   with patch('time.monotonic',lambda:wire.now):
    w=main.MinimalHMI()
    for timer in w.findChildren(QTimer):timer.stop()
    w.controller_combo.setCurrentIndex(w.controller_combo.findData(TEENSY_CARRIAGE))
    w.ser=wire;w.set_controls_enabled(True);p=w.carriage_tab;d=w.dry_run;sup=d.supervision
    mask_seen=set();return_overlap=[]
    def records(lines):
     for line in lines:
      if old_return and line.startswith('BENCH_HELLO,'):line=line.replace('FW:0.27.0','FW:0.26.0').replace('CARRIAGE_V20','CARRIAGE_V19').replace(',RECOVERY:COUNTED_STOP_V1','').replace('FW:0.26.0','FW:0.25.0').replace('CARRIAGE_V19','CARRIAGE_V18').replace(',AUTO_RETURN:CLAMPED_LAST_CUT_V1','')
      if legacy and line.startswith('BENCH_HELLO,'):line=line.replace('FW:0.27.0','FW:0.26.0').replace('CARRIAGE_V20','CARRIAGE_V19').replace(',RECOVERY:COUNTED_STOP_V1','').replace('FW:0.26.0','FW:0.23.0').replace('CARRIAGE_V19','CARRIAGE_V17').replace(',AUTO_RETURN:CLAMPED_LAST_CUT_V1','').replace('FW:0.24.0','FW:0.23.0').replace('FW:0.25.0','FW:0.23.0').replace('CARRIAGE_V18','CARRIAGE_V17').replace(',SECOND_CLAMP:D18_MASK_V1','').replace(',FEED:CONTINUOUS_ACQUIRE_V1','').replace(',PARALLEL_RETURN:UNPLUGGED_OPERATOR_V1','')
      w.update_message_log(line)
      assert not p.local_fault,(p.local_fault,line)
      if line.startswith('BENCH_DRY,') and d.data.get('CYCLE')=='1' and d.data.get('STATE')=='SPINUP':mask_seen.add(d.data['CLAMP_MASK'])
      if (p.x.get('RETURN_AUTO')=='1' and p.x.get('ARMED')=='1' and int(p.x.get('REMAINING','0'))>0 and
          d.data.get('SAW')=='1' and d.data.get('SECOND_CLAMP')=='1' and d.data.get('MAIN_CLAMP')=='0'):
       return_overlap.append(int(p.x['REMAINING']))
    def flush():
     for _ in range(100):
      if not wire.commands:return
      records(wire.exchange(wire.commands.popleft()))
     raise AssertionError('command loop')
    def tick():
     flush();records(wire.exchange('@TICK 100'));p.tick();d.tick();flush()
     assert not p.local_fault and not d.local_fault,(p.local_fault,d.local_fault,d.message,wire.writes[-12:])
    def until(test):
     for _ in range(1800):
      if test():return
      tick()
     raise AssertionError((d.sequence,d.data,w.direct_controls.intent,d.message,wire.writes[-12:]))
    records(wire.initial);tick()
    assert p.compatible and d.compatible and d.second_supported is not legacy
    assert not sup.second_requested() and not sup.second_enabled.isChecked()
    assert d.data.get('SECOND_ENABLED')=='0' and d.data.get('SECOND_CLAMP')=='0'
    w.manual_pneumatics.refresh()
    assert not w.manual_pneumatics.buttons['second_engage'].isEnabled()
    assert not w.manual_pneumatics.request('second_engage') and not w.send_command('DCLAMP2 1')
    assert w.auto_second_clamp_label.text()=='DISABLED' and not wire.writes
    original=dict(d.data)
    if not legacy:
     d.data.update(SECOND_CLAMP='1',SECOND_ENABLED='1',CLAMP='1',CLAMP_MASK='2')
     w.refresh_teensy_tabs();w.manual_pneumatics.refresh()
     assert w.auto_second_clamp_label.text()=='ON COMMANDED' and w.manual_pneumatics.labels['second'].text()=='ON commanded'
     d.data=original;w.refresh_teensy_tabs()
    # Existing settings gain no silent enable; both saved footprint and protocol are required.
    for key,value in dict(main_near=8.75,main_far=9.75,front_offset=0,rear_extent=16.75,keepout=1,margin=.5,max_clear_push=160).items():sup.fields[key].setValue(value)
    assert sup.save()
    if legacy:
     sup.second_enabled.setChecked(True);assert not sup.save()
     sup.fields['outfeed_near'].setValue(11.5);sup.fields['outfeed_far'].setValue(12.5);assert sup.save()
     d.consent.setChecked(True);assert not d.configure()
     assert not any(c.startswith(('DSET','DCLAMP2','DCUTM')) for c in wire.writes)
     w.close();wire.close();print('Second clamp legacy capability lockout passed');return
    w.homing_speed.setValue(1200);w.homing_accel.setValue(1500);w.save_homing_settings()
    flush();tick()
    assert w.home_motor();flush();until(lambda:w.direct_controls.intent is None)
    for profile,rate,accel in ((1,600,600),(2,3000,1500),(3,3500,2000)):
     assert p.edit_profile(profile,rate,accel);flush();tick()
    for key in ('board.settle','main.engage_delay','main.engage_settle','main.release_delay','main.release_clearance','outfeed.engage_delay','outfeed.engage_settle','outfeed.release_delay','outfeed.release_clearance','trigger.spinup'):
     w.cylinder_timing.fields[key].setValue(100)
    w.cylinder_timing.fields['trigger.spinup'].setValue(300)
    w.cylinder_timing.fields['outfeed.engage_delay'].setValue(60000) # unused future drafts cannot block main-only use
    assert w.manual_pneumatics.request('engage');flush();until(lambda:d.data.get('STATE')=='CLAMPED' and not w.direct_controls.intent)
    assert len(d.loaded)==20 and d.loaded[15]==0 and d.data['MAIN_CLAMP']=='1' and d.data['SECOND_CLAMP']=='0'
    assert w.manual_pneumatics.request('release');flush();until(lambda:d.data.get('STATE')=='READY' and not w.direct_controls.intent)
    d.stop();flush();tick()
    w.cylinder_timing.fields['outfeed.engage_delay'].setValue(100)
    sup.second_enabled.setChecked(True)
    assert not sup.save() # no measured pad yet
    sup.fields['outfeed_near'].setValue(11.5);sup.fields['outfeed_far'].setValue(12.5);assert sup.save()
    assert d.data['SECOND_ENABLED']=='0' # saving dimensions never commands hardware
    assert w.manual_pneumatics.request('second_engage');flush();until(lambda:d.data.get('STATE')=='CLAMPED' and not w.direct_controls.intent)
    assert d.data['SECOND_ENABLED']=='1' and d.data['SECOND_CLAMP']=='1' and d.data['MAIN_CLAMP']=='0'
    assert not w.direct_controls.can_motion('jog') and not w.send_command('XARM 1')
    assert w.manual_pneumatics.request('second_release');flush();until(lambda:d.data.get('STATE')=='READY' and not w.direct_controls.intent)
    assert d.data['CLAMP_MASK']=='0'
    assert w.manual_pneumatics.request('second_engage');flush();until(lambda:d.data.get('STATE')=='CLAMPED' and not w.direct_controls.intent)
    d.stop();flush();until(lambda:d.data.get('RELEASE_READY')=='1')
    w.manual_pneumatics.refresh();assert not w.manual_pneumatics.recover_release.isHidden()
    assert d.request('recover_release');flush();tick();assert d.data['CLAMP_MASK']=='0'
    assert w.manual_pneumatics.request('second_engage');flush();until(lambda:d.data.get('STATE')=='CLAMPED' and not w.direct_controls.intent)
    # Explicitly held second clamp is retained through a Manual main+outfeed cycle.
    assert w.manual_pneumatics.request('cycle');flush();until(lambda:wire.strokes==1 and d.data.get('STATE')=='READY' and not w.direct_controls.intent)
    assert '3' in mask_seen and d.data['CLAMP_MASK']=='0'
    d.stop();flush();tick()
    assert w.set_length(27);flush();until(lambda:w.direct_controls.intent is None)
    w.load_cut_list_lines(['14 outfeed-only']);w.kerf_input.setValue(.12)
    # Save reference signature after changing kerf; no new physical measurements.
    assert sup.save();w.repeat_pattern.setChecked(False);w.clear_at_list_end.setChecked(False)
    assert w.start_auto_cycle();flush();until(lambda:d.sequence and d.sequence['stage']=='SEARCH')
    records(wire.exchange('@PIN 21 0'));until(lambda:d.sequence and d.sequence['stage']=='MOVE')
    records(wire.exchange('@AUTO_SENSOR 1'))
    if not old_return:
     until(lambda:bool(return_overlap))
     assert d.sequence['stage']=='RETURN_CUT_WAIT'
     assert d.intervention.pause() and d.intervention.after_cut
     until(lambda:d.intervention.paused())
     assert p.x['REMAINING']=='0' and not p.armed and d.data['CLAMP']=='0' and wire.strokes==3
     assert d.intervention.resume_plan()[0]=='board_done'
     assert d.intervention.resume();flush()
    until(lambda:d.sequence is None)
    assert wire.strokes==3 and '1' in mask_seen and '2' in mask_seen,(wire.strokes,mask_seen,d.message,d.data,wire.writes[-30:])
    assert any(c.startswith(('DCUTM ','DCUTRET ')) and c.split()[3]=='2' for c in wire.writes)
    assert bool(return_overlap) is not old_return
    assert any(c.startswith('DCUTRET ') for c in wire.writes) is not old_return
    assert not any(c.startswith('DOPCUT ') for c in wire.writes)
    assert d.data['CLAMP_MASK']=='0' and not p.armed
    w.close();app.processEvents()
   wire.close()
 print('Second clamp HMI/sketch passed: default disabled, measured enable, independent manual controls, both-clamp cycle, outfeed-only Auto and released return')


if __name__=='__main__':
 policies();exe=Path(sys.argv[1]) if len(sys.argv)>1 else Path('tmp/firmware-tests/dry_run_server.exe')
 run(exe);run(exe,old_return=True);run(exe,legacy=True)
