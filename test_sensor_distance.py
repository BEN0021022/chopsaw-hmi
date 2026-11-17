"""One saved laser distance drives geometry, migration and reference invalidation."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PyQt6.QtCore import QSettings,QTimer
from PyQt6.QtWidgets import QApplication,QLabel
import main
from automation_supervision import Span
from controller_backends import TEENSY_CARRIAGE


class SensorDistanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_legacy_migration_edit_and_restart_use_single_field(self):
        with tempfile.TemporaryDirectory() as folder:
            settings=QSettings(folder+'/settings.ini',QSettings.Format.IniFormat)
            settings.setValue('controller_mode',TEENSY_CARRIAGE)
            settings.setValue('board_sensor_location',10.5);settings.setValue('kerf',.12)
            legacy=dict(main_near=8.75,main_far=9.75,front_offset=0,rear_extent=16.75,keepout=1,margin=.5,
                        sensor_near=10.8,sensor_far=10.8,max_clear_push=160,verified=True,automatic_clearance=True,
                        second_enabled=False,reference_signature=[10.8,.12,'sensor_plus_kerf_v1'])
            settings.setValue('supervision/geometry_v1',json.dumps(legacy))
            with patch.object(main,'QSettings',lambda *a,**k:settings),patch.object(main,'get_app_dir',lambda:folder),patch.object(main.updater,'check_for_update',lambda:None):
                w=main.MinimalHMI()
                for timer in w.findChildren(QTimer):timer.stop()
                sup=w.dry_run.supervision
                with patch.object(w,'send_command',side_effect=AssertionError('Setting change sent a hardware command')):
                    self.assertEqual(w.board_sensor_location_input.value(),10.5)
                    self.assertEqual(sup.context().geometry.sensor,Span(10.5,10.5))
                    migrated=json.loads(settings.value('supervision/geometry_v1'))
                    self.assertNotIn('sensor_near',migrated);self.assertNotIn('sensor_far',migrated)
                    self.assertEqual(migrated['rear_extent'],16.75)
                    self.assertEqual(sup.coordinator.geometry.clamps[0].footprint,Span(8.75,9.75))
                    self.assertNotIn('sensor_near',sup.fields);self.assertNotIn('sensor_far',sup.fields)
                    self.assertFalse(any('Board detector zone' in label.text() for label in w.supervision_settings.findChildren(QLabel)))
                    sup.coordinator.locate_stock(Span(-.12,82.1252));revision=sup.coordinator.config_revision
                    w.board_sensor_location_input.setValue(10.25)
                    self.assertEqual(sup.coordinator.geometry.sensor,Span(10.25,10.25))
                    self.assertFalse(sup.coordinator.material.located)
                    self.assertGreater(sup.coordinator.config_revision,revision)
                    self.assertEqual(sup.context().geometry.sensor,Span(10.25,10.25))
                    # An old in-flight capture must not revive the stale board.
                    p=w.carriage_tab
                    p.x.update(POS_KNOWN='1',HOME_OFFSET='-9963',FAULT='NONE',EDGE_VALID='1',
                               MOVE_ID='7',EDGE_MILLI='92745',SENSOR_OFFSET_MILLI='10500',TRIM_MILLI='120')
                    sup.observe('BENCH_X')
                    self.assertFalse(sup.coordinator.material.located)
                    p.x.update(MOVE_ID='8',SENSOR_OFFSET_MILLI='10250')
                    sup.observe('BENCH_X')
                    self.assertTrue(sup.coordinator.material.located)
                    # Saving other dimensions cannot restore the old coordinates.
                    self.assertTrue(sup.save())
                    self.assertNotIn('sensor_near',json.loads(settings.value('supervision/geometry_v1')))
                    sup.coordinator.locate_stock(Span(-.12,82.1252))
                    w.kerf_input.setValue(.125)
                    self.assertFalse(sup.coordinator.material.located)
                    self.assertEqual(sup.coordinator.geometry.sensor,Span(10.25,10.25))
                    w._save_settings()
                w.close();self.app.processEvents()
                other=main.MinimalHMI()
                for timer in other.findChildren(QTimer):timer.stop()
                self.assertEqual(other.board_sensor_location_input.value(),10.25)
                self.assertEqual(other.dry_run.supervision.context().geometry.sensor,Span(10.25,10.25))
                self.assertFalse(other.dry_run.supervision.coordinator.material.located)
                other.close();self.app.processEvents()


if __name__=='__main__':unittest.main()
