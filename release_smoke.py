"""Explicit offline packaging diagnostic; isolated settings and no serial access."""
import hashlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch


def run(window_type, directory):
    from PyQt6.QtCore import QSettings, QTimer
    from PyQt6.QtWidgets import QApplication
    import serial
    import serial.tools.list_ports
    import updater
    from _version import __version__
    folder = Path(directory).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    data = folder / 'isolated-userdata'
    data.mkdir(exist_ok=True)
    namespace = window_type.__init__.__globals__
    settings = lambda *a, **k: QSettings(str(data / 'preferences.ini'), QSettings.Format.IniFormat)
    result = {'version': __version__, 'frozen': bool(getattr(sys, 'frozen', False)), 'checks': {}}
    if result['frozen']:
        result['exe_sha256'] = hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()
    with patch.dict(namespace, QSettings=settings, get_app_dir=lambda: str(data)), \
         patch.object(serial.tools.list_ports, 'comports', lambda: []), \
         patch.object(serial, 'Serial', side_effect=AssertionError('Serial forbidden in release diagnostic')), \
         patch.object(updater, 'check_for_update', lambda *a, **k: None):
        app = QApplication.instance() or QApplication(sys.argv)
        w = window_type()
        w.tabs.setCurrentWidget(w.full_auto_tab)
        w.show()
        def finish():
            try:
                keypad = w.cut_length_keypad
                # Find by widget rather than assuming a layout insertion order.
                from PyQt6.QtWidgets import QGridLayout
                grid = next(layout for layout in keypad.findChildren(QGridLayout)
                            if layout.indexOf(keypad.keys['Back']) >= 0)
                result['checks'] = {
                    'main_window': w.isVisible(),
                    'version_title': f'v{__version__}' in w.windowTitle(),
                    'two_clamps': len(w.saw_sim.clamps) == 2 and not hasattr(w, 'fa_cyl3_status'),
                    'full_auto': w.machine_workbench.pages.tabText(0) == 'Machine / live cycle',
                    'keypad_back_left': grid.getItemPosition(grid.indexOf(keypad.keys['Back']))[:2] == (3, 0),
                    'keypad_decimal_right': grid.getItemPosition(grid.indexOf(keypad.keys['.']))[:2] == (3, 2),
                    'disconnected': not w.is_connected(),
                    'no_auto_action': w.dry_run.sequence is None and w.direct_controls.intent is None,
                    'start_disabled': not w.fa_start_cycle_button.isEnabled(),
                    'updater_present': w.check_updates_btn.text() == 'Check for Updates',
                }
                if os.environ.get('CHOPSAW_RELEASE_NETWORK_TEST') == '1':
                    latest = json.loads(updater._http_get(updater.API_LATEST, 10))
                    result['checks']['github_https'] = bool(latest.get('tag_name'))
                    result['remote_tag'] = latest.get('tag_name')
                w.grab().save(str(folder / 'packaged-window.png'))
                result['passed'] = all(result['checks'].values())
            except Exception as exc:
                result.update(passed=False, error=repr(exc))
            w.close()
            (folder / 'report.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
            app.exit(0 if result.get('passed') else 1)
        QTimer.singleShot(600, finish)
        return app.exec()
