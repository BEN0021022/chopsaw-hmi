"""Exercise touch/keyboard cut-list entry with fake serial, never hardware."""
import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
import main
from controller_backends import TEENSY_CARRIAGE
from test_teensy_carriage import FakeSerial, ready, packet


def run():
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as folder:
        main.QSettings = lambda *a, **k: QSettings(folder + '/settings.ini', QSettings.Format.IniFormat)
        main.updater.check_for_update = lambda *a, **k: None
        w = main.MinimalHMI()
        w.controller_combo.setCurrentIndex(w.controller_combo.findData(TEENSY_CARRIAGE))
        w.ser = FakeSerial()
        wire = w.ser
        w.set_controls_enabled(True)
        p = w.carriage_tab
        p.timer.stop()
        ready(p)
        p.consent.setChecked(True)
        packet(p, ARMED=1, ENA=0, CONFIGURED=1, POS_KNOWN=1, HOME_OFFSET=-14, HOME_STATE='DONE')
        w.resize(1280, 900)
        w.tabs.setCurrentWidget(w.auto_tab)
        w.show()
        app.processEvents()
        popup = w.cut_length_keypad
        editor = w.cut_length_input.lineEdit()
        writes = list(wire.writes)

        def tap_field():
            QTest.mouseClick(editor, Qt.MouseButton.LeftButton)
            app.processEvents()

        def tap_key(key):
            QTest.mouseClick(popup.keys[key], Qt.MouseButton.LeftButton)

        def add():
            QTest.mouseClick(w.add_cut_button, Qt.MouseButton.LeftButton)

        # Optional keypad: ordinary keyboard entry still works with it off.
        assert not w.cut_length_keypad_checkbox.isChecked()
        tap_field()
        assert popup.isHidden()
        editor.selectAll()
        QTest.keyClicks(editor, '12.75')
        add()
        assert [c[1] for c in w.cut_list] == [12.75]
        assert editor.selectedText() == editor.text(), 'Add selects the next keyboard entry'

        QTest.mouseClick(w.cut_length_keypad_checkbox, Qt.MouseButton.LeftButton)
        assert popup.isHidden(), 'Enabling is a preference; tapping the field opens it'
        tap_field()
        for length in ('18.375', '24.5', '.25'):
            assert popup.isVisible() and editor.selectedText() == editor.text()
            for char in length:
                tap_key(char)
            assert abs(w.cut_length_input.value() - float(length)) < 1e-6
            add()
            assert w.cut_list[-1][1] == float(length)
            assert popup.isVisible(), 'Keep open for multiple entries'
            assert editor.selectedText() == editor.text(), 'Next length needs no extra field tap'
        assert [c[1] for c in w.cut_list] == [12.75, 18.375, 24.5, .25]

        # Edits go into the same field; Clear cannot silently add the old value.
        tap_field()
        for key in '7.52': tap_key(key)
        tap_key('Back')
        assert w.cut_length_input.value() == 7.5
        QTest.mouseClick(popup.clear_button, Qt.MouseButton.LeftButton)
        count = len(w.cut_list)
        add()
        assert len(w.cut_list) == count and 'Enter a length from' in popup.hint.text()
        tap_key('0')
        add()
        assert len(w.cut_list) == count
        tap_key('.')
        tap_key('5')
        add()
        assert w.cut_list[-1][1] == .5

        # Physical typing is also allowed while the overlay is open.
        tap_field()
        QTest.keyClicks(editor, '32.125')
        add()
        assert w.cut_list[-1][1] == 32.125
        QTest.mouseClick(popup.close_button, Qt.MouseButton.LeftButton)
        assert popup.isHidden() and w.cut_length_keypad_checkbox.isChecked()
        tap_field()
        assert popup.isVisible()
        w.resize(1400, 1000)
        app.processEvents()
        assert popup.width() <= popup.parentWidget().width()
        assert popup.height() <= popup.parentWidget().height()
        assert popup.geometry().right() < popup.parentWidget().width()
        # Add remains accessible: overlay is confined to the left status column.
        assert not popup.rect().contains(popup.mapFromGlobal(w.add_cut_button.mapToGlobal(w.add_cut_button.rect().center())))
        QTest.mouseClick(w.cut_length_keypad_checkbox, Qt.MouseButton.LeftButton)
        assert popup.isHidden()
        tap_field()
        assert popup.isHidden()
        w.cut_length_keypad_checkbox.setChecked(True)
        tap_field()
        w.tabs.setCurrentWidget(w.legacy_tab)
        w.tabs.setCurrentWidget(w.auto_tab)
        assert popup.isHidden()
        assert wire.writes == writes, 'Cut-list input must never send hardware commands, even when armed'
        w._save_settings()
        assert w.settings.value('cut_length_keypad', type=bool)
        w.close()
        app.processEvents()
        reopened = main.MinimalHMI()
        assert reopened.cut_length_keypad_checkbox.isChecked()
        assert reopened.cut_length_keypad.isHidden(), 'Restoring a preference must not open the keypad'
        reopened.close()
        app.processEvents()
    print('AUTO keypad: repeated touch entry, physical typing, validation, close/toggle, layout and persistence OK')


if __name__ == '__main__':
    run()
