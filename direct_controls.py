"""One operator gesture -> acknowledged preparation -> one requested action.

No action on connection, no replay after Stop/fault/reconnect. Physical state
guards remain at both the app serial boundary and the controller.
"""
import math
import time
from PyQt6.QtCore import QObject
from automation_supervision import assess_manual_cycle


class DirectControls(QObject):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner=owner
        self.intent=None
        self.message=''

    def cancel(self):
        self.intent=None
        self.message=''

    def preparing_trigger(self):
        return bool(self.intent and self.intent['kind']=='actuator' and self.intent['value']=='press')

    def base_ready(self):
        d=self.owner.dry_run; p=self.owner.carriage_tab
        return (d.safe_link(False) and (not d.sequence or d.intervention.manual_window()) and not d.auto_start and not d.awaiting_stop
                and not p.pending and not p.profile_pending and not p.stopping
                and not p.homing and not p.edge_searching and not p.full_home_pending and p.x.get('REMAINING')=='0')

    def free_for_carriage(self):
        d=self.owner.dry_run; p=self.owner.carriage_tab
        return (self.base_ready() and not self.intent and not d.pending and not d.manual_start
                and d.data.get('CLAMP')=='0' and d.data.get('SAW')=='0' and d.data.get('TRIGGER')=='0'
                and d.data.get('STATE') in ('OFF','READY')
                and p.inputs.get('SAW_UP')=='0' and p.inputs.get('SAW_DOWN')=='1')

    def can_motion(self, kind='move'):
        ready=self.free_for_carriage() and (kind=='home' or self.owner.carriage_tab.x.get('POS_KNOWN')=='1')
        if kind=='auto':
            ready=ready and not self.owner.dry_run.sequence and self.owner.dry_run.supervision.coordinator.geometry.verified and bool(self.owner.cut_list) and self.owner.carriage_tab.inputs.get('BOARD_EDGE')=='1' and self.owner.dry_run.acquisition_command() is not None
        return bool(ready)

    def can_actuator(self, action):
        d=self.owner.dry_run; p=self.owner.carriage_tab
        if d.sequence or not self.base_ready() or self.intent or d.pending or d.manual_start:return False
        state=d.data.get('STATE')
        if action=='unpress':return d.data.get('TRIGGER')=='1'
        if action=='release' and d.data.get('RELEASE_READY')=='1':return True
        if action=='up':return state in ('DOWN_DELAY','DESCEND','DOWN','DWELL','UP_DELAY')
        if state not in ('OFF','READY','CLAMPED') or d.data.get('TRIGGER')!='0':return False
        if p.inputs.get('SAW_UP')!='0' or p.inputs.get('SAW_DOWN')!='1':return False
        if action in ('second_engage','second_release'):
            if not d.second_supported or not d.supervision.second_requested():return False
            held=d.data.get('SECOND_CLAMP')=='1'
            return state in ('OFF','READY','CLAMPED') and (held if action=='second_release' else
                        not held and d.supervision.individual_clamp_allowed('outfeed'))
        if action=='release':return state=='CLAMPED' and d.data.get('MAIN_CLAMP',d.data.get('CLAMP'))=='1'
        if action=='engage':return state in ('OFF','READY','CLAMPED') and d.data.get('MAIN_CLAMP',d.data.get('CLAMP'))=='0' and d.supervision.individual_clamp_allowed()
        if action=='lower':
            c=d.supervision.context()
            return (c.reference_known and (not c.geometry.verified or c.geometry.pusher(c.position).near>c.geometry.cut_keepout)
                    and d.supervision.individual_clamp_allowed())
        if action=='cycle':return assess_manual_cycle(d.supervision.context()).proceeds
        return action=='press'

    def request(self, kind, value=None):
        if kind=='actuator' and value=='press' and not self.owner.dry_run.operator_holding_trigger():return False
        allowed=self.can_actuator(value) if kind=='actuator' else self.can_motion(kind)
        if not allowed:
            p=self.owner.carriage_tab; d=self.owner.dry_run
            self.message=('Home first.' if kind!='actuator' and p.x.get('POS_KNOWN')!='1' and kind!='home' else
                          'Return saw UP, release trigger and clamp before carriage movement.' if kind!='actuator' else
                          assess_manual_cycle(d.supervision.context()).reason if value=='cycle' else
                          'Waiting for the machine state required by this action.')
            self.owner.log.append('CONTROL: '+self.message)
            return False
        if kind in ('move','load'):
            maximum=int(self.owner.carriage_tab.x.get('SOFT_MAX_MILLI','0'))/1000
            if not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=maximum:
                self.message=f'Enter a carriage target from 0 to {maximum:.3f} inches.';return False
        if kind=='jog' and (not math.isfinite(value) or not 0<abs(value)<=2):return False
        if kind in ('home','move','load','jog') and self.owner.dry_run.sequence:
            intervention=self.owner.dry_run.intervention
            if not intervention.paused():
                if not intervention.pause():return False
                self.intent={'kind':kind,'value':value,'phase':'wait_pause','at':time.monotonic(),'session':self.owner.ser}
                self.message='Pausing before the requested manual adjustment.';return True
        self.intent={'kind':kind,'value':value,'phase':'prepare','at':time.monotonic(),'session':self.owner.ser}
        self.message='Preparing '+(str(value) if kind=='actuator' else kind)+'…'
        self.tick()
        return True

    def fail(self, reason):
        self.intent=None;self.message=reason
        self.owner.dry_run.stop(reason)

    def tick(self):
        s=self.intent
        if not s:return
        d=self.owner.dry_run;p=self.owner.carriage_tab
        if self.owner.ser is not s['session'] or not d.safe_link(False):
            self.fail('Control feedback/interlock lost; action cancelled.');return
        if s['phase'] not in ('running','finish') and time.monotonic()-s['at']>10:
            self.fail('Control preparation did not complete; action cancelled.');return
        if s['phase']=='wait_pause':
            if not d.intervention.paused() or d.awaiting_stop:return
            s['phase']='prepare'
        if self.dispatch_ready_move():return
        old=d.issuing_sequence;d.issuing_sequence=True
        try:
            kind,value=s['kind'],s['value']
            if s['phase']=='running':
                if p.pending or p.profile_pending or p.full_home_pending or p.homing or p.x.get('REMAINING')!='0':return
                if kind=='home':
                    if p.x.get('HOME_STATE')!='DONE':return
                elif p.x.get('MOVE_ID')==s['move_id']:return
                if p.armed:
                    if not self.owner.send_command('XARM 0'):self.fail('Cannot finish carriage action.');return
                    s['phase']='finish';return
                self.intent=None;self.message='Home complete.' if kind=='home' else 'Carriage move complete.';return
            if s['phase']=='finish':
                if not p.armed:self.intent=None;self.message='Carriage move complete.'
                return
            if p.pending or p.profile_pending or d.pending or d.manual_start:return
            if kind=='actuator' and value=='release' and d.data.get('RELEASE_READY')=='1':
                if not d.request('recover_release'):self.fail('Clamp cannot release until UP and brake wait complete.')
                else:self.intent=None;self.message='Releasing clamp.'
                return
            if kind=='actuator' and value in ('up','unpress'):
                if not d.request(value):self.fail('Requested recovery action is not available.')
                else:self.intent=None;self.message='Returning UP.' if value=='up' else 'Trigger released.'
                return
            if kind=='actuator' and d.data.get('MANUAL')=='1' and (d.settings_match() or value=='release'):
                if value=='press' and not d.operator_holding_trigger():self.cancel();return
                if not d.request(value):self.fail('Requested actuator action is not available.')
                else:self.intent=None;self.message='Requested '+value+'.'
                return
            # Transfer ownership only when all actuator outputs are clear.
            if p.armed:
                if not self.owner.send_command('XARM 0'):self.fail('Cannot release carriage control.')
                return
            if d.data.get('STATE')!='OFF' or d.data.get('ARMED')=='1':
                if any(d.data.get(k)!='0' for k in ('CLAMP','SAW','TRIGGER')):
                    self.fail('Return saw UP and release clamp/trigger before changing control.');return
                if not self.owner.send_command('DOFF'):self.fail('Cannot release actuator control.')
                return
            if kind=='actuator':
                if not d.enable_manual():self.fail('Actuator preparation is blocked by current feedback.')
                return
            p.consent.setChecked(True)  # internal authorization for this gesture only
            if kind=='auto':
                self.intent=None
                if not d.begin_auto():self.message='Auto needs Home, a clear detector and a cut list.'
                return
            if p.x.get('CONFIGURED')!='1':
                if not self.owner.send_command('XCONFIG 0 1'):self.fail('Driver setup rejected.')
                return
            if kind=='home':
                desired=tuple(int(v) for v in p.home_preferences())
                actual=(int(p.x.get('HOME_RATE_PPS','40')),int(p.x.get('HOME_ACCEL_PPS2','200')))
                if p.home_profile_supported and desired!=actual:
                    if not p.edit_home_profile(*desired):self.fail('Homing settings could not be loaded.')
                    return
                if not p.full_home():self.fail('Home is blocked by current machine feedback.');return
                s['phase']='running';return
            profile=3 if kind=='load' else 2
            if p.x.get('PROFILE_ID')!=str(profile):
                if not p.select_profile(profile):self.fail('Motion profile could not be selected.')
                return
            # The next phase sends exactly this one target after ready readback.
            if not self.owner.send_command('XARM 1'):self.fail('Carriage preparation rejected.');return
            s['phase']='move_ready'
        finally:d.issuing_sequence=old

    def dispatch_ready_move(self):
        s=self.intent
        if not s or s['phase']!='move_ready':return False
        d=self.owner.dry_run;p=self.owner.carriage_tab
        if not p.armed or p.x.get('JOG_READY')!='1':return True
        old=d.issuing_sequence;d.issuing_sequence=True
        try:
            s['move_id']=p.x.get('MOVE_ID')
            method={'move':p.move_to,'load':p.move_load_to,'jog':p.jog_distance}[s['kind']]
            if not method(s['value']):self.fail('Requested carriage target was rejected.');return True
            s['phase']='running';self.message='Carriage moving.'
        finally:d.issuing_sequence=old
        return True
