"""Resume interrupted acquisition, truing and feed without guessing a cut DONE."""
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
                assert not p.local_fault and not d.local_fault,(p.local_fault,d.local_fault,d.message)
            def until(condition):
                for _ in range(1800):
                    if condition():return
                    tick()
                raise AssertionError((d.sequence,d.intervention.checkpoint,d.message,p.x))
            def stage(name):return bool(d.sequence and d.sequence['stage']==name)
            records(wire.initial);tick();assert w.home_motor();flush();until(lambda:w.direct_controls.intent is None)
            for profile in (1,2,3):assert p.edit_profile(profile,600,600);flush();tick()
            sup=d.supervision
            for key,value in dict(main_near=8.75,main_far=9.75,front_offset=0,rear_extent=16.75,
                                  keepout=1,margin=.5,max_clear_push=160).items():sup.fields[key].setValue(value)
            assert sup.save();w.kerf_input.setValue(.12);w.load_cut_list_lines(['20 first','20 second'])
            assert w.start_auto_cycle();flush();until(lambda:stage('SEARCH'))
            tick(400);assert d.intervention.pause();flush();until(lambda:d.intervention.paused())
            assert wire.strokes==0 and d.sequence['next_index']==0
            w.auto_modes.setCurrentIndex(1);assert d.sequence['semi']
            w.auto_modes.setCurrentIndex(0);assert not d.sequence['semi']
            old_search=int(d.sequence['edge_command'].split()[1]);assert d.intervention.resume();flush();until(lambda:stage('SEARCH'))
            assert int(d.sequence['edge_command'].split()[1])<old_search
            records(wire.exchange('@PIN 21 0'));until(lambda:stage('MOVE'));records(wire.exchange('@AUTO_SENSOR 1'))
            tick(400);target=int(p.x['TARGET_OFFSET']);assert int(p.x['REMAINING'])>0
            assert d.intervention.pause();flush();until(lambda:d.intervention.paused())
            assert sup.coordinator.material.stock.near>0 # not yet at true-up plane
            assert d.intervention.resume_plan()[0]=='position'
            assert d.intervention.resume();flush();until(lambda:stage('FEED_ARM'))
            assert p.x['PROFILE_ID']=='1'
            until(lambda:stage('MOVE') and d.sequence['index']==0)
            assert wire.strokes==1 # exactly one completed truing stroke
            tick(400);assert int(p.x['REMAINING'])>0;target=int(p.x['TARGET_OFFSET'])
            assert d.intervention.pause();flush();until(lambda:d.intervention.paused())
            assert d.progress_index==0 and wire.strokes==1
            assert d.intervention.resume_plan()[0]=='position'
            assert d.intervention.resume();flush();until(lambda:stage('SAW_WAIT'))
            assert int(p.x['HOME_OFFSET'])==target
            # A sensor discrepancy disables Resume until it is reconciled; no
            # automatic motion is issued when the signal changes back.
            assert d.intervention.pause();until(lambda:d.intervention.paused())
            count=len(wire.writes);records(wire.exchange('@AUTO_SENSOR 0'));tick()
            assert d.intervention.resume_plan() is None
            for _ in range(5):tick()
            assert not any(c.startswith(('XMOVE','XARM 1','DCUT')) for c in wire.writes[count:])
            # Cancel revokes both the saved sequence and any pending action.
            d.cancel_cycle();flush();tick();assert d.sequence is None and d.intervention.checkpoint is None
            assert not d.intervention.resume();w.close()
        wire.close()
    print('Pause checkpoints passed: interrupted search/truing/feed, same pending target, sensor reconciliation and Cancel revocation.')


if __name__=='__main__':run(Path(sys.argv[1]) if len(sys.argv)>1 else Path('tmp/firmware-tests/dry_run_server.exe'))
