"""Acknowledged native unloaded-pneumatic adapter and real-input cut-list runner."""
import math
import re
import secrets
import time
from datetime import datetime, timezone
from dataclasses import asdict, replace
from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QCheckBox, QPushButton
from sensor_bench.protocol import parse_line
from simulator import VirtualController
from supervision_ui import SupervisionAdapter
from automation_supervision import Decision, Outcome, plan_board_feed, assess_manual_cycle
from cycle_diagnostics import CycleDiagnostics
from cycle_intervention import CycleIntervention

TIMING_KEYS = ('board.settle','main.engage_delay','main.engage_settle','main.release_delay',
               'main.release_clearance','saw.down_delay','saw.down_timeout','saw.bottom_dwell',
               'saw.up_delay','saw.up_timeout','saw.up_settle','trigger.press_delay',
               'trigger.spinup','trigger.release_delay','trigger.brake_wait')
STATES = {'OFF','READY','CLAMP_DELAY','CLAMP_SETTLE','CLAMPED','RELEASE_DELAY','RELEASE_CLEAR',
          'DOWN_DELAY','DESCEND','DOWN','DWELL','UP_DELAY','RETURN','UP_SETTLE','STOP_RETURN','FAULT',
          'TRIGGER_DELAY','SPINUP','TRIGGER_RELEASE_DELAY','BRAKE_WAIT','STOPPED'}
TRAVEL = {'DESCEND','DOWN','DWELL','UP_DELAY','RETURN','UP_SETTLE','STOP_RETURN'}
COMMAND = re.compile(r'(?:DSET ([0-9]+) ([0-9]+)|DCOMMIT ([0-9]+)|DARM ([0-9]+)|DCLAMP ([01])|DCYCLE|DDOWN|DUP|DOFF|DMANUAL ([0-9]+)|DTHOLD|DTPRESS|DTRELEASE|DCUT|DRELEASE|DOPCUT [0-9]+ [0-9]+)')
SECOND_COMMAND = re.compile(r'(?:DCLAMP2 [01]|DCUTM [0-9]+ [0-9]+ [123]|DRETURN [0-9]+ [0-9]+ [0-9]+|DCUTRET [0-9]+ [0-9]+ [123] [0-9]+ [0-9]+)')
SECOND_TIMING_KEYS=('outfeed.engage_delay','outfeed.engage_settle','outfeed.release_delay','outfeed.release_clearance')


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
        self.second_supported = False
        self.data = {}
        self.received = None
        self.token = 0
        self.loaded = None
        self.pending = None
        self.awaiting_stop = False
        self.local_fault = ''
        self.sequence = None
        self.intervention=CycleIntervention(self)
        self.issuing_sequence = False
        self.last_keepalive = 0
        self.manual_start = None
        self.auto_start = None
        self.auto_start_at = 0
        self.trigger_held = False
        self.last_trigger_hold = 0
        self.progress_index=None; self.progress_batch=None
        self.message = 'Connect compatible Teensy firmware. Second clamp requires 0.24+.'
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
            self.session = session; self.compatible=False; self.second_supported=False; self.data={}; self.received=None
            self.token=0; self.loaded=None; self.pending=None; self.awaiting_stop=False; self.local_fault=''; self.sequence=None
            self.manual_start=None; self.auto_start=None; self.trigger_held=False
            self.intervention.clear()
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
                and p.inputs.get('SAW_UP') in ('0','1')
                and p.inputs.get('SAW_DOWN') in ('0','1')
                and p.inputs.get('CL57T_ALM') in ('0','1')
                and p.inputs.get('CL57T_ALM')=='1'
                and not (p.inputs.get('SAW_UP')==p.inputs.get('SAW_DOWN')=='0')
                and self.data.get('FAULT')=='NONE')

    def settings_match(self):
        return (self.loaded is not None and self.data.get('HASH')==str(timing_hash(self.loaded))
                and self.loaded == self.configuration_values()
                and (not self.supervision.second_requested() or self.second_supported))

    def configuration_values(self):
        values=self.owner.cylinder_timing.snapshot()
        result=tuple(values[key] for key in TIMING_KEYS)
        if self.second_supported:
            enabled=self.supervision.second_requested()
            result+=(int(enabled),)+(tuple(values[key] for key in SECOND_TIMING_KEYS) if enabled else (0,0,0,0))
        return result

    def cycle_clamp_mask(self):
        decision=self.supervision.review() if self.sequence else assess_manual_cycle(self.supervision.context())
        if not decision.proceeds:return 0
        return sum({'main':1,'outfeed':2}.get(key,0) for key in decision.permitted_clamps)

    def motion_locked(self):
        return self.native() and (bool(getattr(getattr(self.owner,'direct_controls',None),'intent',None)) or bool(self.manual_start) or bool(self.auto_start) or self.awaiting_stop or self.sequence is not None or bool(self.local_fault) or
                                 self.data.get('ARMED')=='1' or self.data.get('STATE','OFF') not in ('OFF','FAULT'))

    def consent_changed(self, checked):
        if not checked and self.native() and not self.intervention.recovering() and (self.data.get('ARMED')=='1' or self.sequence):
            self.stop('Dry-run consent removed')
        self.changed.emit()

    def trigger_consent_changed(self, checked):
        if not checked and self.native() and self.compatible and not self.intervention.recovering():
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
        if command=='DRELEASE': return self.fresh() and self.data.get('RELEASE_READY')=='1' and (not self.sequence or self.intervention.recovering())
        if command=='DTRELEASE': return self.native() and self.compatible and not self.sequence
        if self.awaiting_stop: return False
        if command=='KEEPALIVE': return self.safe_link() and self.data.get('ARMED')=='1'
        if command=='DTHOLD':
            return (self.safe_link() and not self.sequence and self.operator_holding_trigger()
                    and self.data.get('MANUAL')=='1' and self.data.get('TRIGGER')=='1')
        if self.sequence and not self.issuing_sequence: return False
        match=COMMAND.fullmatch(command)
        second=SECOND_COMMAND.fullmatch(command)
        if not (match or (self.second_supported and second)) or not self.safe_link(): return False
        p=self.owner.carriage_tab
        state=self.data.get('STATE')
        if command.startswith(('DSET ','DCOMMIT ')):
            if match[1] is not None:
                index,value=int(match[1]),int(match[2])
                if not self.loaded or not 0<=index<len(self.loaded) or value!=self.loaded[index]: return False
            elif command!=f'DCOMMIT {self.token}': return False
            return bool(self.pending and self.pending['kind']=='config' and self.data.get('ARMED')=='0'
                        and state=='OFF' and not p.armed and not p.pending and not p.profile_pending
                        and p.x.get('REMAINING')=='0')
        if command.startswith(('DARM ','DMANUAL ')):
            requested=(f'DMANUAL {self.token}' if self.manual_start=='arm' else f'DARM {self.token}')
            return (command==requested and not self.pending and not p.armed and not p.pending and p.x.get('REMAINING')=='0'
                    and state=='OFF' and self.data.get('CFG')==str(self.token) and self.settings_match())
        if command.startswith('DRETURN '):
            s=self.sequence
            return bool(s and s['stage']=='EARLY_RETURN_WAIT' and s.get('operator_confirmed') and
                        self.owner.carriage_tab.parallel_supported() and self.owner.carriage_tab.armed and
                        self.operator_snapshot_valid(True) and self.settings_match() and not self.pending and
                        self.data.get('STATE')=='OFF' and self.data.get('ARMED')=='0' and
                        p.x.get('RETURN_PERMIT')=='1' and p.x.get('RETURN_USED')=='0' and
                        command==f"DRETURN {self.token} {(int(self.data['REQ'])+1)&0xffffffff} {p.x['MOVE_ID']}")
        if self.pending or self.data.get('ARMED')!='1' or self.data.get('CFG')!=str(self.token): return False
        if command=='DTPRESS':
            return self.can_hold_trigger() and self.operator_holding_trigger()
        if command=='DCUT' or command.startswith(('DCUTM ','DCUTRET ')):
            mask=self.cycle_clamp_mask()
            if command.startswith('DCUTRET '):
                s=self.sequence
                if (not s or not s.get('automatic_cut_return') or not p.automatic_return_supported() or
                    not self.supervision.coordinator.still_valid(s['cut_return_plan']) or
                    command!=f"DCUTRET {self.token} {(int(self.data['REQ'])+1)&0xffffffff} {mask} {s['cut_return_target']} {s['cut_return_min']}"):
                    return False
                if mask!=s['cut_return_mask']:return False
            elif command.startswith('DCUTM '):
                if command!=f"DCUTM {self.token} {(int(self.data['REQ'])+1)&0xffffffff} {mask}":return False
                if mask & 2 and (not self.supervision.second_requested() or self.data.get('SECOND_ENABLED')!='1'):return False
            elif mask!=1:return False
            return (self.settings_match() and state in ('READY','CLAMPED') and self.data.get('CYCLE')=='0'
                    and self.data.get('TRIGGER')=='0' and (self.supervision.review().proceeds if self.sequence else
                                                         assess_manual_cycle(self.supervision.context()).proceeds))
        if command.startswith('DOPCUT '):
            s=self.sequence
            return bool(s and s['stage']=='OPERATOR_ARMED' and s.get('operator_confirmed')
                        and self.operator_snapshot_valid() and self.settings_match()
                        and state=='READY' and self.data.get('MANUAL')=='0' and self.data.get('CLAMP')=='0'
                        and self.data.get('TRIGGER')=='0' and self.data.get('CYCLE')=='0'
                        and command==f"DOPCUT {self.token} {(int(self.data['REQ'])+1)&0xffffffff}")
        if self.data.get('CYCLE')=='1': return command=='DUP'
        if self.data.get('TRIGGER')!='0': return False
        if command.startswith('DCLAMP2 '):
            on=command.endswith('1')
            return (self.settings_match() and self.supervision.second_requested() and self.data.get('SECOND_ENABLED')=='1'
                    and self.data.get('MANUAL')=='1' and state in ('READY','CLAMPED')
                    and self.data.get('SECOND_CLAMP')==('0' if on else '1')
                    and (not on or self.supervision.individual_clamp_allowed('outfeed')))
        if command=='DCLAMP 0': return state=='CLAMPED' and self.data.get('MAIN_CLAMP',self.data.get('CLAMP'))=='1'
        if command=='DUP': return state in {'DOWN_DELAY','DESCEND','DOWN','DWELL','UP_DELAY'}
        if not self.settings_match(): return False
        if command=='DCLAMP 1': return state in ('READY','CLAMPED') and self.data.get('MAIN_CLAMP',self.data.get('CLAMP'))=='0' and self.supervision.individual_clamp_allowed()
        return command in ('DCYCLE','DDOWN') and (state=='CLAMPED' or (state=='READY' and self.data.get('MANUAL')=='1')) and self.supervision.individual_clamp_allowed()

    def configure(self):
        self.sync()
        p=self.owner.carriage_tab
        if not self.safe_link() or self.pending or p.armed or self.data.get('STATE')!='OFF': return False
        if self.supervision.second_requested() and not self.second_supported:
            self.message='Second clamp requires firmware 0.24 or newer. Disable it or update firmware.';self.changed.emit();return False
        values=self.configuration_values()
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
        commands.update(second_engage='DCLAMP2 1',second_release='DCLAMP2 0')
        if action=='cycle' and self.second_supported and self.cycle_clamp_mask()!=1:
            commands['cycle']=f"DCUTM {self.token} {(int(self.data.get('REQ','0'))+1)&0xffffffff} {self.cycle_clamp_mask()}"
        if action=='cycle' and self.sequence and self.sequence.get('automatic_cut_return'):
            s=self.sequence
            commands['cycle']=f"DCUTRET {self.token} {(int(self.data.get('REQ','0'))+1)&0xffffffff} {self.cycle_clamp_mask()} {s['cut_return_target']} {s['cut_return_min']}"
        if action=='return_operator_cycle':commands[action]=f"DRETURN {self.token} {(int(self.data.get('REQ','0'))+1)&0xffffffff} {self.owner.carriage_tab.x['MOVE_ID']}"
        command=(f"DOPCUT {self.token} {(int(self.data.get('REQ','0'))+1)&0xffffffff}" if action=='operator_cycle' else commands.get(action,''))
        if not self.allowed(command):
            if action=='cycle' and self.supervision.last_decision:
                self.message=self.supervision.last_decision.reason
                self.changed.emit()
            return False
        expected=(int(self.data.get('REQ','0'))+1)&0xffffffff
        if not self.owner.send_command(command): return False
        if action in ('cycle','operator_cycle','return_operator_cycle'):
            s = self.sequence
            index = s['index'] if s else None
            self.owner.cut_history.prepare_cycle(
                expected_done=(int(self.data['DONE'])+1)&0xffffffff,
                mode='auto' if s else 'manual',
                cut_type='truing' if index == -1 else 'cut',
                cut_number=index+1 if index is not None and index >= 0 else None,
                length=(s['kerf'] if index == -1 else
                        s.get('adjusted_length',s['cuts'][index]) if s else None),
                length_source='truing_kerf' if index == -1 else
                              'operator_adjusted_feed_estimate' if s and 'adjusted_length' in s else 'cut_list_target' if s else 'unknown_manual_length',
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
            compatible=(self.owner.carriage_tab.compatible and f.get('FW') in ('0.22.0','0.23.0','0.24.0','0.25.0','0.26.0','0.27.0')
                        and f.get('DRY_RUN')=='UNLOADED_V6' and f.get('BLADE_LOCK')=='UNPLUGGED_CYCLE'
                        and f.get('TRIGGER_TEST')=='HOLD_V1' and f.get('CYCLE')=='CLAMP_TRIGGER_TRAVEL_V1'
                        and f.get('OPERATOR_CUT')=='UNCLAMPED_ONESHOT_V1')
            if self.compatible and not compatible: self.stop('Dry-run identity changed')
            self.compatible=compatible
            compatible=compatible and (f.get('FW') not in ('0.25.0','0.26.0','0.27.0') or (self.owner.carriage_tab.continuous_supported() and self.owner.carriage_tab.parallel_supported()))
            compatible=compatible and (f.get('FW') not in ('0.26.0','0.27.0') or self.owner.carriage_tab.automatic_return_supported())
            compatible=compatible and (f.get('FW')!='0.27.0' or f.get('RECOVERY')=='COUNTED_STOP_V1')
            self.compatible=compatible
            supported=compatible and f.get('FW') in ('0.24.0','0.25.0','0.26.0','0.27.0') and f.get('SECOND_CLAMP')=='D18_MASK_V1'
            if self.second_supported and not supported:self.stop('Second-clamp capability changed')
            self.second_supported=supported
        elif message.kind=='BENCH_DRY':
            try:
                valid=(f.get('PROTO')=='6' and f.get('LOCK') in ('0','1') and f.get('TRIGGER') in ('0','1')
                       and f.get('MANUAL') in ('0','1') and f.get('OPERATOR') in ('0','1')
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
                cycle_phases={'SPINUP','DOWN_DELAY','DESCEND','DOWN','DWELL','UP_DELAY','RETURN','UP_SETTLE','TRIGGER_RELEASE_DELAY'}
                cycle_trigger=phase in cycle_phases
                manual_travel=(f['MANUAL']=='1' and f['CYCLE']=='0' and phase in
                               {'DOWN_DELAY','DESCEND','DOWN','DWELL','UP_DELAY','RETURN','UP_SETTLE'})
                operator_cycle=f['OPERATOR']=='1'
                valid=(f['ARMED']==('0' if phase in {'OFF','STOP_RETURN','STOPPED','FAULT'} else '1')
                       and (not operator_cycle or (f['CYCLE']=='1' and f['CLAMP']=='0' and f['MANUAL']=='0' and phase in cycle_phases|{'TRIGGER_DELAY','BRAKE_WAIT'}))
                       and (recovering or manual_travel or operator_cycle or
                            (self.second_supported and phase in ('CLAMP_DELAY','CLAMP_SETTLE','RELEASE_DELAY','RELEASE_CLEAR')) or
                            f['CLAMP']==str(int(clamped))) and f['SAW']==str(int(lowered))
                       and (f['FAULT']!='NONE')==(phase=='FAULT')
                       and f['LOCK']==('0' if f['MANUAL']=='1' or f['CYCLE']=='1' else '1')
                       and (f['MANUAL']=='0' or f['ARMED']=='1')
                       and (f['CYCLE']=='0' or (f['ARMED']=='1' and phase not in ('READY','CLAMPED')))
                       and (f['CYCLE']!='1' or f['TRIGGER']==str(int(cycle_trigger)))
                       and (f['TRIGGER']=='0' or f['CYCLE']=='1' or (f['MANUAL']=='1' and phase in ('READY','CLAMPED') and f['SAW']=='0'))
                       and (f['RELEASE_READY']=='0' or (phase in ('STOPPED','FAULT') and f['CLAMP']=='1')))
            if valid and self.second_supported:
                try:
                    mask,plan=int(f['CLAMP_MASK']),int(f['PLAN_MASK'])
                    valid=(0<=mask<=3 and 0<=plan<=3 and f['SECOND_ENABLED'] in ('0','1')
                           and f['MAIN_CLAMP']==str(int(bool(mask&1))) and f['SECOND_CLAMP']==str(int(bool(mask&2)))
                           and f['CLAMP']==str(int(bool(mask)))
                           and (f['SECOND_ENABLED']=='1' or not ((mask|plan)&2))
                           and (f['CYCLE']=='0' or f['OPERATOR']=='1' or phase in ('CLAMP_DELAY','CLAMP_SETTLE','RELEASE_DELAY','RELEASE_CLEAR') or mask==plan))
                except (KeyError,ValueError):valid=False
            if not valid:
                self.stop('Invalid dry-run readback'); return
            if self.data and int(f['UP_MS'])<int(self.data['UP_MS']):
                self.stop('Dry-run controller restarted'); return
            self.data=f; self.received=time.monotonic()
            if f['STATE'] in ('OFF','FAULT') and f['ARMED']=='0': self.awaiting_stop=False
            if self.token and f['CFG']==str(self.token) and self.loaded is not None and f['HASH']!=str(timing_hash(self.loaded)):
                self.stop('Controller timing readback mismatch'); return
            if self.second_supported and self.token and f['CFG']==str(self.token) and self.loaded is not None and f['SECOND_ENABLED']!=str(self.loaded[15]):
                self.stop('Second-clamp enable readback mismatch');return
            if self.pending:
                if ((self.pending['kind']=='config' and f['CFG']==str(self.token)) or
                    (self.pending['kind']=='action' and int(f['REQ'])==self.pending['req'])):
                    self.pending=None
            if f['FAULT']!='NONE':
                reason='Controller fault: '+f['FAULT']+'; clamp retained if engaged.'
                if self.sequence and (not self.intervention.recovering() or self.owner.direct_controls.intent):
                    self.stop(reason,recover_cycle=True)
                else:
                    self.pending=None;self.manual_start=None;self.auto_start=None;self.trigger_held=False
                    if self.intervention.recovering():self.intervention.observe_fault_completion()
                    else:self.message=reason
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

    def stop(self, reason='Stopped; trigger released, engaged clamp retained.', *, recover_cycle=False,discard_recovery=False):
        retain=bool(self.sequence and not discard_recovery and (recover_cycle or self.intervention.recovering() or reason!='Stopped; trigger released, engaged clamp retained.'))
        if retain:self.intervention.capture_fault(reason)
        else:self.intervention.clear()
        if hasattr(self.owner,'direct_controls'):self.owner.direct_controls.cancel()
        if self.native() and self.owner.ser and self.owner.ser.is_open:
            self.awaiting_stop=True
            old=self.issuing_sequence;self.issuing_sequence=True
            try:self.owner.send_command('OFF')
            finally:self.issuing_sequence=old
        p=self.owner.carriage_tab
        if p.armed or p.homing or p.x.get('REMAINING','0')!='0':p.stopping=True
        p.pending=None;p.profile_pending=None;p.full_home_pending=None
        if not retain:self.sequence=None
        self.pending=None; self.manual_start=None; self.auto_start=None; self.trigger_held=False; self.message=reason
        self.supervision.coordinator.invalidate('Stopped; reconcile material before another automatic cycle.')
        if reason!='Stopped; trigger released, engaged clamp retained.': self.local_fault=reason
        self.diagnostics.note('STOP', reason, time.monotonic())
        self.capture_diagnostics()
        self.changed.emit()

    def feedback_problem(self):
        """Keep the controller's cause instead of replacing it with a waiver."""
        p=self.owner.carriage_tab
        if p.local_fault:return p.local_fault
        code=p.x.get('FAULT','NONE')
        if code=='NONE':code=p.safety.get('FAULT','NONE')
        if code=='EDGE_FAILED':
            detail=p.x.get('EDGE_ERROR','UNKNOWN')
            if detail=='NOT_FOUND':
                distance=int(p.x.get('JOG_PULSES','0'))/127.12
                return f'Board detector not found after {distance:.2f} in of search. Check stock/sensor; Home before retry.'
            if detail=='TIMEOUT':return 'Board detector search timed out. Check stock/sensor and Gentle profile; Home before retry.'
            return f'Board detector acquisition failed ({detail}). Home before retry.'
        if code!='NONE':return f"Carriage fault: {code}. "+('Counted position retained; clear the cause and error before recovery.' if p.x.get('POS_KNOWN')=='1' else 'Home after resolving the cause.')
        if self.data.get('FAULT','NONE')!='NONE':return 'Controller fault: '+self.data['FAULT']
        if not self.fresh():return 'Controller cycle feedback missing or stale; action stopped.'
        for record in ('X','SAFETY','INPUTS'):
            if not p.fresh(record):return f'{record} feedback missing or stale; action stopped.'
        if p.inputs.get('FENCE_DOOR')!='0':return 'Guard door opened; action stopped.'
        if p.inputs.get('CL57T_ALM')!='1':return 'Driver alarm input active; action stopped.'
        return 'Machine interlock changed; action stopped. Check live sensor status.'

    def tick(self):
        self.sync()
        now=time.monotonic()
        if self.native() and not self.intervention.recovering() and (self.data.get('ARMED')=='1' or self.sequence):
            if not self.safe_link():
                if not self.local_fault: self.stop(self.feedback_problem())
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
                if not self.safe_link(): self.stop(self.feedback_problem())
                elif self.auto_start=='off' and now-self.auto_start_at>2: self.stop('Auto stop acknowledgment timed out')
                elif self.auto_start=='off' and self.data.get('STATE')=='OFF':
                    self.auto_start='config'
                    if not self.configure(): self.stop('Auto timing load rejected')
                elif self.auto_start=='config' and self.data.get('CFG')==str(self.token):
                    prepared=self.owner.prepare_saved_profiles()
                    if prepared is None:return
                    if not prepared:self.stop('Saved motion profiles could not be acknowledged.');return
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
                if self.intervention.recovering():
                    self.message='RECOVERY — cut list or reference settings changed. Cancel to start the edited batch.'
                    self.changed.emit();return
                self.stop('Cut list or reference settings changed; batch cancelled.');return
            if not self.supervision.coordinator.geometry.verified:
                self.stop('Supervision geometry/reference changed during sequence; no automatic restart')
                return
            self.issuing_sequence=True
            try:
                self.intervention.tick()
                if self.sequence['stage'] not in ('PAUSING','PAUSED','FAULT_RECOVERY'):self.advance_sequence()
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
        if self.native() and self.data.get('CLAMP')=='0' and self.owner.carriage_tab.ready_link() and self.owner.carriage_tab.safety.get('RESET_READY')=='1':
            self.owner.carriage_tab.acknowledge(); self.local_fault=''; self.consent.setChecked(False)
            self.trigger_consent.setChecked(False)

    def cancel_cycle(self):
        self.stop(discard_recovery=True);self.message='Cycle canceled; cut list retained. Start begins a new batch.';self.changed.emit()

    def approve_cut(self):
        if self.intervention.paused():return self.intervention.resume(approve_cut=True)
        if not self.sequence or self.sequence['stage']!='WAIT_CUT_APPROVAL' or not self.can_approve_cut():return False
        self.sequence.update(stage='DISARM',cut_approved=True,at=time.monotonic())
        self.changed.emit();return True

    def can_approve_cut(self):
        if self.intervention.paused():
            plan=self.intervention.resume_plan()
            return bool(plan and plan[0]=='cut')
        return bool(self.sequence and self.sequence['stage']=='WAIT_CUT_APPROVAL' and self.safe_link()
                    and not self.pending and not self.owner.carriage_tab.armed
                    and not self.owner.direct_controls.intent and self.data.get('STATE')=='OFF'
                    and self.supervision.review().proceeds)

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
                and p.inputs.get('BOARD_EDGE')=='1' and bool(self.owner.cut_list) and self.acquisition_command() is not None)

    def acquisition_command(self):
        """Auto gets a travel-derived bound, separate from the bench's 2 in.

        Reserve space beyond the latest possible capture for sensor + kerf
        truing and the pusher/blade keepout. Remain inside firmware soft limits.
        """
        p=self.owner.carriage_tab;g=self.supervision.coordinator.geometry
        if not g.verified or p.x.get('POS_KNOWN')!='1':return None
        try:
            sensor=float(self.owner.board_sensor_location_input.value())
            trim=float(self.owner.kerf_input.value())
            if not all(math.isfinite(v) and 0<=v<=160.5 for v in (sensor,trim)):return None
            minimum=max(g.physical_min,g.cut_keepout)+g.pusher_front_offset+1/127.12+sensor+trim
            minimum_offset=max(int(p.x['SOFT_MIN_OFFSET']),math.ceil((minimum-160.5)*127.12))
            count=min(int(p.x['MAX_MOVE']),int(p.x['HOME_OFFSET'])-minimum_offset)
            if count<1:return None
            keyword='XACQUIRE' if p.continuous_supported() else 'XEDGE'
            return f'{keyword} {count} {int(math.floor(sensor*1000+.5))} {int(math.floor(trim*1000+.5))}'
        except (ValueError,KeyError,OverflowError):return None

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
        self.sequence={'stage':'SEARCH_PROFILE','at':time.monotonic(),'cuts':cuts,'kerf':self.owner.kerf_input.value(),
                       'index':-1,'next_index':previous['next_index'] if previous else 0,
                       'board':(previous['board'] if previous.get('reacquire') else previous['board']+1) if previous else 1,
                       'semi':previous['semi'] if previous else self.owner.auto_modes.currentIndex()==1,
                       'repeat':previous['repeat'] if previous else self.owner.repeat_pattern.isChecked(),
                       'clear_between':previous['clear_between'] if previous else self.owner.clear_between_boards.isChecked(),
                       'clear_end':previous['clear_end'] if previous else self.owner.clear_at_list_end.isChecked(),
                       'list_snapshot':previous['list_snapshot'] if previous else tuple(self.owner.cut_list),
                       'reference_signature':self.supervision.current_reference_signature(),
                       'move_id':int(p.x['MOVE_ID']),
                       'edge_command':self.acquisition_command()}
        self.progress_batch=self.sequence['list_snapshot']; self.progress_index=self.sequence['next_index']
        # The explicit Run Dry List gesture authorizes this sequence's arming.
        self.issuing_sequence=True
        try: sent=p.select_profile(1)
        finally: self.issuing_sequence=False
        if not sent:
            self.stop('Cannot select Gentle acquisition profile'); return False
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
                or self.acquisition_command() is None)

    def acquisition_rejected(self, decision, context):
        """Retain the first actual rejection; capture data without actuator writes."""
        s=self.sequence
        if not s:return
        if s.get('acquisition_rejection'):return
        detail={'code':decision.code,'reason':decision.reason,'context':asdict(context),
                'decision':asdict(decision),'carriage_readback':dict(self.owner.carriage_tab.x),
                'controller_readback':dict(self.data),'inputs_raw':dict(self.owner.carriage_tab.inputs),
                'sequence_before_rejection':dict(s)}
        s['acquisition_rejection']={'code':decision.code,'reason':decision.reason}
        s['stage']='BOARD_TOO_SHORT' if decision.code=='NEXT_BOARD_REQUIRED' else 'OPERATOR_REQUIRED'
        s['at']=time.monotonic()
        self.supervision.coordinator.paused=decision
        self.supervision.last_decision=decision
        self.diagnostics.note('ACQUISITION_REJECTED',decision.code+': '+decision.reason,time.monotonic(),detail)
        try:
            folder=self.owner.cut_history.path.parent/'diagnostics'
            folder.mkdir(parents=True,exist_ok=True)
            path=folder/('acquisition-rejected-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json')
            self.diagnostics.write_report(path,time.monotonic(),{'acquisition_rejection':detail})
            s['acquisition_rejection']['snapshot_path']=str(path)
        except (OSError,ValueError,TypeError) as error:
            s['acquisition_rejection']['write_error']=str(error)
        self.owner.log.append('ACQUISITION REJECTED ['+decision.code+']: '+decision.reason+' '+
                              s['acquisition_rejection'].get('snapshot_path',s['acquisition_rejection'].get('write_error','')))
        self.message=self.acquisition_rejection_message()

    def acquisition_rejection_message(self):
        result=self.sequence['acquisition_rejection']
        message=f"Acquisition paused [{result['code']}]: {result['reason']} No saw cycle was sent."
        if result['code']=='NEXT_BOARD_REQUIRED':message+=' Load suitable stock with detector clear before starting a new acquisition.'
        if result.get('snapshot_path'):message+=' Diagnostic saved: '+result['snapshot_path']
        elif result.get('write_error'):message+=' Diagnostic could not be saved: '+result['write_error']
        return message

    def advance_sequence(self):
        # Implemented as ACK/state transitions, never PC timers commanding valve phases.
        s=self.sequence; p=self.owner.carriage_tab
        if not s or self.pending or p.profile_pending: return
        if not self.safe_link(): self.stop(self.feedback_problem()); return
        stage=s['stage']
        def next_stage(name): s['stage']=name; s['at']=time.monotonic()
        if stage=='SEARCH_PROFILE' and p.x.get('PROFILE_ID')=='1':
            if not self.owner.send_command('XARM 1'):self.stop('Cannot arm board acquisition');return
            next_stage('SEARCH_ARM')
        elif stage=='SEARCH_ARM' and p.armed and p.x.get('JOG_READY')=='1':
            if not p.request_move(s['edge_command']): self.stop('Board detector must be clear before acquisition'); return
            next_stage('SEARCH')
        elif stage=='SEARCH' and p.x.get('EDGE_VALID')=='1' and p.x.get('EDGE_STATE')=='FOUND' and (not p.armed or p.x.get('ACQUIRE_CONTINUOUS')=='1'):
            if p.x.get('ACQUIRE_CONTINUOUS')=='1':
                s['move_id']=int(p.x['MOVE_ID'])-1;next_stage('MOVE');return
            # Preview ONE next cut on the captured board. Future boards in the
            # queue do not have to fit this board's available carriage travel.
            c=self.supervision.context()
            proposed=int(p.x['TRUING_MILLI'])/1000
            material=c.material
            if material.located:
                material=replace(material,stock=material.stock.shifted(proposed-c.position))
            decision=plan_board_feed(replace(c,position=proposed,material=material),s['cuts'][s['next_index']],s['kerf'])
            if not decision.proceeds or decision.code=='NEXT_BOARD_REQUIRED':
                self.acquisition_rejected(decision,replace(c,position=proposed,material=material))
                return
            if not p.select_profile(1): self.stop('Cannot retain Gentle truing profile'); return
            next_stage('TRUE_PROFILE')
        elif stage=='TRUE_PROFILE' and p.x.get('PROFILE_ID')=='1':
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
            if s['index']==-1 and p.continuous_supported():
                reference=self.supervision.context()
                if (not reference.material.located or reference.sensor_clear is None or
                        reference.material.stock.overlaps(reference.geometry.sensor)==reference.sensor_clear):
                    self.acquisition_rejected(Decision(Outcome.OPERATOR_REQUIRED,'DETECTOR_REFERENCE_MISMATCH',
                        'Truing position reached; board detector and material reference disagree. Reconcile before the first stroke.'),reference);return
                capacity=plan_board_feed(reference,s['cuts'][s['next_index']],s['kerf'])
                if not capacity.proceeds or capacity.code=='NEXT_BOARD_REQUIRED':
                    self.acquisition_rejected(capacity,reference);return
            # Captured stock was translated by the real sensor+kerf advance.
            # Do not fabricate a new material origin to hide a truing mismatch.
            decision=self.supervision.review()
            if not decision.proceeds:
                if s['index']>=0:
                    following=s['cuts'][s['index']+1] if s['index']+1<len(s['cuts']) else None
                    plan=self.supervision.review('operator_cut',length=following,kerf=s['kerf'])
                    if plan.proceeds:
                        s['operator_stock']=self.supervision.coordinator.material.stock
                        s['operator_cut_position']=self.supervision.context().position
                        s['operator_config']=self.supervision.coordinator.config_revision
                        s['early_return']=plan.code=='OPERATOR_CUT_RETURN'
                        s['operator_confirmed']=False
                        if s['early_return']:
                            s['operator_position']=self.owner.native_load_target()
                            if s['operator_position']<=s['operator_cut_position']:
                                self.stop('Load position must be behind the positioned cut for early return.');return
                            if not self.owner.send_command('XARM 1'):self.stop('Cannot arm early return');return
                            next_stage('EARLY_RETURN_ARM')
                        else:
                            s['operator_position']=s['operator_cut_position'];next_stage('WAIT_OPERATOR_CUT')
                        return
                next_stage('OPERATOR_REQUIRED')
                self.message='Operator intervention required: '+decision.reason
                self.changed.emit(); return
            if s['semi'] and not s.pop('cut_approved',False):
                next_stage('WAIT_CUT_APPROVAL');self.message='Position ready. Jog to adjust if needed, then approve the pending stroke.';return
            s['automatic_cut_return']=False
            if s['index']>=0 and p.automatic_return_supported():
                following=s['cuts'][s['index']+1] if s['index']+1<len(s['cuts']) else None
                clear_after=s['clear_between'] if following is not None or s['repeat'] else s['clear_end']
                plan=self.supervision.review('cut_return',length=following,kerf=s['kerf'],
                                             load_position=self.owner.native_load_target(),clear_after=clear_after)
                if plan.code=='CLAMPED_CUT_RETURN':
                    g=self.supervision.coordinator.geometry
                    selected=[c for c in g.clamps if c.key in plan.permitted_clamps]
                    minimum=max([g.cut_keepout+g.pusher_front_offset]+
                                [c.footprint.far+g.margin+g.pusher_front_offset for c in selected])
                    s.update(automatic_cut_return=True,early_return=True,cut_return_plan=plan,
                             cut_return_mask=sum({'main':1,'outfeed':2}[c.key] for c in selected),
                             cut_return_target=round(plan.target*1000),cut_return_min=math.ceil(minimum*1000))
            if not self.request('arm'): self.stop('Cannot arm unloaded pneumatics'); return
            next_stage('CLAMP')
        elif stage=='CLAMP' and self.data.get('STATE')=='READY':
            s['done']=int(self.data['DONE'])
            if not self.request('cycle'): self.stop('Saw cycle rejected'); return
            next_stage('SAW_ACK')
        elif stage=='SAW_ACK':
            # REQ acknowledgment completes before this branch; next status may
            # still be DOWN_DELAY, but the cycle must actually leave CLAMPED.
            if self.data.get('CYCLE')=='1': next_stage('RETURN_CUT_WAIT' if s.get('automatic_cut_return') else 'SAW_WAIT')
        elif stage=='SAW_WAIT' and self.data.get('STATE')=='READY' and int(self.data['DONE'])!=s['done']:
            self.owner.send_command('DOFF'); next_stage('PNEU_OFF')
        elif stage=='PNEU_OFF' and self.data.get('STATE')=='OFF' and self.data.get('ARMED')=='0':
            early=s.get('early_return',False)
            s['index']=s['next_index'] if s['index']==-1 else s['index']+1
            s['next_index']=s['index']
            self.progress_index=s['next_index']
            s.pop('operator_confirmed',None)
            s.pop('adjusted_length',None)
            if self.intervention.after_cut:
                self.intervention.pause(after_cut=True);return
            if early:
                # Carriage is already at Load. Never push/cut again using a
                # material reference whose contact was lost on early return.
                s['early_return']=False;next_stage('DONE');return
            next_stage('NEXT_ACTION');return
        elif stage=='NEXT_ACTION':
            if s['index']>=len(s['cuts']):
                self.finish_board(next_stage); return
            else:
                decision=self.supervision.review('feed',length=s['cuts'][s['index']],kerf=s['kerf'])
                if decision.code=='NEXT_BOARD_REQUIRED':
                    self.finish_board(next_stage); return
                if not decision.proceeds:
                    self.stop(decision.reason); return
                s['target']=decision.target
                if not p.select_profile(2): self.stop('Cannot select Normal feed profile'); return
                next_stage('FEED_PROFILE')
        elif stage=='RESUME_POSITION_PROFILE' and p.x.get('PROFILE_ID')==str(s['resume_profile']):
            if not self.owner.send_command('XARM 1'):self.stop('Cannot arm paused positioning');return
            next_stage('FEED_ARM')
        elif stage=='WAIT_CUT_APPROVAL':
            self.message=('Truing position ready. Press True-up / advance.' if s['index']<0 else
                          f"Cut {s['index']+1} positioned. Jog to adjust if needed, then press Clamp / Cut / Advance.");return
        elif stage=='FINISH_BOARD':
            self.finish_board(next_stage);return
        elif stage=='FEED_PROFILE' and p.x.get('PROFILE_ID')=='2':
            if not self.owner.send_command('XARM 1'):self.stop('Cannot arm dry-list feed');return
            next_stage('FEED_ARM')
        elif stage=='EARLY_RETURN_ARM' and p.armed and p.x.get('JOG_READY')=='1':
            if p.parallel_supported():
                g=self.supervision.coordinator.geometry
                command=f"XRETURN {round(s['operator_position']*1000)} {math.ceil((g.cut_keepout+g.pusher_front_offset)*1000)}"
                sent=p.request_move(command)
            else:sent=p.move_load_to(s['operator_position'])
            if not sent:self.stop('Early return rejected');return
            s['move_id']=int(p.x['MOVE_ID']);next_stage('EARLY_RETURN_WAIT')
        elif stage=='EARLY_RETURN_WAIT' and not p.pending and int(p.x['MOVE_ID'])!=s['move_id'] and p.x.get('REMAINING')=='0':
            self.owner.send_command('XARM 0');next_stage('EARLY_RETURN_DISARM')
        elif stage=='EARLY_RETURN_DISARM' and not p.armed and not p.stopping:
            if not self.operator_snapshot_valid():self.stop('Early-return stock/detector reference changed.');return
            next_stage('WAIT_OPERATOR_CUT')
        elif stage=='RETURN_CUT_ACK':
            if self.data.get('CYCLE')=='1' or int(self.data['DONE'])!=s['done']:next_stage('RETURN_CUT_WAIT')
        elif stage=='RETURN_CUT_WAIT':
            self.message=('Last cut: settling clamps, then Fast carriage return; waiting for cut and return to finish.'
                          if s.get('automatic_cut_return') else 'Operator cut running while carriage returns; waiting for both to finish.')
            if (p.x.get('RETURN_AT_LOAD')=='1' and not p.armed and p.x.get('REMAINING')=='0' and
                    self.data.get('STATE')=='READY' and self.data.get('CYCLE')=='0' and int(self.data['DONE'])!=s['done']):
                self.owner.send_command('DOFF');next_stage('PNEU_OFF')
        elif stage=='WAIT_OPERATOR_CUT':
            if s['early_return'] and self.supervision.context().sensor_clear is not True:
                self.message='PENDING CUT — detector is blocked. Finish this cut before loading the next board; no stroke will start.'
                return
            self.message=('WAITING FOR OPERATOR — secure unclamped wood, then press Wood secured / run cut. '
                          +('Carriage is at Load. Load the next board after this cut finishes.' if s['early_return'] else
                            'Carriage stays forward; more cuts fit this board.')+' Saw mains stay unplugged.')
            return
        elif stage=='OPERATOR_ARM' and not p.armed:
            if not self.operator_snapshot_valid():self.stop('Operator cut reference changed; action cancelled.');return
            if not self.request('arm'):self.stop('Cannot prepare operator-controlled stroke');return
            next_stage('OPERATOR_ARMED')
        elif stage=='OPERATOR_ARMED' and self.data.get('STATE')=='READY':
            s['done']=int(self.data['DONE'])
            if not self.request('operator_cycle'):self.stop('Operator-controlled stroke rejected');return
            s['operator_confirmed']=False;next_stage('SAW_ACK')
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
            if s['next_index']>=len(s['cuts']) and s['repeat']:
                s['index']=s['next_index']=0;self.progress_index=0
            if s['next_index']<len(s['cuts']):
                next_stage('WAIT_NEW_BOARD')
                self.message=f"Board {s['board']} complete. Load the next board; next cut is {s['next_index']+1}. Press Start next board when ready."
            else:
                self.sequence=None; self.message='Unloaded dry list complete; production cut-list progress unchanged.'
            return
        elif stage in ('BOARD_TOO_SHORT','OPERATOR_REQUIRED') and s.get('acquisition_rejection'):
            self.message=self.acquisition_rejection_message()
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
            label = (f"SEARCH — Gentle approach, up to {int(s['edge_command'].split()[1])/127.12:.2f} in; waiting for board detector"
                     if s['stage']=='SEARCH' else s['stage'])
            self.message=f"Dry list board {s['board']}: {label} — {'truing' if s['index']<0 else 'cut '+str(s['index']+1)}; saw mains MUST stay unplugged."
            if time.monotonic()-s['at']>180:
                self.stop('Dry-list phase exceeded 180 seconds')

    def finish_board(self, next_stage):
        """Same bounded cleanup/verified return at end of EACH board."""
        s=self.sequence; p=self.owner.carriage_tab
        clear=s['clear_between'] if (s['repeat'] or s['next_index']<len(s['cuts'])) else s['clear_end']
        if not clear:
            if not self.owner.send_command('XARM 1'):self.stop('Cannot arm return with remainder retained');return
            next_stage('LOAD_ARM');return
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

    def operator_snapshot_valid(self,allow_return=False):
        s=self.sequence;p=self.owner.carriage_tab;c=self.supervision.context()
        if not s or 'operator_stock' not in s:return False
        returning=(allow_return and s.get('early_return') and p.parallel_supported() and p.x.get('RETURN_PERMIT')=='1'
                   and p.x.get('DIR')=='1' and p.x.get('RETURN_USED')=='0' and p.x.get('REMAINING')!='0'
                   and c.position is not None
                   and s['operator_cut_position']<=c.position<=s['operator_position']+.02)
        return (self.safe_link(False) and self.batch_unchanged() and c.reference_known and (c.carriage_idle or returning)
                and c.saw_up and c.trigger_off and c.clamps_off and c.fault_free and c.door_closed
                and c.config_revision==s['operator_config'] and c.material.located
                and c.material.stock==s['operator_stock']
                and c.sensor_clear is not None and c.material.stock.overlaps(c.geometry.sensor)!=c.sensor_clear
                and (returning or abs(c.position-s['operator_position'])<.02)
                and (not s['early_return'] or c.sensor_clear is True)
                and self.data.get('CLAMP')=='0' and self.data.get('SAW')=='0' and self.data.get('TRIGGER')=='0')

    def can_confirm_operator_cut(self):
        if self.sequence and self.sequence['stage']=='EARLY_RETURN_WAIT':
            return bool(not self.pending and self.owner.carriage_tab.armed and self.operator_snapshot_valid(True)
                        and self.data.get('STATE')=='OFF' and self.data.get('ARMED')=='0')
        return bool(self.sequence and self.sequence['stage']=='WAIT_OPERATOR_CUT' and not self.pending
                    and not self.owner.carriage_tab.armed and self.operator_snapshot_valid()
                    and self.data.get('STATE')=='OFF' and self.data.get('ARMED')=='0')

    def confirm_operator_cut(self):
        if not self.can_confirm_operator_cut():return False
        if self.sequence['stage']=='EARLY_RETURN_WAIT':
            s=self.sequence;s['operator_confirmed']=True;s['done']=int(self.data['DONE'])
            old=self.issuing_sequence;self.issuing_sequence=True
            try:sent=self.request('return_operator_cycle')
            finally:self.issuing_sequence=old
            s['operator_confirmed']=False
            if not sent:return False
            s.update(stage='RETURN_CUT_ACK',at=time.monotonic());self.changed.emit();return True
        self.sequence.update(operator_confirmed=True,stage='OPERATOR_ARM',at=time.monotonic())
        self.supervision.coordinator.paused=None
        self.diagnostics.note('OPERATOR_CUT_REQUEST','One unplugged stroke requested; main clamp inhibited, grip not measured.',time.monotonic(),
                              {'cut_index':self.sequence['index'],'early_return':self.sequence['early_return'],
                               'cut_position':self.sequence['operator_cut_position'],'carriage_position':self.supervision.context().position})
        self.message='Operator requested one unplugged stroke; main clamp inhibited.'
        self.changed.emit();return True
