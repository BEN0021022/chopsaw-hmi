"""Paused-list ownership and explicit manual repositioning; no pulse generation."""
import time
from dataclasses import replace


class CycleIntervention:
    def __init__(self, dry):
        self.dry=dry
        self.checkpoint=None
        self.after_cut=False

    def clear(self):
        self.checkpoint=None;self.after_cut=False

    def paused(self):
        return bool(self.dry.sequence and self.dry.sequence['stage'] in ('PAUSED','FAULT_RECOVERY'))

    def recovering(self):
        return bool(self.dry.sequence and self.dry.sequence['stage']=='FAULT_RECOVERY')

    def manual_window(self):
        return bool(self.dry.sequence and self.dry.sequence['stage'] in ('PAUSED','WAIT_CUT_APPROVAL','FAULT_RECOVERY'))

    def capture_fault(self,reason):
        d=self.dry;s=d.sequence
        if not s:return
        if not self.recovering():
            stage=s['stage'];index=s['index']
            expected=((int(s['done'])+1)&0xffffffff if index>=0 and 'done' in s and stage in
                      ('SAW_ACK','SAW_WAIT','RETURN_CUT_ACK','RETURN_CUT_WAIT','PNEU_OFF') else None)
            self.checkpoint={'kind':'fault_reacquire','stage':stage,'next_index':s['next_index'],
                             'cut_index':index,'expected_done':expected,'done':d.data.get('DONE'),
                             'cfg':d.data.get('CFG'),'reason':reason,'count_uncertain':False}
            s.update(stage='FAULT_RECOVERY',at=time.monotonic(),operator_confirmed=False)
        elif self.checkpoint:self.checkpoint['reason']=reason
        self.after_cut=False
        self.observe_fault_completion()

    def observe_fault_completion(self):
        d=self.dry;s=d.sequence;q=self.checkpoint
        if not self.recovering() or not q:return
        done=d.data.get('DONE')
        if d.data.get('CFG')!=q['cfg']:
            q['count_uncertain']=True;return
        if q.get('expected_done') is not None and done==str(q['expected_done']):
            q['next_index']=max(q['next_index'],q['cut_index']+1)
            q['expected_done']=None;q['done']=done
        elif done!=q['done']:q['count_uncertain']=True
        s['next_index']=q['next_index'];d.progress_index=q['next_index']

    def pause(self, after_cut=False):
        d=self.dry;s=d.sequence;p=d.owner.carriage_tab
        if not s or s['stage'] in ('PAUSING','PAUSED'):return False
        # Do not stop a partly issued/active stroke just to implement a routine
        # pause. Cancel/STOP remains the immediate interruption control.
        if not after_cut and (d.data.get('CYCLE')=='1' or s['stage'] in ('SAW_ACK','SAW_WAIT','RETURN_CUT_ACK','RETURN_CUT_WAIT')):
            self.after_cut=True;d.message='Pause requested: finishing this stroke and brake wait, then stopping before the next feed.'
            d.changed.emit();return True
        stage='AFTER_CUT' if after_cut else s['stage']
        if after_cut and s.get('early_return'):
            kind='board_done';s['early_return']=False
        elif stage in ('SEARCH_PROFILE','SEARCH_ARM','SEARCH','TRUE_PROFILE','TRUE_ARM'):
            kind='acquire' if stage in ('SEARCH_PROFILE','SEARCH_ARM','SEARCH') else 'position'
        elif stage=='MOVE':kind='position'
        elif stage in ('FEED_PROFILE','FEED_ARM'):kind='position'
        elif stage in ('DISARM','WAIT_CUT_APPROVAL','WAIT_OPERATOR_CUT','CLAMP','OPERATOR_ARM','OPERATOR_ARMED'):kind='cut'
        elif stage.startswith('EARLY_RETURN'):kind='early_return'
        elif stage in ('LOAD_ARM','LOAD_WAIT','DONE','CLEAR_PROFILE','CLEAR_ARM','CLEAR_MOVE','CLEAR_VERIFY','CLEARANCE_REQUIRED'):kind='finish_board'
        elif stage in ('WAIT_NEW_BOARD','BOARD_TOO_SHORT'):kind='next_board'
        else:kind='advance'
        target=s.get('target')
        if stage in ('TRUE_PROFILE','TRUE_ARM') or (stage=='MOVE' and s['index']==-1):
            target=int(p.x.get('TRUING_MILLI','0'))/1000
        elif stage=='MOVE':target=160.5+int(p.x['TARGET_OFFSET'])/127.12
        self.checkpoint={'kind':kind,'stage':stage,'target':target,'home_changed':False,
                         'index':s['index'],'next_index':s['next_index']}
        self.after_cut=False
        old=d.issuing_sequence;d.issuing_sequence=True
        try:
            if not d.owner.send_command('OFF'):return False
        finally:d.issuing_sequence=old
        d.owner.direct_controls.cancel();d.trigger_held=False
        d.pending=None;d.auto_start=None;d.manual_start=None;d.awaiting_stop=True
        p.pending=None;p.profile_pending=None;p.full_home_pending=None
        p.stopping=bool(p.armed or p.x.get('REMAINING','0')!='0')
        s.update(stage='PAUSING',at=time.monotonic(),operator_confirmed=False)
        d.message='Pausing; waiting for stationary carriage and clear actuator outputs.'
        self.tick();d.changed.emit();return True

    def tick(self):
        d=self.dry;s=d.sequence;p=d.owner.carriage_tab
        if not s or not self.checkpoint:return
        if self.recovering():
            self.observe_fault_completion();d.message=self.description()
        elif s['stage']=='PAUSED':
            if p.homing or p.x.get('POS_KNOWN')!='1':self.checkpoint['home_changed']=True
            d.message=self.description()
        elif s['stage']=='PAUSING':
            if (not p.armed and not p.pending and not p.stopping and p.x.get('REMAINING')=='0'
                    and d.data.get('STATE')=='OFF' and all(d.data.get(k)=='0' for k in ('ARMED','CLAMP','SAW','TRIGGER','CYCLE'))):
                c=d.supervision.context()
                self.checkpoint.update(position=c.position,material=c.material,
                                       done=d.data.get('DONE'),home_state=p.x.get('HOME_STATE'))
                s.update(stage='PAUSED',at=time.monotonic());d.awaiting_stop=False

    def description(self):
        d=self.dry;p=d.owner.carriage_tab
        if self.recovering():
            q=self.checkpoint
            prefix=(f"RECOVERY — cut {d.sequence['next_index']+1} retained. " if d.sequence['next_index']<len(d.sequence['cuts']) else 'RECOVERY — all cuts confirmed complete. ')
            if q and q.get('count_uncertain'):return prefix+'Cut counter changed unexpectedly; cancel/reconcile the list before continuing.'
            if not d.safe_link(False):return prefix+'Clear the cause, return saw UP, release retained clamps and clear the error.'
            if p.x.get('POS_KNOWN')!='1':return prefix+'Position confidence lost; Home is required, then move stock clear and Resume.'
            if d.data.get('CLAMP')!='0':return prefix+'Release clamps before manual carriage movement.'
            return prefix+'Jog or move to Load to clear the detector. Resume gently reacquires, trues the board and continues the remaining list.'
        prefix='PAUSED — pending cut retained. '
        if p.homing or p.x.get('POS_KNOWN')!='1':return prefix+'Home must finish before Resume.'
        if d.owner.direct_controls.intent:return prefix+'Manual positioning is in progress.'
        plan=self.resume_plan()
        if plan and plan[0]=='acquire':return prefix+'Resume reacquires the board before the pending cut.'
        if not plan:return prefix+'Reconcile the board/detector signal before Resume; Home or move manually as needed.'
        if plan[0]=='position':return prefix+'Resume finishes the interrupted move. Manual jog/position/Home is available.'
        note='Place stock against the pusher; Resume uses this adjusted position.'
        if plan[0]=='cut' and d.sequence['index']>=0:
            estimate=max(0,-plan[1].near-d.sequence['kerf'])
            note+=f" Cut estimate {estimate:.2f} in (list {d.sequence['cuts'][d.sequence['index']]:g} in)."
        return prefix+note

    def resume_plan(self):
        d=self.dry;s=d.sequence;p=d.owner.carriage_tab;c=d.supervision.context();q=self.checkpoint
        if (not self.paused() or not q or not d.safe_link(False) or not d.batch_unchanged()
                or d.pending or d.awaiting_stop or p.armed or p.pending or p.profile_pending or p.stopping
                or d.owner.direct_controls.intent or not c.carriage_idle or not c.saw_up or not c.clamps_off
                or not c.trigger_off or not c.reference_known or d.data.get('STATE')!='OFF'):
            return None
        if self.recovering():
            if q.get('count_uncertain') or s.get('reference_signature')!=d.supervision.current_reference_signature():return None
            if s['next_index']>=len(s['cuts']) and not s['repeat']:return ('recovery_complete',None)
            return ('fault_acquire',None) if c.sensor_clear is True and d.acquisition_command() else None
        if q['done']!=d.data.get('DONE'):return None
        kind=q['kind'];m=q.get('material')
        if kind=='next_board':return ('next_board',None) if c.sensor_clear is True and d.acquisition_command() else None
        if kind=='board_done':return ('board_done',None)
        if s['next_index']>=len(s['cuts']):return ('finish_only',None)
        if q['stage']=='WAIT_OPERATOR_CUT' and s.get('early_return'):
            return ('returned_operator',None) if abs(c.position-s['operator_position'])<.02 and c.sensor_clear is True else None
        if q['home_changed'] or kind=='acquire' or not m or not m.located:
            return ('acquire',None) if c.sensor_clear is True and d.acquisition_command() else None
        delta=c.position-q['position']
        if kind=='position' and abs(delta)<1/127.12:
            if c.sensor_clear is None or m.stock.overlaps(c.geometry.sensor)==c.sensor_clear:return None
            return ('position',m.stock)
        # Resume is the explicit operator assertion that the adjusted stock is
        # against the pusher. No grip is inferred from this material registration.
        stock=m.stock.shifted(delta)
        if not stock.near<=0<=stock.far or abs(delta)>m.stock.far-m.stock.near:
            return ('acquire',None) if c.sensor_clear is True and d.acquisition_command() else None
        if c.sensor_clear is None or stock.overlaps(c.geometry.sensor)==c.sensor_clear:return None
        if c.geometry.pusher(c.position).near<=c.geometry.cut_keepout:return None
        if kind in ('early_return','finish_board') and abs(delta)<1/127.12:return (kind,stock)
        if kind=='advance':return ('advance',stock)
        return ('cut',stock)

    def resume(self, approve_cut=False):
        plan=self.resume_plan()
        if not plan:return False
        d=self.dry;s=d.sequence;p=d.owner.carriage_tab;q=self.checkpoint
        kind,stock=plan
        old=d.issuing_sequence;d.issuing_sequence=True
        try:
            d.set_authorized(True);p.consent.setChecked(True)
            if kind=='recovery_complete':
                d.sequence=None;self.clear();d.message='All cuts were confirmed complete before the fault; cycle complete.'
                d.changed.emit();return True
            if kind=='fault_acquire':
                completed=s['next_index']>=len(s['cuts'])
                old_index,old_next=s['index'],s['next_index']
                if completed:s['index']=s['next_index']=0;d.progress_index=0
                s.update(stage='WAIT_NEW_BOARD',reacquire=not completed)
                if not d.begin_auto():
                    s.update(stage='FAULT_RECOVERY',index=old_index,next_index=old_next);d.progress_index=old_next;return False
                self.clear();return True
            if kind in ('acquire','next_board'):
                s.update(stage='WAIT_NEW_BOARD',reacquire=kind=='acquire')
                self.clear()
                return d.begin_auto()
            if stock is not None and kind not in ('early_return','finish_board'):
                d.supervision.coordinator.locate_stock(stock,source='operator')
                d.supervision.position=d.supervision.context().position
                d.supervision.coordinator.paused=None
            if kind=='position':
                s['target']=q['target'];s['resume_profile']=1 if s['index']<0 else 2
                if not p.select_profile(s['resume_profile']):return False
                s['stage']='RESUME_POSITION_PROFILE'
            elif kind=='advance':s['stage']='NEXT_ACTION'
            elif kind in ('finish_board','finish_only'):s['stage']='FINISH_BOARD'
            elif kind=='board_done':s['stage']='DONE'
            elif kind=='returned_operator':
                d.supervision.coordinator.material=replace(q['material'],revision=d.supervision.coordinator.material.revision+1,
                                                          source='operator reconfirmed pending cut after Pause')
                d.supervision.coordinator.paused=None
                d.supervision.position=d.supervision.context().position
                s['operator_config']=d.supervision.coordinator.config_revision
                s['stage']='WAIT_OPERATOR_CUT'
            elif kind=='early_return':
                s['operator_stock']=stock
                if not d.owner.send_command('XARM 1'):return False
                s['stage']='EARLY_RETURN_ARM'
            else:
                s.update(stage='DISARM',cut_approved=bool(approve_cut),early_return=False)
                if s['index']>=0 and stock is not None:
                    s['adjusted_length']=max(0,-stock.near-s['kerf'])
                for key in ('operator_stock','operator_position','operator_cut_position','operator_config'):s.pop(key,None)
            s['at']=time.monotonic();self.clear()
            d.message='Resuming pending cut from the operator-adjusted board reference.'
            d.changed.emit();return True
        finally:d.issuing_sequence=old
