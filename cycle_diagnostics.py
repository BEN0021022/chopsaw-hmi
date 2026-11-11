"""Bounded, read-only observations of controller phases; no timing enforcement."""
from datetime import datetime, timezone
from collections import deque
import json


# Configured waits vs travel limits are deliberately distinguished.
PHASE_TIMINGS = {
    'CLAMP_DELAY': ('wait', ('board.settle', 'main.engage_delay')),
    'CLAMP_SETTLE': ('wait', ('main.engage_settle',)),
    'TRIGGER_DELAY': ('wait', ('trigger.press_delay',)),
    'SPINUP': ('wait', ('trigger.spinup',)),
    'DOWN_DELAY': ('wait', ('saw.down_delay',)),
    'DESCEND': ('travel limit', ('saw.down_timeout',)),
    'DWELL': ('wait', ('saw.bottom_dwell',)),
    'UP_DELAY': ('wait', ('saw.up_delay',)),
    'RETURN': ('travel limit', ('saw.up_timeout',)),
    'UP_SETTLE': ('wait', ('saw.up_settle',)),
    'TRIGGER_RELEASE_DELAY': ('wait', ('trigger.release_delay',)),
    'BRAKE_WAIT': ('wait', ('trigger.brake_wait',)),
    'RELEASE_DELAY': ('wait', ('main.release_delay',)),
    'RELEASE_CLEAR': ('wait', ('main.release_clearance',)),
}


class CycleDiagnostics:
    def __init__(self):
        self.events = deque(maxlen=2000)
        self.phases = deque(maxlen=500)
        self.latest = {}
        self._phase = None
        self._event_key = None
        self.dropped_events = 0
        self.dropped_phases = 0

    def _event(self, event):
        if len(self.events) == self.events.maxlen:
            self.dropped_events += 1
        self.events.append(event)

    def note(self, code, reason, now, details=None):
        key = (code, reason)
        if key != self._event_key:
            event = {'at': now, 'utc': datetime.now(timezone.utc).isoformat(),
                     'event': code, 'reason': reason}
            if details is not None: event['snapshot'] = details
            self._event(event)
            self._event_key = key

    def observe(self, snapshot, timings, now):
        self.latest = dict(snapshot)
        if not snapshot.get('fresh'):
            # Do not count a disconnect as time spent in the last known phase.
            self._finish(now, interrupted=True)
            self._phase = None
            self.note('FEEDBACK_UNAVAILABLE', snapshot.get('message', 'No fresh native readback'), now, snapshot)
            return
        phase = (snapshot.get('sequence', 'IDLE'), snapshot.get('controller', 'UNKNOWN'))
        # Host ACK -> WAIT transitions must not split a single physical wait.
        phase_key = ('TIMED', phase[1]) if phase[1] in PHASE_TIMINGS else phase
        if self._phase and self._phase['key'] == phase_key:
            return
        self._finish(now)
        kind, keys = PHASE_TIMINGS.get(phase[1], ('state', ()))
        expected = sum(timings[k] for k in keys) if keys and all(k in timings for k in keys) else None
        self._phase = {'key': phase_key, 'at': now, 'sequence': phase[0], 'controller': phase[1],
                       'expected_ms': expected, 'timing_kind': kind,
                       'timing_source': snapshot.get('timing_source', 'unknown')}
        self.note('PHASE', f'{phase[0]} / {phase[1]}', now, snapshot)

    def _finish(self, now, interrupted=False):
        if self._phase:
            if len(self.phases) == self.phases.maxlen:
                self.dropped_phases += 1
            row = {k: v for k, v in self._phase.items() if k != 'key'}
            row.update(observed_ms=round(max(0, now-row['at'])*1000), interrupted=interrupted)
            self.phases.append(row)

    def phase_rows(self, now):
        rows = list(self.phases)
        if self._phase:
            row = {k: v for k, v in self._phase.items() if k != 'key'}
            row.update(observed_ms=round(max(0, now-row['at'])*1000), active=True)
            rows.append(row)
        return rows

    def report(self, now):
        return {'format': 'chopsaw-commissioning-v1',
                'exported_utc': datetime.now(timezone.utc).isoformat(),
                'scope': 'Saw-unplugged commissioning; observed host intervals, not firmware duration or grip/blade-stop proof.',
                'dropped_events': self.dropped_events, 'dropped_phases': self.dropped_phases,
                'latest': self.latest, 'phases': self.phase_rows(now), 'events': list(self.events)}

    def write_report(self, path, now, extra):
        report = self.report(now)
        report.update(extra)
        with open(path, 'w', encoding='utf-8') as stream:
            json.dump(report, stream, indent=2, allow_nan=False)
