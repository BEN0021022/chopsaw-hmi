"""Acknowledged native unloaded-pneumatic adapter and real-input cut-list runner."""
import math
import re
import secrets
import time
from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QCheckBox, QPushButton
from sensor_bench.protocol import parse_line
from simulator import VirtualController

TIMING_KEYS = ('board.settle','main.engage_delay','main.engage_settle','main.release_delay',
               'main.release_clearance','saw.down_delay','saw.down_timeout','saw.bottom_dwell',
               'saw.up_delay','saw.up_timeout','saw.up_settle')
STATES = {'OFF','READY','CLAMP_DELAY','CLAMP_SETTLE','CLAMPED','RELEASE_DELAY','RELEASE_CLEAR',
          'DOWN_DELAY','DESCEND','DOWN','DWELL','UP_DELAY','RETURN','UP_SETTLE','STOP_RETURN','FAULT'}
TRAVEL = {'DESCEND','DOWN','DWELL','UP_DELAY','RETURN','UP_SETTLE','STOP_RETURN'}
COMMAND = re.compile(r'(?:DSET ([0-9]+) ([0-9]+)|DCOMMIT ([0-9]+)|DARM ([0-9]+)|DCLAMP ([01])|DCYCLE|DDOWN|DUP|DOFF|DMANUAL ([0-9]+)|DTHOLD|DTPRESS|DTRELEASE)')


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
        self.trigger_held = False
        self.last_trigger_hold = 0
        self.message = 'Connect matching 0.18.0 unloaded-test firmware.'
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
        note=QLabel('UNPOWERED TEST ONLY — saw mains physically unplugged; no stock.')
        note.setWordWrap(True); layout.addWidget(note)
        self.enable_manual_button=QPushButton('Enable unpowered manual controls')
        self.enable_manual_button.clicked.connect(self.enable_manual)
        layout.addWidget(self.enable_manual_button)
        self.label = QLabel(self.message); self.label.setWordWrap(True)
        self.label.setStyleSheet('color:#fbbf24;font-size:13px;'); layout.addWidget(self.label)
        return self.widget

    def native(self):
        return self.owner.is_connected() and not isinstance(self.owner.ser,VirtualController) and self.owner.carriage_tab.connected

    def sync(self):
        session = (self.owner.ser, self.native())
        if session != self.session:
            self.session = session; self.compatible=False; self.data={}; self.received=None
            self.token=0; self.loaded=None; self.pending=None; self.awaiting_stop=False; self.local_fault=''; self.sequence=None
            self.manual_start=None; self.trigger_held=False
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
        return self.native() and (bool(self.manual_start) or self.awaiting_stop or self.sequence is not None or bool(self.local_fault) or
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
        return (self.safe_link(False) and not self.pending and not self.manual_start and not self.sequence
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
        return (self.safe_link() and not self.pending and not self.sequence and not self.awaiting_stop
                and self.settings_match() and self.data.get('CFG')==str(self.token)
                and self.data.get('MANUAL')=='1' and self.data.get('STATE') in ('READY','CLAMPED')
                and self.data.get('TRIGGER')=='0' and p.inputs.get('SAW_UP')=='0'
                and p.inputs.get('SAW_DOWN')=='1')

    def begin_trigger_hold(self):
        self.trigger_held=True
        if self.request('press'): return True
        self.trigger_held=False; return False

    def end_trigger_hold(self):
        was_held=self.trigger_held
        self.trigger_held=False
        if was_held or self.data.get('TRIGGER')=='1': self.request('unpress')

    def allowed(self, command):
        if command=='DOFF': return self.native() and self.compatible
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
        if self.data.get('TRIGGER')!='0': return False
        if command=='DCLAMP 0': return state=='CLAMPED'
        if command=='DUP': return state in {'DOWN_DELAY','DESCEND','DOWN','DWELL','UP_DELAY'}
        if not self.settings_match(): return False
        if command=='DCLAMP 1': return state=='READY'
        return command in ('DCYCLE','DDOWN') and state=='CLAMPED'

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
        commands={'arm':f'DARM {self.token}','engage':'DCLAMP 1','release':'DCLAMP 0',
                  'lower':'DDOWN','up':'DUP','cycle':'DCYCLE','manual_arm':f'DMANUAL {self.token}',
                  'press':'DTPRESS','unpress':'DTRELEASE'}
        command=commands.get(action,'')
        if not self.allowed(command): return False
        expected=(int(self.data.get('REQ','0'))+1)&0xffffffff
        if not self.owner.send_command(command): return False
        self.pending={'kind':'action','req':expected,'at':time.monotonic()}
        self.message='Waiting for controller acknowledgment.'; self.changed.emit(); return True

    def handle(self, line):
        self.sync()
        if not self.native(): return
        message=parse_line(line)
        if not message: return
        f=message.fields
        if message.kind=='BENCH_HELLO':
            compatible=(self.owner.carriage_tab.compatible and f.get('FW')=='0.18.0'
                        and f.get('DRY_RUN')=='UNLOADED_V3' and f.get('BLADE_LOCK')=='MANUAL_HOLD'
                        and f.get('TRIGGER_TEST')=='HOLD_V1')
            if self.compatible and not compatible: self.stop('Dry-run identity changed')
            self.compatible=compatible
        elif message.kind=='BENCH_DRY':
            try:
                valid=(f.get('PROTO')=='3' and f.get('LOCK') in ('0','1') and f.get('TRIGGER') in ('0','1')
                       and f.get('MANUAL') in ('0','1')
                       and f.get('STATE') in STATES and f.get('ARMED') in ('0','1')
                       and f.get('CLAMP') in ('0','1') and f.get('SAW') in ('0','1') and bool(f.get('FAULT'))
                       and all(0<=int(f[k])<=0xffffffff for k in ('CFG','HASH','REQ','UP_MS')))
            except (KeyError,ValueError): valid=False
            if valid:
                phase=f['STATE']
                clamped=phase in {'CLAMP_SETTLE','CLAMPED','RELEASE_DELAY','DOWN_DELAY','DESCEND','DOWN','DWELL','UP_DELAY','RETURN','UP_SETTLE'}
                lowered=phase in {'DESCEND','DOWN','DWELL','UP_DELAY'}
                valid=(f['ARMED']==('0' if phase in {'OFF','STOP_RETURN','FAULT'} else '1')
                       and f['CLAMP']==str(int(clamped)) and f['SAW']==str(int(lowered))
                       and (f['FAULT']!='NONE')==(phase=='FAULT')
                       and f['LOCK']==('0' if f['MANUAL']=='1' else '1')
                       and (f['MANUAL']=='0' or f['ARMED']=='1')
                       and (f['TRIGGER']=='0' or (f['MANUAL']=='1' and phase in ('READY','CLAMPED') and f['SAW']=='0')))
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
                self.sequence=None; self.pending=None; self.manual_start=None; self.trigger_held=False; self.message='Controller fault: '+f['FAULT']
            elif not self.local_fault and not self.sequence and not self.message.startswith('Unloaded dry list complete'):
                trigger=('PRESSED while held (commanded)' if f['TRIGGER']=='1' else
                         'released; hold-to-test ready' if f['MANUAL']=='1' else 'locked OFF')
                self.message='Unloaded dry run: '+f['STATE']+'; trigger '+trigger+'.'
        elif message.kind=='BENCH_ERROR' and f.get('CODE','').startswith(('DRY_','BLADE_')):
            self.stop('Controller rejected dry-run request: '+f.get('CODE','UNKNOWN'))
        self.changed.emit()

    def stop(self, reason='Stopped; unloaded clamp released.'):
        if self.native() and self.owner.ser and self.owner.ser.is_open:
            self.awaiting_stop=True
            self.owner.send_command('OFF')
        self.sequence=None; self.pending=None; self.manual_start=None; self.trigger_held=False; self.message=reason
        if reason!='Stopped; unloaded clamp released.': self.local_fault=reason
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
        if self.trigger_held:
            if not self.operator_holding_trigger(): self.end_trigger_hold()
            elif self.data.get('TRIGGER')=='1' and now-self.last_trigger_hold>=.1:
                self.owner.send_command('DTHOLD'); self.last_trigger_hold=now
            elif not self.pending and self.data.get('TRIGGER')=='0':
                # An expired/lost hold never presses itself again.
                self.trigger_held=False
        if self.sequence:
            self.issuing_sequence=True
            try: self.advance_sequence()
            finally: self.issuing_sequence=False
        if hasattr(self,'label'):
            self.label.setText(self.message)
            self.configure_button.setEnabled(self.safe_link() and not self.pending and not self.owner.carriage_tab.armed and self.data.get('STATE')=='OFF')
            self.arm_button.setEnabled(self.allowed(f'DARM {self.token}'))
            self.enable_manual_button.setText('Disable manual controls / release' if self.data.get('MANUAL')=='1' else
                                             'Enabling manual controls…' if self.manual_start else 'Enable unpowered manual controls')
            self.enable_manual_button.setEnabled(self.can_enable_manual() or self.data.get('MANUAL')=='1')
        if hasattr(self.owner,'auto_dry_run'):
            self.owner.auto_dry_status.setText(self.message)
            self.owner.auto_dry_run.setEnabled(self.can_start())
            self.owner.auto_dry_configure.setEnabled(self.configure_button.isEnabled() and not self.sequence)
            self.owner.auto_dry_stop.setEnabled(self.native() and self.compatible)
        self.changed.emit()

    def acknowledge(self):
        if self.native() and self.owner.carriage_tab.ready_link() and self.owner.carriage_tab.safety.get('RESET_READY')=='1':
            self.owner.carriage_tab.acknowledge(); self.local_fault=''; self.consent.setChecked(False)
            self.trigger_consent.setChecked(False)

    def start_sequence(self):
        p=self.owner.carriage_tab
        if not self.can_start(): return False
        cuts=[float(length) for _,length,_ in self.owner.cut_list]
        if any(not math.isfinite(x) or x<=0 for x in cuts): return False
        self.sequence={'stage':'SEARCH_ARM','at':time.monotonic(),'cuts':cuts,'kerf':self.owner.kerf_input.value(),
                       'index':-1,'move_id':int(p.x['MOVE_ID']),
                       'edge_command':f'XEDGE {int(math.floor(p.edge_search.value()*127.12+.5))} '
                                      f'{int(math.floor(self.owner.board_sensor_location_input.value()*1000+.5))} '
                                      f'{int(math.floor(p.trim_overlap.value()*1000+.5))}'}
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
        return not (not self.safe_link() or self.awaiting_stop or self.pending or self.sequence or not self.settings_match() or
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
            minimum=(sum(s['cuts'])+len(s['cuts'])*s['kerf'])*1000
            if int(p.x['TRUING_MILLI'])<minimum:
                self.stop('Cut list exceeds available referenced travel'); return
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
            if not self.request('arm'): self.stop('Cannot arm unloaded pneumatics'); return
            next_stage('CLAMP')
        elif stage=='CLAMP' and self.data.get('STATE')=='READY':
            if not self.request('engage'): self.stop('Clamp request rejected'); return
            next_stage('CLAMP_WAIT')
        elif stage=='CLAMP_WAIT' and self.data.get('STATE')=='CLAMPED':
            if not self.request('cycle'): self.stop('Saw cycle rejected'); return
            next_stage('SAW_ACK')
        elif stage=='SAW_ACK':
            # REQ acknowledgment completes before this branch; next status may
            # still be DOWN_DELAY, but the cycle must actually leave CLAMPED.
            if self.data.get('STATE')!='CLAMPED': next_stage('SAW_WAIT')
        elif stage=='SAW_WAIT' and self.data.get('STATE')=='CLAMPED':
            if not self.request('release'): self.stop('Clamp release rejected'); return
            next_stage('RELEASE_WAIT')
        elif stage=='RELEASE_WAIT' and self.data.get('STATE')=='READY':
            self.owner.send_command('DOFF'); next_stage('PNEU_OFF')
        elif stage=='PNEU_OFF' and self.data.get('STATE')=='OFF' and self.data.get('ARMED')=='0':
            s['index']+=1
            if s['index']>=len(s['cuts']):
                if not self.owner.send_command('XARM 1'): self.stop('Cannot arm carriage return'); return
                next_stage('LOAD_ARM')
            else:
                s['target']=160.5+int(p.x['HOME_OFFSET'])/127.12-s['cuts'][s['index']]-s['kerf']
                if s['target']<0 or not self.owner.send_command('XARM 1'):
                    self.stop('Dry-list feed target outside travel'); return
                next_stage('FEED_ARM')
        elif stage=='LOAD_ARM' and p.armed and p.x.get('JOG_READY')=='1':
            if not p.move_load_to(self.owner.native_load_target()): self.stop('Return-to-load rejected'); return
            s['move_id']=int(p.x['MOVE_ID']); next_stage('LOAD_WAIT')
        elif stage=='LOAD_WAIT' and not p.pending and int(p.x['MOVE_ID'])!=s['move_id'] and p.x.get('REMAINING')=='0':
            self.owner.send_command('XARM 0'); next_stage('DONE')
        elif stage=='DONE' and not p.armed:
            self.sequence=None; self.message='Unloaded dry list complete; production cut-list progress unchanged.'; return
        if self.sequence:
            label = ('SEARCH — trip and hold the real board detector until truing starts' if s['stage']=='SEARCH' else s['stage'])
            self.message=f"Dry list: {label} — {'truing' if s['index']<0 else 'cut '+str(s['index']+1)}; blade locked OFF."
            if time.monotonic()-s['at']>180:
                self.stop('Dry-list phase exceeded 180 seconds')
