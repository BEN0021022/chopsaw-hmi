"""Acknowledged native unloaded-pneumatic adapter and real-input cut-list runner."""
import math
import re
import secrets
import time
from dataclasses import replace
from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QCheckBox, QPushButton
from sensor_bench.protocol import parse_line
from simulator import VirtualController
from supervision_ui import SupervisionAdapter
from automation_supervision import Outcome, plan_board_feed, assess_manual_cycle
from cycle_diagnostics import CycleDiagnostics

TIMING_KEYS = ('board.settle','main.engage_delay','main.engage_settle','main.release_delay',
               'main.release_clearance','saw.down_delay','saw.down_timeout','saw.bottom_dwell',
               'saw.up_delay','saw.up_timeout','saw.up_settle','trigger.press_delay',
               'trigger.spinup','trigger.release_delay','trigger.brake_wait')
STATES = {'OFF','READY','CLAMP_DELAY','CLAMP_SETTLE','CLAMPED','RELEASE_DELAY','RELEASE_CLEAR',
          'DOWN_DELAY','DESCEND','DOWN','DWELL','UP_DELAY','RETURN','UP_SETTLE','STOP_RETURN','FAULT',
          'TRIGGER_DELAY','SPINUP','TRIGGER_RELEASE_DELAY','BRAKE_WAIT','STOPPED'}
TRAVEL = {'DESCEND','DOWN','DWELL','UP_DELAY','RETURN','UP_SETTLE','STOP_RETURN'}
COMMAND = re.compile(r'(?:DSET ([0-9]+) ([0-9]+)|DCOMMIT ([0-9]+)|DARM ([0-9]+)|DCLAMP ([01])|DCYCLE|DDOWN|DUP|DOFF|DMANUAL ([0-9]+)|DTHOLD|DTPRESS|DTRELEASE|DCUT|DRELEASE)')


def timing_hash(values):
    value=2166136261
    for number in values:
        for byte in int(number).to_bytes(4,'little'):
            value=((value^byte)*16777619)&0xffffffff
    return value


class NativeDryRun(QObject):
    changed = pyqtSignal()

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.supervision = SupervisionAdapter(owner)
        self.diagnostics = CycleDiagnostics()
        self.session = None
        self.compatible = False
        self.data = {}
        self.received = None
        self.token = 0
        self.loaded = None
        self.pending = None
        self.awaiting_stop = False
        self.local_fault = ''
        self.sequence = None
        self.issuing_sequence = False
        self.last_keepalive = 0
        self.manual_start = None
        self.auto_start = None
        self.auto_start_at = 0
        self.trigger_held = False
        self.last_trigger_hold = 0
        self.message = 'Connect matching 0.21.0 firmware.'
        self.timer = QTimer(self); self.timer.setInterval(100); self.timer.timeout.connect(self.tick); self.timer.start()

    def controls(self):
        self.widget = QWidget()
        layout = QVBoxLayout(self.widget); layout.setContentsMargins(0,0,0,0)
        self.consent = QCheckBox('Unloaded test: no stock; saw unplugged; suppression and air checks complete')
        self.consent.toggled.connect(self.consent_changed)
        # Auto retains its separate preparation control. Manual uses one explicit
        # session-enable gesture; hidden objects preserve shared state/bindings.
        self.consent.setParent(self.widget); self.consent.hide()
        self.configure_button = QPushButton('Load dry-run timings')
        self.configure_button.setEnabled(False)
        self.configure_button.clicked.connect(self.configure)
        self.arm_button = QPushButton('Arm unloaded pneumatics')
        self.arm_button.setEnabled(False)
        self.arm_button.clicked.connect(lambda: self.request('arm'))
        self.configure_button.setParent(self.widget); self.configure_button.hide()
        self.arm_button.setParent(self.widget); self.arm_button.hide()
        self.trigger_consent = QCheckBox('Trigger test ONLY: saw mains physically unplugged; no stock; keep saw UP')
        self.trigger_consent.toggled.connect(self.trigger_consent_changed)
        self.trigger_consent.setParent(self.widget); self.trigger_consent.hide()
        note=QLabel('SAW MAINS UNPLUGGED — integrated timing dry run only.')
        note.setWordWrap(True); layout.addWidget(note)
        self.enable_manual_button=QPushButton('Enable unpowered manual controls')
        self.enable_manual_button.clicked.connect(self.enable_manual)
        self.enable_manual_button.setParent(self.widget); self.enable_manual_button.hide()
        self.label = QLabel(self.message); self.label.setWordWrap(True)
        self.label.setStyleSheet('color:#fbbf24;font-size:13px;')
        self.label.setParent(self.widget); self.label.hide()  # Manual status above already displays this message.
        return self.widget

    def native(self):
        return self.owner.is_connected() and not isinstance(self.owner.ser,VirtualController) and self.owner.carriage_tab.connected

    def sync(self):
        session = (self.owner.ser, self.native())
        if session != self.session:
            if hasattr(self.owner,'direct_controls'):self.owner.direct_controls.cancel()
            self.owner.cut_history.new_session()
            self.diagnostics.note('SESSION_CHANGED', 'Connection/session changed; no previous phase or material reference is reused.', time.monotonic())
            self.diagnostics.observe({'fresh':False,'message':'Connection/session changed'}, {}, time.monotonic())
            self.session = session; self.compatible=False; self.data={}; self.received=None
            self.token=0; self.loaded=None; self.pending=None; self.awaiting_stop=False; self.local_fault=''; self.sequence=None
            self.manual_start=None; self.auto_start=None; self.trigger_held=False
            self.supervision.reset_session()
            if hasattr(self,'consent'): self.consent.setChecked(False)
            if hasattr(self,'trigger_consent'): self.trigger_consent.setChecked(False)

    def fresh(self):
        return self.native() and self.compatible and self.received is not None and time.monotonic()-self.received <= 2

    def safe_link(self, require_consent=True):
        p=self.owner.carriage_tab
        return (self.fresh() and (not require_consent or self.consent.isChecked()) and not self.local_fault and p.ready_link()
                and p.fresh('INPUTS') and not p.local_fault and p.x.get('FAULT')=='NONE'
                and p.safety.get('FAULT')=='NONE' and p.safety.get('DOOR_CLOSED')=='1'
                and p.inputs.get('FENCE_DOOR')=='0' and p.x.get('ALARM_RAW')=='1'
                and all(p.inputs.get(k) in ('0','1') for k in ('SAW_UP','SAW_DOWN','CL57T_ALM'))
                and p.inputs.get('CL57T_ALM')=='1'
                and not (p.inputs.get('SAW_UP')==p.inputs.get('SAW_DOWN')=='0')
                and self.data.get('FAULT')=='NONE')

    def settings_match(self):
        return (self.loaded is not None and self.data.get('HASH')==str(timing_hash(self.loaded))
                and self.loaded == tuple(self.owner.cylinder_timing.snapshot()[key] for key in TIMING_KEYS))

    def motion_locked(self):
        return self.native() and (bool(getattr(getattr(self.owner,'direct_controls',None),'intent',None)) or bool(self.manual_start) or bool(self.auto_start) or self.awaiting_stop or self.sequence is not None or bool(self.local_fault) or
                                 self.data.get('ARMED')=='1' or self.data.get('STATE','OFF') not in ('OFF','FAULT'))

    def consent_changed(self, checked):
        if not checked and self.native() and (self.data.get('ARMED')=='1' or self.sequence):
            self.stop('Dry-run consent removed')
        self.changed.emit()

    def trigger_consent_changed(self, checked):
        if not checked and self.native() and self.compatible:
            self.request('unpress')
        self.changed.emit()

    def can_enable_manual(self):
        p=self.owner.carriage_tab
        return (self.safe_link(False) and not self.pending and not self.manual_start and not self.auto_start and not self.sequence
                and not self.awaiting_stop and not p.armed and not p.pending and not p.profile_pending
                and self.data.get('STATE')=='OFF' and p.x.get('REMAINING')=='0'
                and p.inputs.get('SAW_UP')=='0' and p.inputs.get('SAW_DOWN')=='1')

    def enable_manual(self):
        if self.data.get('MANUAL')=='1': self.stop(); return True
        if not self.can_enable_manual(): return False
        self.consent.setChecked(True)
        self.trigger_consent.setChecked(True)
        self.manual_start='config'
        if not self.configure():
            self.manual_start=None; return False
        return True

    def operator_holding_trigger(self):
        return (self.trigger_held and self.owner.manual_pneumatics.buttons['press'].isDown()
                and self.owner.isActiveWindow() and self.owner.tabs.currentWidget() is self.owner.legacy_tab)

    def can_hold_trigger(self):
        p=self.owner.carriage_tab
        return (self.safe_link() and not self.pending and not self.sequence and not self.auto_start and not self.manual_start and not self.awaiting_stop
                and self.settings_match() and self.data.get('CFG')==str(self.token)
                and self.data.get('MANUAL')=='1' and self.data.get('STATE') in ('READY','CLAMPED')
                and self.data.get('TRIGGER')=='0' and p.inputs.get('SAW_UP')=='0'
                and p.inputs.get('SAW_DOWN')=='1')

    def begin_trigger_hold(self):
        self.trigger_held=True
        if self.owner.direct_controls.request('actuator','press'): return True
        self.trigger_held=False; return False

    def end_trigger_hold(self):
        was_held=self.trigger_held
        self.trigger_held=False
        if self.owner.direct_controls.preparing_trigger():
            self.owner.direct_controls.cancel();self.stop();self.owner.direct_controls.message='Trigger released.';return
        if was_held or self.data.get('TRIGGER')=='1': self.request('unpress')

    def allowed(self, command):
        if command=='DOFF': return self.native() and self.compatible
        if command=='DRELEASE': return self.fresh() and self.data.get('RELEASE_READY')=='1' and not self.sequence
        if command=='DTRELEASE': return self.native() and self.compatible and not self.sequence
        if self.awaiting_stop: return False
        if command=='KEEPALIVE': return self.safe_link() and self.data.get('ARMED')=='1'
        if command=='DTHOLD':
            return (self.safe_link() and not self.sequence and self.operator_holding_trigger()
                    and self.data.get('MANUAL')=='1' and self.data.get('TRIGGER')=='1')
        if self.sequence and not self.issuing_sequence: return False
        match=COMMAND.fullmatch(command)
        if not match or not self.safe_link(): return False
        p=self.owner.carriage_tab
        state=self.data.get('STATE')
        if command.startswith(('DSET ','DCOMMIT ')):
            if match[1] is not None:
                index,value=int(match[1]),int(match[2])
                if not self.loaded or not 0<=index<len(TIMING_KEYS) or value!=self.loaded[index]: return False
            elif command!=f'DCOMMIT {self.token}': return False
            return bool(self.pending and self.pending['kind']=='config' and self.data.get('ARMED')=='0'
                        and state=='OFF' and not p.armed and not p.pending and not p.profile_pending
                        and p.x.get('REMAINING')=='0')
        if command.startswith(('DARM ','DMANUAL ')):
            requested=(f'DMANUAL {self.token}' if self.manual_start=='arm' else f'DARM {self.token}')
            return (command==requested and not self.pending and not p.armed and not p.pending and p.x.get('REMAINING')=='0'
                    and state=='OFF' and self.data.get('CFG')==str(self.token) and self.settings_match())
        if self.pending or self.data.get('ARMED')!='1' or self.data.get('CFG')!=str(self.token): return False
        if command=='DTPRESS':
            return self.can_hold_trigger() and self.operator_holding_trigger()
        if command=='DCUT':
            return (self.settings_match() and state in ('READY','CLAMPED') and self.data.get('CYCLE')=='0'
                    and self.data.get('TRIGGER')=='0' and (self.supervision.review().proceeds if self.sequence else
                                                         assess_manual_cycle(self.supervision.context()).proceeds))
        if self.data.get('CYCLE')=='1': return command=='DUP'
        if self.data.get('TRIGGER')!='0': return False
        if command=='DCLAMP 0': return state=='CLAMPED'
        if command=='DUP': return state in {'DOWN_DELAY','DESCEND','DOWN','DWELL','UP_DELAY'}
        if not self.settings_match(): return False
        if command=='DCLAMP 1': return state=='READY' and self.supervision.individual_clamp_allowed()
        return command in ('DCYCLE','DDOWN') and (state=='CLAMPED' or (state=='READY' and self.data.get('MANUAL')=='1')) and self.supervision.individual_clamp_allowed()

    def configure(self):
        self.sync()
        p=self.owner.carriage_tab
        if not self.safe_link() or self.pending or p.armed or self.data.get('STATE')!='OFF': return False
        values=tuple(self.owner.cylinder_timing.snapshot()[key] for key in TIMING_KEYS)
        if any(not 0<=value<=5000 for value in values) or min(values[6],values[9])<100:
            self.message='Dry-run delays must be 0–5000 ms; travel limits 100–5000 ms.'; self.changed.emit(); return False
        self.token=secrets.randbelow(0x7ffffffe)+1; self.loaded=values
        self.pending={'kind':'config','at':time.monotonic()}
        for index,value in enumerate(values):
            if not self.owner.send_command(f'DSET {index} {value}'):
                self.stop('Timing transfer failed'); return False
        if not self.owner.send_command(f'DCOMMIT {self.token}'):
            self.stop('Timing commit failed'); return False
        self.message='Waiting for controller timing acknowledgment.'; self.changed.emit(); return True

    def request(self, action):
        if action=='cycle' and self.sequence and self.sequence.get('stage')=='OPERATOR_REQUIRED':
            decision=self.supervision.review()
            if not decision.proceeds:
                self.message='Operator recovery required: '+decision.reason+' No clamp-free stroke is authorized.'
                self.changed.emit(); return False
            # An explicit gesture may resume only a newly valid holding plan;
            # geometry/material changes never resume automation by themselves.
            self.sequence['stage']='DISARM'; self.sequence['at']=time.monotonic()
            self.supervision.coordinator.paused=None
            return True
        commands={'arm':f'DARM {self.token}','engage':'DCLAMP 1','release':'DCLAMP 0',
                  'lower':'DDOWN','up':'DUP','cycle':'DCUT','manual_arm':f'DMANUAL {self.token}',
                  'press':'DTPRESS','unpress':'DTRELEASE','recover_release':'DRELEASE'}
        command=commands.get(action,'')
        if not self.allowed(command):
            if action=='cycle' and self.supervision.last_decision:
                self.message=self.supervision.last_decision.reason
                self.changed.emit()
            return False
        expected=(int(self.data.get('REQ','0'))+1)&0xffffffff
        if not self.owner.send_command(command): return False
        if action == 'cycle':
            s = self.sequence
            index = s['index'] if s else None
            self.owner.cut_history.prepare_cycle(
                expected_done=(int(self.data['DONE'])+1)&0xffffffff,
                mode='auto' if s else 'manual',
                cut_type='truing' if index == -1 else 'cut',
                cut_number=index+1 if index is not None and index >= 0 else None,
                length=(s['kerf'] if index == -1 else
                        s['cuts'][index] if s else None),
                length_source='truing_kerf' if index == -1 else 'cut_list_target' if s else 'unknown_manual_length',
                board_preset=self.owner.get_active_board_length(),
                kerf=s['kerf'] if s else self.owner.kerf_input.value())
        self.pending={'kind':'action','req':expected,'at':time.monotonic()}
        self.message='Waiting for controller acknowledgment.'; self.changed.emit(); return True

    def handle(self, line):
        self.sync()
        if not self.native(): return
        message=parse_line(line)
        if not message: return
        f=message.fields
        if message.kind=='BENCH_HELLO':
            compatible=(self.owner.carriage_tab.compatible and f.get('FW')=='0.21.0'
                        and f.get('DRY_RUN')=='UNLOADED_V5' and f.get('BLADE_LOCK')=='UNPLUGGED_CYCLE'
                        and f.get('TRIGGER_TEST')=='HOLD_V1' and f.get('CYCLE')=='CLAMP_TRIGGER_TRAVEL_V1')
            if self.compatible and not compatible: self.stop('Dry-run identity changed')
            self.compatible=compatible
        elif message.kind=='BENCH_DRY':
            try:
                valid=(f.get('PROTO')=='5' and f.get('LOCK') in ('0','1') and f.get('TRIGGER') in ('0','1')
                       and f.get('MANUAL') in ('0','1')
                       and f.get('CYCLE') in ('0','1') and f.get('RELEASE_READY') in ('0','1')
                       and f.get('STATE') in STATES and f.get('ARMED') in ('0','1')
                       and f.get('CLAMP') in ('0','1') and f.get('SAW') in ('0','1') and bool(f.get('FAULT'))
                       and all(0<=int(f[k])<=0xffffffff for k in ('CFG','HASH','REQ','UP_MS','DONE')))
            except (KeyError,ValueError): valid=False
            if valid:
                phase=f['STATE']
                clamped=phase in {'CLAMP_SETTLE','CLAMPED','RELEASE_DELAY','DOWN_DELAY','DESCEND','DOWN','DWELL','UP_DELAY','RETURN','UP_SETTLE','TRIGGER_DELAY','SPINUP','TRIGGER_RELEASE_DELAY','BRAKE_WAIT'}
                lowered=phase in {'DESCEND','DOWN','DWELL','UP_DELAY'}
                recovering=phase in ('STOP_RETURN','STOPPED','FAULT')
                cycle_trigger=phase in {'SPINUP','DOWN_DELAY','DESCEND','DOWN','DWELL','UP_DELAY','RETURN','UP_SETTLE','TRIGGER_RELEASE_DELAY'}
                manual_travel=(f['MANUAL']=='1' and f['CYCLE']=='0' and phase in
                               {'DOWN_DELAY','DESCEND','DOWN','DWELL','UP_DELAY','RETURN','UP_SETTLE'})
                valid=(f['ARMED']==('0' if phase in {'OFF','STOP_RETURN','STOPPED','FAULT'} else '1')
                       and (recovering or manual_travel or f['CLAMP']==str(int(clamped))) and f['SAW']==str(int(lowered))
                       and (f['FAULT']!='NONE')==(phase=='FAULT')
                       and f['LOCK']==('0' if f['MANUAL']=='1' or f['CYCLE']=='1' else '1')
                       and (f['MANUAL']=='0' or f['ARMED']=='1')
                       and (f['CYCLE']=='0' or (f['ARMED']=='1' and phase not in ('READY','CLAMPED')))
                       and (f['CYCLE']!='1' or f['TRIGGER']==str(int(cycle_trigger)))
                       and (f['TRIGGER']=='0' or f['CYCLE']=='1' or (f['MANUAL']=='1' and phase in ('READY','CLAMPED') and f['SAW']=='0'))
                       and (f['RELEASE_READY']=='0' or (phase in ('STOPPED','FAULT') and f['CLAMP']=='1')))
            if not valid:
                self.stop('Invalid dry-run readback'); return
            if self.data and int(f['UP_MS'])<int(self.data['UP_MS']):
                self.stop('Dry-run controller restarted'); return
            self.data=f; self.received=time.monotonic()
            if f['STATE'] in ('OFF','FAULT') and f['ARMED']=='0': self.awaiting_stop=False
            if self.token and f['CFG']==str(self.token) and self.loaded is not None and f['HASH']!=str(timing_hash(self.loaded)):
                self.stop('Controller timing readback mismatch'); return
            if self.pending:
                if ((self.pending['kind']=='config' and f['CFG']==str(self.token)) or
                    (self.pending['kind']=='action' and int(f['REQ'])==self.pending['req'])):
                    self.pending=None
            if f['FAULT']!='NONE':
                self.sequence=None; self.pending=None; self.manual_start=None; self.auto_start=None; self.trigger_held=False; self.message='Controller fault: '+f['FAULT']+'; clamp retained if engaged.'
            elif not self.local_fault and not self.sequence and not self.message.startswith('Unloaded dry list complete'):
                trigger=('PRESSED while held (commanded)' if f['TRIGGER']=='1' else
                         'released; hold-to-test ready' if f['MANUAL']=='1' else 'locked OFF')
                self.message='Unloaded dry run: '+f['STATE']+'; trigger '+trigger+'.'
        elif message.kind=='BENCH_ERROR' and f.get('CODE','').startswith(('DRY_','BLADE_')):
            self.stop('Controller rejected dry-run request: '+f.get('CODE','UNKNOWN'))
        if message.kind in ('BENCH_X','BENCH_DRY'): self.supervision.observe(message.kind)
        self.capture_diagnostics()
        self.changed.emit()

    def capture_diagnostics(self):
        """Record accepted readback only; diagnostics never requests an action."""
        p = self.owner.carriage_tab
        c = self.supervision.context()
        acknowledged = (self.fresh() and self.loaded is not None and self.token and
                        self.data.get('CFG') == str(self.token) and
                        self.data.get('HASH') == str(timing_hash(self.loaded)))
        timings = dict(zip(TIMING_KEYS, self.loaded)) if acknowledged else {}
        decision = self.supervision.last_decision
        snapshot = {
            'fresh': self.fresh() and p.ready_link() and p.fresh('INPUTS'),
            'sequence': self.sequence.get('stage','IDLE') if self.sequence else 'IDLE',
            'controller': self.data.get('STATE','UNKNOWN'), 'message': self.message,
            'timing_source': 'controller hash acknowledged' if acknowledged else 'not acknowledged',
            'acknowledged_timings_ms': timings,
            'position_in': c.position, 'material_revision': c.material.revision,
            'geometry_revision': self.supervision.coordinator.config_revision,
            'inputs_raw': dict(p.inputs), 'controller_readback': dict(self.data),
            'carriage_readback': dict(p.x),
            'decision': decision.code if decision else None,
            'local_fault': self.local_fault or p.local_fault,
        }
        self.diagnostics.observe(snapshot, timings, time.monotonic())

    def stop(self, reason='Stopped; trigger released, engaged clamp retained.'):
        if hasattr(self.owner,'direct_controls'):self.owner.direct_controls.cancel()
        if self.native() and self.owner.ser and self.owner.ser.is_open:
            self.awaiting_stop=True
            self.owner.send_command('OFF')
        p=self.owner.carriage_tab
        if p.armed or p.homing or p.x.get('REMAINING','0')!='0':p.stopping=True
        p.pending=None;p.profile_pending=None;p.full_home_pending=None
        self.sequence=None; self.pending=None; self.manual_start=None; self.auto_start=None; self.trigger_held=False; self.message=reason
        self.supervision.coordinator.invalidate('Stopped; reconcile material before another automatic cycle.')
        if reason!='Stopped; trigger released, engaged clamp retained.': self.local_fault=reason
        self.diagnostics.note('STOP', reason, time.monotonic())
        self.capture_diagnostics()
        self.changed.emit()

    def tick(self):
        self.sync()
        now=time.monotonic()
        if self.native() and (self.data.get('ARMED')=='1' or self.sequence):
            if not self.safe_link():
                if not self.local_fault: self.stop('Dry-run feedback/interlock lost; reset and re-confirm before retry.')
            elif not self.awaiting_stop and now-self.last_keepalive>=.25 and self.data.get('ARMED')=='1':
                self.owner.send_command('KEEPALIVE'); self.last_keepalive=now
        if self.pending and now-self.pending['at']>2: self.stop('Dry-run acknowledgment timed out')
        if self.manual_start and not self.pending:
            if not self.safe_link(): self.stop('Manual setup feedback lost')
            elif self.manual_start=='config' and self.data.get('CFG')==str(self.token):
                self.manual_start='arm'
                if not self.request('manual_arm'): self.stop('Manual enable rejected')
            elif self.manual_start=='arm' and self.data.get('MANUAL')=='1': self.manual_start=None
        if self.auto_start and not self.pending:
            self.issuing_sequence=True
            try:
                if not self.safe_link(): self.stop('Auto setup feedback lost')
                elif self.auto_start=='off' and now-self.auto_start_at>2: self.stop('Auto stop acknowledgment timed out')
                elif self.auto_start=='off' and self.data.get('STATE')=='OFF':
                    self.auto_start='config'
                    if not self.configure(): self.stop('Auto timing load rejected')
                elif self.auto_start=='config' and self.data.get('CFG')==str(self.token):
                    self.auto_start=None
                    if not self.start_sequence(): self.stop('Auto start rejected')
            finally: self.issuing_sequence=False
        if self.trigger_held:
            if not self.operator_holding_trigger(): self.end_trigger_hold()
            elif self.data.get('TRIGGER')=='1' and now-self.last_trigger_hold>=.1:
                self.owner.send_command('DTHOLD'); self.last_trigger_hold=now
            elif not self.pending and self.data.get('TRIGGER')=='0' and not self.owner.direct_controls.preparing_trigger():
                # An expired/lost hold never presses itself again.
                self.trigger_held=False
        if self.sequence:
            if not self.batch_unchanged() or self.sequence.get('reference_signature')!=self.supervision.current_reference_signature():
                self.stop('Cut list or reference settings changed; batch cancelled.');return
            if not self.supervision.coordinator.geometry.verified:
                self.stop('Supervision geometry/reference changed during sequence; no automatic restart')
                return
            self.issuing_sequence=True
            try: self.advance_sequence()
            finally: self.issuing_sequence=False
        if hasattr(self,'label'):
            self.label.setText(self.message)
            self.configure_button.setEnabled(self.safe_link() and not self.pending and not self.owner.carriage_tab.armed and self.data.get('STATE')=='OFF')
            self.arm_button.setEnabled(self.allowed(f'DARM {self.token}'))
            self.enable_manual_button.setText('Disable manual controls / STOP' if self.data.get('MANUAL')=='1' else
                                             'Enabling manual controls…' if self.manual_start else 'Enable unpowered manual controls')
            self.enable_manual_button.setEnabled(self.can_enable_manual() or self.data.get('MANUAL')=='1')
        if hasattr(self.owner,'auto_dry_run'):
            self.owner.auto_dry_status.setText(self.message)
            self.owner.auto_dry_run.setEnabled(self.can_start())
            self.owner.auto_dry_configure.setEnabled(self.configure_button.isEnabled() and not self.sequence)
            self.owner.auto_dry_stop.setEnabled(self.native() and self.compatible)
            if self.native(): self.owner.start_cycle_button.setEnabled(self.can_begin_auto() or self.owner.direct_controls.can_motion('auto'))
        self.owner.direct_controls.tick()
        self.capture_diagnostics()
        self.changed.emit()

    def acknowledge(self):
        if self.native() and self.owner.carriage_tab.ready_link() and self.owner.carriage_tab.safety.get('RESET_READY')=='1':
            self.owner.carriage_tab.acknowledge(); self.local_fault=''; self.consent.setChecked(False)
            self.trigger_consent.setChecked(False)

    def waiting_for_board(self):
        return bool(self.sequence and self.sequence['stage'] in ('WAIT_NEW_BOARD','BOARD_TOO_SHORT'))

    def batch_unchanged(self):
        return (not self.sequence or (tuple(self.owner.cut_list)==self.sequence['list_snapshot'] and
                self.owner.kerf_input.value()==self.sequence['kerf']))

    def can_begin_auto(self):
        p=self.owner.carriage_tab
        return (self.supervision.coordinator.geometry.verified and self.safe_link(False) and not self.pending and not self.manual_start and not self.auto_start
                and not self.awaiting_stop and (not self.sequence or self.waiting_for_board()) and self.batch_unchanged() and not p.armed and not p.pending
                and not p.profile_pending and not p.stopping and p.x.get('CONFIGURED')=='1'
                and p.x.get('POS_KNOWN')=='1' and p.x.get('REMAINING')=='0'
                and self.data.get('STATE') in ('OFF','READY') and self.data.get('CLAMP')=='0'
                and self.data.get('TRIGGER')=='0' and self.data.get('CYCLE')=='0'
                and p.inputs.get('SAW_UP')=='0' and p.inputs.get('SAW_DOWN')=='1'
                and p.inputs.get('BOARD_EDGE')=='1' and bool(self.owner.cut_list))

    def begin_auto(self):
        if not self.can_begin_auto(): return False
        self.consent.setChecked(True); self.owner.carriage_tab.consent.setChecked(True)
        self.auto_start='off'; self.auto_start_at=time.monotonic()
        self.issuing_sequence=True
        try: sent=self.owner.send_command('DOFF')
        finally: self.issuing_sequence=False
        if not sent: self.stop('Cannot prepare Auto'); return False
        return True

    def start_sequence(self):
        p=self.owner.carriage_tab
        if not self.can_start(): return False
        previous=self.sequence if self.waiting_for_board() else None
        cuts=previous['cuts'] if previous else [float(length) for _,length,_ in self.owner.cut_list]
        if any(not math.isfinite(x) or x<=0 for x in cuts): return False
        self.supervision.coordinator.invalidate('New board acquisition requested.')
        self.owner.cut_history.clear_board()
        self.sequence={'stage':'SEARCH_ARM','at':time.monotonic(),'cuts':cuts,'kerf':self.owner.kerf_input.value(),
                       'index':-1,'next_index':previous['next_index'] if previous else 0,
                       'board':previous['board']+1 if previous else 1,
                       'list_snapshot':previous['list_snapshot'] if previous else tuple(self.owner.cut_list),
                       'reference_signature':self.supervision.current_reference_signature(),
                       'move_id':int(p.x['MOVE_ID']),
                       'edge_command':f'XEDGE {int(math.floor(p.edge_search.value()*127.12+.5))} '
                                      f'{int(math.floor(self.owner.board_sensor_location_input.value()*1000+.5))} '
                                      f'{int(math.floor(self.owner.kerf_input.value()*1000+.5))}'}
        # The explicit Run Dry List gesture authorizes this sequence's arming.
        self.issuing_sequence=True
        try: sent=self.owner.send_command('XARM 1')
        finally: self.issuing_sequence=False
        if not sent:
            self.stop('Cannot arm board acquisition'); return False
        self.message='Dry list: arming acquisition; keep board detector clear until SEARCH.'
        return True

    def can_start(self):
        p=self.owner.carriage_tab
        return not (not self.supervision.coordinator.geometry.verified or not self.safe_link() or self.awaiting_stop or self.pending or
                (self.sequence and not self.waiting_for_board()) or not self.batch_unchanged() or self.auto_start or self.manual_start or not self.settings_match() or
                self.data.get('CFG')!=str(self.token) or not self.token or p.pending or p.profile_pending or p.stopping or
                self.data.get('STATE')!='OFF' or p.armed or p.x.get('POS_KNOWN')!='1'
                or not p.consent.isChecked() or p.x.get('CONFIGURED')!='1'
                or p.inputs.get('BOARD_EDGE')!='1' or not self.owner.cut_list
                or not 0<=self.owner.board_sensor_location_input.value()<=160.5
                or int(p.x.get('HOME_OFFSET','0'))-int(math.floor(p.edge_search.value()*127.12+.5))<int(p.x.get('SOFT_MIN_OFFSET','0')))

    def advance_sequence(self):
        # Implemented as ACK/state transitions, never PC timers commanding valve phases.
        s=self.sequence; p=self.owner.carriage_tab
        if not s or self.pending or p.profile_pending: return
        if not self.safe_link(): self.stop('Dry-list feedback/interlock lost'); return
        stage=s['stage']
        def next_stage(name): s['stage']=name; s['at']=time.monotonic()
        if stage=='SEARCH_ARM' and p.armed and p.x.get('JOG_READY')=='1':
            if not p.request_move(s['edge_command']): self.stop('Board detector must be clear before acquisition'); return
            next_stage('SEARCH')
        elif stage=='SEARCH' and p.x.get('EDGE_VALID')=='1' and p.x.get('EDGE_STATE')=='FOUND' and not p.armed:
            # Preview ONE next cut on the captured board. Future boards in the
            # queue do not have to fit this board's available carriage travel.
            c=self.supervision.context()
            proposed=int(p.x['TRUING_MILLI'])/1000
            material=c.material
            if material.located:
                material=replace(material,stock=material.stock.shifted(proposed-c.position))
            decision=plan_board_feed(replace(c,position=proposed,material=material),s['cuts'][s['next_index']],s['kerf'])
            if not decision.proceeds or decision.code=='NEXT_BOARD_REQUIRED':
                self.supervision.coordinator.paused=decision
                next_stage('BOARD_TOO_SHORT')
                self.message=decision.reason+' Load suitable stock and start acquisition again; no truing stroke was sent.'
                return
            if not p.select_profile(2): self.stop('Cannot select stored Normal profile'); return
            next_stage('TRUE_PROFILE')
        elif stage=='TRUE_PROFILE' and p.x.get('PROFILE_ID')=='2':
            if not self.owner.send_command('XARM 1'): self.stop('Cannot arm truing move'); return
            next_stage('TRUE_ARM')
        elif stage=='TRUE_ARM' and p.armed and p.x.get('JOG_READY')=='1':
            if not p.move_to_truing(): self.stop('Keep the board detector active until truing starts'); return
            s['move_id']=int(p.x['MOVE_ID']); next_stage('MOVE')
        elif stage=='FEED_ARM' and p.armed and p.x.get('JOG_READY')=='1':
            if not p.move_to(s['target']): self.stop('Dry-list feed rejected'); return
            s['move_id']=int(p.x['MOVE_ID']); next_stage('MOVE')
        elif stage=='MOVE' and not p.pending and int(p.x['MOVE_ID'])!=s['move_id'] and p.x.get('REMAINING')=='0':
            self.owner.send_command('XARM 0'); next_stage('DISARM')
        elif stage=='DISARM' and not p.armed and not p.stopping:
            # Captured stock was translated by the real sensor+kerf advance.
            # Do not fabricate a new material origin to hide a truing mismatch.
            decision=self.supervision.review()
            if not decision.proceeds:
                next_stage('OPERATOR_REQUIRED')
                self.message='Operator intervention required: '+decision.reason
                self.changed.emit(); return
            if not self.request('arm'): self.stop('Cannot arm unloaded pneumatics'); return
            next_stage('CLAMP')
        elif stage=='CLAMP' and self.data.get('STATE')=='READY':
            s['done']=int(self.data['DONE'])
            if not self.request('cycle'): self.stop('Saw cycle rejected'); return
            next_stage('SAW_ACK')
        elif stage=='SAW_ACK':
            # REQ acknowledgment completes before this branch; next status may
            # still be DOWN_DELAY, but the cycle must actually leave CLAMPED.
            if self.data.get('CYCLE')=='1': next_stage('SAW_WAIT')
        elif stage=='SAW_WAIT' and self.data.get('STATE')=='READY' and int(self.data['DONE'])!=s['done']:
            self.owner.send_command('DOFF'); next_stage('PNEU_OFF')
        elif stage=='PNEU_OFF' and self.data.get('STATE')=='OFF' and self.data.get('ARMED')=='0':
            s['index']=s['next_index'] if s['index']==-1 else s['index']+1
            s['next_index']=s['index']
            if s['index']>=len(s['cuts']):
                self.finish_board(next_stage); return
            else:
                decision=self.supervision.review('feed',length=s['cuts'][s['index']],kerf=s['kerf'])
                if decision.code=='NEXT_BOARD_REQUIRED':
                    self.finish_board(next_stage); return
                if not decision.proceeds:
                    self.stop(decision.reason); return
                s['target']=decision.target
                if not self.owner.send_command('XARM 1'): self.stop('Cannot arm dry-list feed'); return
                next_stage('FEED_ARM')
        elif stage=='CLEAR_PROFILE' and not p.profile_pending and p.x.get('PROFILE_ID')=='1':
            decision=self.supervision.review('clear_sensor')
            if (not decision.proceeds or decision.target!=s['clear_target'] or
                    not self.supervision.coordinator.still_valid(s['clear_plan'])):
                self.stop('Cleanup plan changed; operator reconciliation required'); return
            if not self.owner.send_command('XARM 1'): self.stop('Cannot arm bounded cleanup'); return
            next_stage('CLEAR_ARM')
        elif stage=='CLEAR_ARM' and p.armed and p.x.get('JOG_READY')=='1':
            decision=self.supervision.review('clear_sensor')
            if not decision.proceeds or not self.supervision.coordinator.still_valid(s['clear_plan']):
                self.stop('Cleanup eligibility changed before movement; no retry'); return
            if not p.move_to(s['clear_target']): self.stop('Cleanup target rejected'); return
            s['move_id']=int(p.x['MOVE_ID']); next_stage('CLEAR_MOVE')
        elif stage=='CLEAR_MOVE' and not p.pending and int(p.x['MOVE_ID'])!=s['move_id'] and p.x.get('REMAINING')=='0':
            self.owner.send_command('XARM 0'); next_stage('CLEAR_VERIFY')
        elif stage=='CLEAR_VERIFY' and not p.armed:
            if p.fresh('INPUTS') and p.inputs.get('BOARD_EDGE')=='1':
                if 'clear_since' not in s: s['clear_since']=time.monotonic()
                if time.monotonic()-s['clear_since']>=.25:
                    if not self.owner.send_command('XARM 1'): self.stop('Cannot arm return after clearance'); return
                    next_stage('LOAD_ARM')
            else: s.pop('clear_since',None)
            if time.monotonic()-s['at']>2: self.stop('Detector did not clear after bounded push; no retry'); return
        elif stage=='LOAD_ARM' and p.armed and p.x.get('JOG_READY')=='1':
            if not p.move_load_to(self.owner.native_load_target()): self.stop('Return-to-load rejected'); return
            s['move_id']=int(p.x['MOVE_ID']); next_stage('LOAD_WAIT')
        elif stage=='LOAD_WAIT' and not p.pending and int(p.x['MOVE_ID'])!=s['move_id'] and p.x.get('REMAINING')=='0':
            self.owner.send_command('XARM 0'); next_stage('DONE')
        elif stage=='DONE' and not p.armed:
            if s['next_index']<len(s['cuts']):
                next_stage('WAIT_NEW_BOARD')
                self.message=f"Board {s['board']} complete. Load the next board; next cut is {s['next_index']+1}. Press Start next board when ready."
            else:
                self.sequence=None; self.message='Unloaded dry list complete; production cut-list progress unchanged.'
            return
        elif stage in ('WAIT_NEW_BOARD','BOARD_TOO_SHORT'):
            self.message=(f"Board {s['board']}: waiting for suitable stock for cut {s['next_index']+1}. "
                          'Detector must be clear; press Start next board to acquire. '+
                          ('Cut list/kerf changed; restore them or Stop to begin a new batch.' if not self.batch_unchanged() else ''))
            return
        elif stage in ('OPERATOR_REQUIRED','CLEARANCE_REQUIRED'):
            decision=self.supervision.coordinator.paused
            self.message='OPERATOR REQUIRED — '+(decision.reason if decision else 'Reconcile material/holding and restart.')
            return  # Unenergized human pause has no arbitrary 180-second expiry.
        if self.sequence:
            label = ('SEARCH — trip and hold the real board detector until truing starts' if s['stage']=='SEARCH' else s['stage'])
            self.message=f"Dry list board {s['board']}: {label} — {'truing' if s['index']<0 else 'cut '+str(s['index']+1)}; saw mains MUST stay unplugged."
            if time.monotonic()-s['at']>180:
                self.stop('Dry-list phase exceeded 180 seconds')

    def finish_board(self, next_stage):
        """Same bounded cleanup/verified return at end of EACH board."""
        s=self.sequence; p=self.owner.carriage_tab
        decision=self.supervision.review('clear_sensor')
        if not decision.proceeds:
            next_stage('CLEARANCE_REQUIRED'); self.message=decision.reason; return
        if decision.outcome==Outcome.ADAPT:
            s['clear_target']=decision.target; s['clear_plan']=decision
            if not p.select_profile(1): self.stop('Cannot select cleanup Gentle profile'); return
            next_stage('CLEAR_PROFILE')
        else:
            if not self.owner.send_command('XARM 1'): self.stop('Cannot arm carriage return'); return
            next_stage('LOAD_ARM')
