"""Qt offline workbench: no commands, settings/model mutation or fake live state."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from PyQt6.QtCore import QSettings, QTimer
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont, QFontDatabase
import main
from controller_backends import TEENSY_CARRIAGE


def run():
    app = QApplication.instance() or QApplication([])
    if os.name == 'nt':
        for font in ('segoeui.ttf', 'seguisb.ttf', 'consola.ttf'):
            QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+font)
        app.setFont(QFont('Segoe UI', 10))
    with tempfile.TemporaryDirectory() as folder:
        main.QSettings = lambda *a, **k: QSettings(folder+'/settings.ini', QSettings.Format.IniFormat)
        main.updater.check_for_update = lambda *a, **k: None
        w = main.MinimalHMI()
        for timer in w.findChildren(QTimer): timer.stop()
        w.controller_combo.setCurrentIndex(w.controller_combo.findData(TEENSY_CARRIAGE))
        bench = w.machine_workbench
        coordinator = w.dry_run.supervision.coordinator
        before = (coordinator.geometry, coordinator.material, coordinator.paused, list(coordinator.events))
        settings = {key:w.settings.value(key) for key in w.settings.allKeys()}
        with patch.object(w, 'send_command', side_effect=AssertionError('Preview sent a hardware command')):
            assert w.full_auto_tab.isEnabled() and w.full_auto_legacy.isEnabled()
            assert not w.fa_start_cycle_button.isEnabled()
            assert not w.fa_stop_button.isEnabled()
            for index, scenario in enumerate(bench.scenarios):
                bench.scenario.setCurrentIndex(index)
                bench.refresh()
                assert bench.current_decision.code == scenario.expected, scenario.title
            bench.scenario.setCurrentIndex(0)
            bench.position.setValue(8)
            assert not bench.current_decision.proceeds
            bench.load_scenario()
            w.cut_list = [(0,12,False),(0,20,False),(0,1,False)]
            bench.forecast()
            assert bench.lookahead.rowCount() == 2
            bench.source.setCurrentIndex(0)
            assert not bench.current_context.fresh
            assert bench.current_context.position is None
            assert bench.current_decision.code == 'STATE_UNKNOWN'
            assert bench.lookahead.rowCount() == 0
            assert all('checklist' not in bench.pages.tabText(i).lower() for i in range(bench.pages.count()))
            path = Path(folder)/'report.json'
            assert bench.export_report(path=path)
            report = json.loads(path.read_text())
            assert report['checklist']=={}
            assert not report['geometry']['verified']
            assert report['preview_source'] == 'live readback'
            assert (coordinator.geometry, coordinator.material, coordinator.paused, list(coordinator.events)) == before
            assert {key:w.settings.value(key) for key in w.settings.allKeys()} == settings
            assert bench.export_report(path=Path(folder)/'missing'/'report.json') is False
            w.cut_history.error = 'Cut history test: file is locked'
            w.refresh_cut_history_status()
            assert not w.cut_history_warning.isHidden()
            assert 'file is locked' in w.cut_history_warning.text()
            w.cut_history.error = ''; w.refresh_cut_history_status()
            assert w.cut_history_warning.isHidden()
            bench.source.setCurrentIndex(1)
            bench.pages.setCurrentIndex(1)
            w.tabs.setCurrentWidget(w.full_auto_tab)
            w.resize(1440,1000); w.show(); app.processEvents()
            output = Path('tmp/ui-workbench'); output.mkdir(parents=True, exist_ok=True)
            w.grab().save(str(output/'normal.png'))
            bench.scenario.setCurrentIndex(1); app.processEvents()
            w.grab().save(str(output/'overlap.png'))
        w.close()
    print('Offline workbench: scenarios, policy lookahead, unknown live state, export and non-actuation checks passed.')


if __name__ == '__main__': run()
