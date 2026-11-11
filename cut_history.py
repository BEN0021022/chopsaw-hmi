"""Append-only cut metrics. Background disk I/O never gates machine commands."""
import csv
from datetime import datetime, timezone
from pathlib import Path
import math
import os
import queue
import threading
import time
import uuid


FIELDS = (
    'timestamp_utc', 'event_id', 'session_id', 'board_id', 'run_type', 'mode',
    'event_type', 'completed_count', 'cut_type', 'cut_number',
    'cut_length_in', 'cut_length_source', 'board_length_in', 'board_length_source',
    'board_preset_in', 'remaining_infeed_in', 'carriage_position_in', 'kerf_in',
    'controller_done', 'app_version',
)


def inches(value):
    """Unknown dimensions stay blank; no guessed zero-length cuts."""
    if value is None: return ''
    value = float(value)
    if not math.isfinite(value) or value < 0: return ''
    return round(value, 6)


class CutHistory:
    def __init__(self, directory, app_version):
        self.path = Path(directory) / 'cut_history.csv'
        self.app_version = app_version
        self.error = ''
        self.lost_records = 0
        self._queue = queue.Queue(maxsize=1000)
        self._stop = threading.Event()
        self._thread = None
        self._last_event = None
        self._written_event = None
        self.new_session()

    def new_session(self):
        self.session_id = uuid.uuid4().hex
        self.clear_board()
        self.pending = None

    def clear_board(self):
        self.board = {'board_id':'', 'board_length_in':'', 'board_length_source':'unknown'}

    def new_board(self, length=None, source='unknown'):
        self.board = {'board_id':uuid.uuid4().hex, 'board_length_in':inches(length),
                      'board_length_source':source if length is not None else 'unknown'}

    def prepare_cycle(self, *, expected_done, mode, cut_type, cut_number=None,
                      length=None, length_source='unknown', board_preset=None, kerf=None):
        # Called only for an accepted cycle request. Freeze the original target;
        # edits to the list/settings during a stroke must not rewrite its metrics.
        self.pending = dict(self.board, expected_done=expected_done, mode=mode,
                            cut_type=cut_type, cut_number=cut_number,
                            cut_length_in=inches(length), cut_length_source=length_source,
                            board_preset_in=inches(board_preset), kerf_in=inches(kerf))

    def completed(self, done, delta, *, remaining=None, position=None, board_preset=None):
        if not 0 < delta <= 0xffffffff: return False
        event_id = f'{self.session_id}:{done}'
        if event_id == self._last_event: return False
        associated = self.pending if delta == 1 and self.pending and self.pending['expected_done'] == done else None
        data = associated or dict(self.board, mode='unknown', cut_type='unassociated',
                                  cut_number=None, cut_length_in='', cut_length_source='unknown',
                                  board_preset_in=inches(board_preset), kerf_in='')
        row = {key:'' for key in FIELDS}
        row.update(timestamp_utc=datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
                   event_id=event_id, session_id=self.session_id,
                   # All current native combined cycles are unplugged tests.
                   # Production permissions are not changed by adding metrics.
                   run_type='dry_run', event_type='completed_cycle' if delta == 1 else 'counter_gap',
                   completed_count=delta, cut_type=data['cut_type'],
                   cut_number=data['cut_number'] if data['cut_number'] is not None else '',
                   cut_length_in=data['cut_length_in'], cut_length_source=data['cut_length_source'],
                   board_id=data['board_id'], board_length_in=data['board_length_in'],
                   board_length_source=data['board_length_source'], board_preset_in=data['board_preset_in'],
                   remaining_infeed_in=inches(remaining), carriage_position_in=inches(position),
                   kerf_in=data['kerf_in'], controller_done=done, app_version=self.app_version)
        # mode is a separate column: Manual / Auto / unknown.
        row['mode'] = data['mode']
        if self._stop.is_set():
            self.lost_records += 1
            self.error = 'Cut history is closed; a completed-cycle record could not be queued.'
            return False
        try: self._queue.put_nowait(row)
        except queue.Full:
            self.lost_records += 1
            self.error = 'Cut history queue is full; a completed-cycle record could not be queued.'
            return False
        self._last_event = event_id
        self.pending = None
        if self._thread is None:
            self._thread = threading.Thread(target=self._writer, name='cut-history', daemon=True)
            self._thread.start()
        return True

    def _append(self, row):
        # Never replace an existing history, even if its schema is unexpected.
        # One history writer per running app is assumed.
        with self.path.open('a+', newline='', encoding='utf-8') as stream:
            stream.seek(0)
            header = next(csv.reader(stream), None)
            columns = FIELDS
            if header is not None and header != list(columns):
                raise ValueError('Existing cut_history.csv has an unexpected header; it was not overwritten')
            stream.seek(0, os.SEEK_END)
            writer = csv.DictWriter(stream, fieldnames=columns)
            if header is None: writer.writeheader()
            if self._written_event != row['event_id']:
                writer.writerow(row)
            stream.flush()
            self._written_event = row['event_id']
            os.fsync(stream.fileno())

    def _writer(self):
        while not self._stop.is_set() or not self._queue.empty():
            try: row = self._queue.get(timeout=.2)
            except queue.Empty: continue
            while True:
                try:
                    self._append(row)
                    self.error = ''
                    self._queue.task_done()
                    break
                except (OSError, ValueError, csv.Error) as error:
                    self.error = f'Cut history could not be saved to {self.path}: {error}'
                    # Keep this row and retry in order, off the control thread.
                    if self._stop.wait(3): return

    def flush(self, timeout=1):
        deadline = time.perf_counter()+timeout
        while self._queue.unfinished_tasks and time.perf_counter() < deadline:
            time.sleep(.01)
        return self._queue.unfinished_tasks == 0

    def close(self, timeout=1):
        drained = self.flush(timeout)
        self._stop.set()
        if self._thread is not None: self._thread.join(timeout=.25)
        if not drained and not self.error:
            self.error = 'Cut history did not finish writing before shutdown.'
        return drained

    @property
    def warning(self):
        lost = f'{self.lost_records} cut-history record(s) could not be queued.' if self.lost_records else ''
        return ' '.join(part for part in (self.error, lost) if part)
