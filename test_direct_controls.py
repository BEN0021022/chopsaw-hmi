"""Actual sketch -> real HMI direct gestures, without consent/arm/setup clicks."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys,tempfile
from pathlib import Path
from unittest.mock import patch
from PyQt6.QtCore import QSettings,QTimer,Qt
from PyQt6.QtGui import QFont,QFontDatabase
from PyQt6.QtTest import QTest
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
            w.ser=wire;w.set_controls_enabled(True)
            p=w.carriage_tab;d=w.dry_run;b=w.direct_controls;panel=w.manual_pneumatics
            def records(lines):
                for line in lines:w.update_message_log(line)
            def flush():
                for _ in range(100):
                    if not wire.commands:return
                    records(wire.exchange(wire.commands.popleft()))
                raise AssertionError('command loop')
            def tick(count=100):
                flush();records(wire.exchange(f'@TICK {count}'));p.tick();d.tick();flush()
                assert not p.local_fault and not d.local_fault,(p.local_fault,d.local_fault,b.message,d.message)
            def until(condition,seconds=180):
                for _ in range(seconds*10):
                    if condition():return
                    tick()
                raise AssertionError((b.intent,b.message,p.x,d.data,wire.writes[-15:]))
            records(wire.initial);tick()
            assert not any(c.startswith(('XARM','DARM','DMANUAL','XHOME','DCUT')) for c in wire.writes)
            sup=d.supervision
            for key,value in dict(main_near=8.75,main_far=9.75,front_offset=0,rear_extent=16.75,
                                  keepout=1,margin=.5,max_clear_push=160).items():
                sup.fields[key].setValue(value)
            assert sup.save() # numeric data only, no verification checkbox
            assert sup.verified.isHidden() and sup.automatic_clear.isHidden()
            assert d.enable_manual_button.isHidden() and w.auto_teensy_setup.isHidden()
            w.tabs.setCurrentWidget(w.legacy_tab);w.resize(1280,900);w.show();w.activateWindow();app.processEvents()
            # Type before Home, but Enter must not queue or start a move.
            assert w.keypad.isEnabled() and not w.keypad.enter_button.isEnabled()
            QTest.keyClicks(w.keypad.display,'150');QTest.keyClick(w.keypad.display,Qt.Key.Key_Return)
            assert b.intent is None
            assert w.home_motor();flush();until(lambda:p.x.get('POS_KNOWN')=='1' and b.intent is None)
            assert 'XCONFIG 0 1' in wire.writes and 'XHOME 20594' in wire.writes
            assert not p.armed and d.data['ARMED']=='0'
            QTest.keyClick(w.keypad.display,Qt.Key.Key_Return);flush();until(lambda:b.intent is None)
            assert abs((160.5+int(p.x['HOME_OFFSET'])/127.12)-150)<.01
            assert not p.armed
            # Clamp/release directly. Data entry remains usable while clamped,
            # but neither typing nor Enter can move the carriage under the clamp.
            assert panel.buttons['engage'].isEnabled();panel.buttons['engage'].click();flush()
            until(lambda:d.data['STATE']=='CLAMPED')
            assert d.data['CLAMP']=='1' and not w.keypad.enter_button.isEnabled()
            QTest.keyClicks(w.keypad.display,'140');QTest.keyClick(w.keypad.display,Qt.Key.Key_Return)
            count=len([c for c in wire.writes if c.startswith('XMOVE ')])
            assert panel.buttons['release'].isEnabled();panel.buttons['release'].click();flush()
            until(lambda:d.data['STATE']=='READY')
            assert len([c for c in wire.writes if c.startswith('XMOVE ')])==count
            QTest.keyClick(w.keypad.display,Qt.Key.Key_Return);flush();until(lambda:b.intent is None)
            assert abs((160.5+int(p.x['HOME_OFFSET'])/127.12)-140)<.01
            assert w.auto_jog(-1);flush();until(lambda:b.intent is None)
            assert abs((160.5+int(p.x['HOME_OFFSET'])/127.12)-139)<.02
            assert b.request('load',140);flush();until(lambda:b.intent is None)
            assert abs((160.5+int(p.x['HOME_OFFSET'])/127.12)-140)<.01
            # Independent travel from OFF loads timings/enters Manual itself.
            assert panel.buttons['lower'].isEnabled();panel.buttons['lower'].click();flush()
            until(lambda:d.data['STATE']=='DOWN')
            assert d.data['CLAMP']=='0' and not panel.buttons['engage'].isEnabled()
            assert panel.buttons['up'].isEnabled();panel.buttons['up'].click();flush()
            until(lambda:d.data['STATE']=='READY')
            assert d.data['CLAMP']=='0'
            # Hold trigger directly; release before preparation prevents late press.
            d.stop();flush();tick();press=panel.buttons['press'];panel.refresh()
            QTest.mousePress(press,Qt.MouseButton.LeftButton);QTest.mouseRelease(press,Qt.MouseButton.LeftButton)
            flush();tick();assert b.intent is None and d.data['TRIGGER']=='0'
            panel.refresh();QTest.mousePress(press,Qt.MouseButton.LeftButton);flush()
            until(lambda:d.data['TRIGGER']=='1')
            for _ in range(15):tick()
            QTest.mouseRelease(press,Qt.MouseButton.LeftButton);flush();tick();assert d.data['TRIGGER']=='0'
            # Manual Cycle requires no stock-registration gesture; collision and
            # machine-state guards remain, and no material location is fabricated.
            assert not sup.coordinator.material.located
            assert panel.cycle_button.isEnabled();done=int(d.data['DONE']);panel.cycle_button.click();flush()
            until(lambda:int(d.data['DONE'])==done+1)
            assert not sup.coordinator.material.located and d.data['CLAMP']=='0'
            # Stop during automatic preparation revokes the sole pending target.
            assert w.set_length(130);d.stop();flush();tick();start=len(wire.writes)
            for _ in range(10):tick()
            assert b.intent is None and not any(c.startswith(('XARM 1','XMOVE','DMANUAL','DCUT')) for c in wire.writes[start:])
            # All simple controls survive a normal mode handoff; no enable UI.
            assert w.keypad.isEnabled() and w.keypad.enter_button.isEnabled()
            output=Path('tmp/ui-direct');output.mkdir(parents=True,exist_ok=True)
            app.processEvents();w.grab().save(str(output/'manual.png'))
            w.tabs.setCurrentWidget(w.auto_tab);app.processEvents();w.grab().save(str(output/'auto.png'))
            # Guard loss during preparation revokes the single pending gesture.
            assert w.set_length(125)
            records(wire.exchange('@PIN 29 1'));p.tick();d.tick();flush()
            start=len(wire.writes)
            for _ in range(10):
                records(wire.exchange('@TICK 100'));p.tick();d.tick();flush()
            assert b.intent is None
            assert not any(c.startswith(('XARM 1','XMOVE','DMANUAL','DCUT')) for c in wire.writes[start:])
            w.close()
        wire.close()
    print('Direct controls actual-sketch test passed: Home, physical keypad, clamp/release, unclamped travel, held trigger, Manual Cycle, mode handoff and Stop cancellation.')


if __name__=='__main__':run(Path(sys.argv[1]) if len(sys.argv)>1 else Path('tmp/firmware-tests/dry_run_server.exe'))
