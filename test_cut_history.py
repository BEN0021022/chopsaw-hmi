"""Long-lived CSV metrics: append, identity, unknowns, completion and disk errors."""
import csv
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from cut_history import CutHistory


class CutHistoryTests(unittest.TestCase):
    def rows(self, journal):
        self.assertTrue(journal.flush())
        with journal.path.open(newline='',encoding='utf-8') as stream:
            return list(csv.DictReader(stream))

    def prepare(self, journal, done=1, length=18):
        journal.prepare_cycle(expected_done=done, mode='auto', cut_type='cut',
                              cut_number=1, length=length, length_source='cut_list_target',
                              board_preset=144.5, kerf=.1)

    def test_completion_only_append_across_app_restart_and_no_duplicate(self):
        with tempfile.TemporaryDirectory() as folder:
            journal=CutHistory(folder,'test')
            journal.new_board(145.25,'edge_estimate')
            self.prepare(journal)
            self.assertFalse(journal.path.exists(), 'Requesting a cut must not log completion')
            self.assertTrue(journal.completed(1,1,remaining=126.15,position=126.15))
            self.assertFalse(journal.completed(1,1))
            row=self.rows(journal)[0]
            self.assertEqual(row['cut_length_in'],'18.0')
            self.assertEqual(row['board_length_in'],'145.25')
            self.assertEqual(row['board_preset_in'],'144.5')
            self.assertEqual(row['run_type'],'production')
            self.assertEqual(row['board_length_source'],'edge_estimate')
            self.assertTrue(journal.close())
            second=CutHistory(folder,'test')
            self.prepare(second)
            self.assertTrue(second.completed(1,1))
            rows=self.rows(second)
            self.assertEqual(len(rows),2)
            self.assertNotEqual(rows[0]['event_id'],rows[1]['event_id'])
            with second.path.open(encoding='utf-8') as stream:
                self.assertEqual(sum(line.startswith('timestamp_utc,') for line in stream),1)
            second.close()

    def test_manual_unknowns_stable_board_and_counter_gap(self):
        with tempfile.TemporaryDirectory() as folder:
            journal=CutHistory(folder,'test'); journal.new_board()
            journal.prepare_cycle(expected_done=1, mode='manual',cut_type='cut')
            journal.completed(1,1)
            row=self.rows(journal)[0]
            self.assertEqual(row['cut_length_in'],'')
            self.assertEqual(row['board_length_in'],'')
            self.assertEqual(row['board_length_source'],'unknown')
            journal.completed(4,3)
            rows=self.rows(journal)
            self.assertEqual(rows[-1]['event_type'],'counter_gap')
            self.assertEqual(rows[-1]['completed_count'],'3')
            self.assertEqual(rows[-1]['cut_length_in'],'')
            journal.close()

    def test_slow_disk_write_is_nonblocking_and_records_stay_in_order(self):
        with tempfile.TemporaryDirectory() as folder:
            journal=CutHistory(folder,'test')
            entered=threading.Event(); release=threading.Event()
            original=journal._append
            def delayed(row):
                entered.set(); release.wait(2); original(row)
            with patch.object(journal,'_append',delayed):
                self.prepare(journal)
                started=time.perf_counter(); journal.completed(1,1)
                self.assertLess(time.perf_counter()-started,.2)
                self.assertTrue(entered.wait(1))
                self.prepare(journal,2,24); journal.completed(2,1)
                self.assertFalse(journal.flush(.01))
                release.set(); rows=self.rows(journal)
                self.assertEqual([r['cut_length_in'] for r in rows],['18.0','24.0'])
            journal.close()

    def test_permission_failure_is_reported_without_blocking_caller(self):
        with tempfile.TemporaryDirectory() as folder:
            journal=CutHistory(folder,'test')
            with patch.object(journal,'_append',side_effect=PermissionError('file is locked')):
                self.prepare(journal)
                self.assertTrue(journal.completed(1,1))
                deadline=time.perf_counter()+1
                while not journal.warning and time.perf_counter()<deadline: time.sleep(.01)
                self.assertIn('file is locked',journal.warning)
                self.assertFalse(journal.close(.01))

    def test_incompatible_existing_file_is_preserved_and_warning_visible(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'cut_history.csv'; path.write_text('my,old,schema\n1,2,3\n')
            journal=CutHistory(folder,'test'); self.prepare(journal); journal.completed(1,1)
            deadline=time.perf_counter()+1
            while not journal.warning and time.perf_counter()<deadline: time.sleep(.01)
            self.assertIn('unexpected header',journal.warning)
            self.assertFalse(journal.close(.01))
            self.assertEqual(path.read_text(),'my,old,schema\n1,2,3\n')

    def test_new_board_and_session_do_not_reuse_previous_dimensions(self):
        with tempfile.TemporaryDirectory() as folder:
            journal=CutHistory(folder,'test'); journal.new_board(144,'edge_estimate')
            self.prepare(journal); journal.new_session()
            self.assertIsNone(journal.pending)
            journal.completed(8,1)
            row=self.rows(journal)[0]
            self.assertEqual(row['cut_type'],'unassociated')
            self.assertEqual(row['board_length_in'],'')
            journal.close()


if __name__=='__main__': unittest.main()
