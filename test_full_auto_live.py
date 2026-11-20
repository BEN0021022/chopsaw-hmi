"""Actual sketch -> Full Auto view and shared Start/Stop; no physical ports."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys,tempfile
from pathlib import Path
from unittest.mock import patch
from PyQt6.QtCore import QSettings,QTimer
from PyQt6.QtWidgets import QApplication,QLabel
from PyQt6.QtGui import QFont,QFontDatabase
import main
from controller_backends import TEENSY_CARRIAGE
from full_auto_live import refresh_full_auto
from test_native_dry_run import Sketch


def run(exe):
 app=QApplication.instance() or QApplication([])
 if os.name=='nt':
  QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf')
  QFontDatabase.addApplicationFont('C:/Windows/Fonts/consola.ttf')
  app.setFont(QFont('Segoe UI',10))
 with tempfile.TemporaryDirectory() as folder:
  with patch.object(main,'QSettings',lambda *a,**k:QSettings(folder+'/prefs.ini',QSettings.Format.IniFormat)),patch.object(main,'get_app_dir',lambda:folder),patch.object(main.updater,'check_for_update',lambda:None):
   wire=Sketch(exe)
   with patch('time.monotonic',lambda:wire.now):
    w=main.MinimalHMI()
    for timer in w.findChildren(QTimer):timer.stop()
    w.controller_combo.setCurrentIndex(w.controller_combo.findData(TEENSY_CARRIAGE))
    assert w.machine_workbench.pages.tabText(0)=='Machine / live cycle'
    assert not any('Fence Clamp' in x.text() for x in w.full_auto_tab.findChildren(QLabel))
    assert not any(key.startswith('fence.') for key in w.cylinder_timing.fields)
    assert len(w.saw_sim.clamps)==2 and w.saw_sim.carriage is None
    assert not w.fa_start_cycle_button.isEnabled() and not w.fa_stop_button.isEnabled()
    w.ser=wire;w.set_controls_enabled(True);p=w.carriage_tab;d=w.dry_run;sup=d.supervision
    seen=set();positions=[]
    def records(lines):
     for line in lines:w.update_message_log(line)
    def flush():
     for _ in range(100):
      if not wire.commands:return
      records(wire.exchange(wire.commands.popleft()))
     raise AssertionError('command loop')
    def tick(ms=100):
     flush();records(wire.exchange(f'@TICK {ms}'));p.tick();d.tick();flush();refresh_full_auto(w)
     c=sup.context()
     if c.fresh and c.reference_known:
      assert abs(w.saw_sim.carriage-c.position)<1e-9
      positions.append(c.position)
     if d.fresh():
      assert w.saw_sim.clamps==tuple(d.data[key]=='1' for key in ('MAIN_CLAMP','SECOND_CLAMP'))
      for key in ('MAIN_CLAMP','SECOND_CLAMP','SAW','TRIGGER'):
       if d.data[key]=='1':seen.add(key)
      if p.x.get('RETURN_AUTO')=='1' and p.x.get('REMAINING')!='0' and d.data['CYCLE']=='1':seen.add('overlap')
     assert w.fa_start_cycle_button.isEnabled()==w.start_cycle_button.isEnabled()
    def until(check):
     for _ in range(2400):
      if check():return
      tick()
     raise AssertionError((d.message,d.sequence,p.x))
    records(wire.initial);tick();assert w.home_motor();flush();until(lambda:w.direct_controls.intent is None)
    for key,value in dict(main_near=8.75,main_far=9.75,front_offset=0,rear_extent=16.75,keepout=1,margin=.5,max_clear_push=160,outfeed_near=10.25,outfeed_far=11.5).items():sup.fields[key].setValue(value)
    sup.second_enabled.setChecked(True);assert sup.save()
    w.kerf_input.setValue(.12);w.board_sensor_location_input.setValue(10.5)
    w.load_cut_list_lines(['20 first','20 second']);w.repeat_pattern.setChecked(False);w.clear_at_list_end.setChecked(False)
    w.tabs.setCurrentWidget(w.full_auto_tab);w.resize(1440,950);w.show();app.processEvents();tick()
    assert w.fa_start_cycle_button.isEnabled() and w.fa_stop_button.isEnabled()
    output=Path('tmp/ui-full-auto');output.mkdir(parents=True,exist_ok=True)
    w.grab().save(str(output/'ready.png'))
    before=len(wire.writes)
    refresh_full_auto(w);w.machine_workbench.refresh();app.processEvents()
    assert len(wire.writes)==before,'Painting/refresh cannot issue commands'
    w.fa_start_cycle_button.click();flush();until(lambda:d.sequence and d.sequence['stage']=='SEARCH')
    assert not w.fa_start_cycle_button.isEnabled() and w.fa_stop_button.isEnabled()
    # Interrupt real simulated search from the new button, then start again.
    tick(300);w.fa_stop_button.click();flush();tick(500)
    assert d.sequence is None and p.x['REMAINING']=='0' and not p.armed
    pulses=wire.pulses;tick(500);assert wire.pulses==pulses
    w.fa_start_cycle_button.click();flush();until(lambda:d.sequence and d.sequence['stage']=='SEARCH')
    records(wire.exchange('@PIN 21 0'));until(lambda:d.sequence and d.sequence['stage']=='MOVE')
    records(wire.exchange('@AUTO_SENSOR 1'))
    until(lambda:'overlap' in seen)
    assert w.saw_sim.board_present and w.saw_sim.clamp_positions==(9.25,-10.875)
    w.grab().save(str(output/'return-during-cut.png'))
    until(lambda:d.sequence is None)
    assert seen=={'MAIN_CLAMP','SECOND_CLAMP','SAW','TRIGGER','overlap'},seen
    assert max(positions)-min(positions)>20 and d.progress_index==2
    # The same page can approve a Semi-Auto cut; interrupting a held clamp
    # retains it and still exposes Stop rather than stranding the operator.
    records(wire.exchange('@AUTO_SENSOR 0'));records(wire.exchange('@PIN 21 1'));tick()
    w.auto_modes.setCurrentIndex(1);tick();w.fa_start_cycle_button.click();flush()
    until(lambda:d.sequence and d.sequence['stage']=='SEARCH')
    records(wire.exchange('@PIN 21 0'));until(lambda:d.sequence and d.sequence['stage']=='MOVE')
    records(wire.exchange('@AUTO_SENSOR 1'))
    until(lambda:d.sequence and d.sequence['stage']=='WAIT_CUT_APPROVAL')
    assert w.fa_operator_cut_button.isEnabled() and not w.fa_operator_cut_button.isHidden()
    w.fa_operator_cut_button.click();flush();until(lambda:d.data['CLAMP']=='1')
    w.fa_stop_button.click();flush();tick(500)
    assert d.sequence is None and not p.armed and d.data['CLAMP']=='1' and d.data['TRIGGER']=='0'
    # Stale telemetry must not leave the old board/carriage/outputs looking live.
    wire.now+=3;p.tick();d.tick();w.refresh_teensy_tabs();refresh_full_auto(w)
    assert w.saw_sim.carriage is None and not w.saw_sim.board_present
    assert w.saw_sim.clamps==(None,None) and w.fa_cyl1_status.text()=='UNKNOWN'
    assert w.fa_saw_position_label.text()=='UNKNOWN' and not w.fa_start_cycle_button.isEnabled()
    assert w.fa_stop_button.isEnabled(),'Stop stays available while serial is connected'
    w.close()
   wire.close()
 print('Full Auto passed: shared Start/Stop, two live clamps, feed/cut/return overlap, Semi-Auto approval, retained-clamp Stop, modeled stock, stale/unknown and non-actuating paint.',flush=True)


if __name__=='__main__':run(Path(sys.argv[1]) if len(sys.argv)>1 else Path('tmp/firmware-tests/dry_run_server.exe'))
