"""Native HMI adapter for the single pure automation coordinator.

Geometry commissioning is data-only. Second-clamp execution also requires the
matching controller capability and acknowledged enable configuration.
"""
import json
import math
import time
from dataclasses import replace
from PyQt6.QtWidgets import QGroupBox, QVBoxLayout, QFormLayout, QLabel, QDoubleSpinBox, QCheckBox, QPushButton
from automation_supervision import AutomationCoordinator, Geometry, Clamp, Span, Context, Outcome


class SupervisionAdapter:
    def __init__(self, owner):
        self.owner=owner
        self.coordinator=AutomationCoordinator()
        self.position=None; self.edge_key=None; self.done=None; self.last_decision=None
        self.last_event=None
        self.reference_signature=()
        try:
            data=json.loads(owner.settings.value('supervision/geometry_v1','{}'))
            if data:
                self.reference_signature=tuple(data.get('reference_signature',()))
                # Saved dimensions are machine data, not a per-session waiver.
                # Reject invalid/empty defaults; no checkbox is needed to reuse
                # valid operator-entered measurements on the next startup.
                self.coordinator.configure(self.geometry_from_data(dict(data,verified=True,automatic_clearance=True),self.sensor_distance()))
                # Retire old duplicated coordinates only after validating the
                # migrated geometry. The saved cutting setting is authoritative.
                if 'sensor_near' in data or 'sensor_far' in data:
                    data.pop('sensor_near',None);data.pop('sensor_far',None)
                    owner.settings.setValue('supervision/geometry_v1',json.dumps(data))
        except (ValueError,TypeError,KeyError): pass  # Invalid stored geometry stays uncommissioned.

    @staticmethod
    def geometry_from_data(d,sensor_distance):
        enabled=d.get('second_enabled',False)
        if type(enabled) is not bool:raise ValueError('Second clamp enable must be a boolean')
        near,far=float(d.get('outfeed_near',0)),float(d.get('outfeed_far',0))
        if near<0 or far<near or (enabled and (far<=near or near<=float(d['keepout'])+float(d['margin']))):
            raise ValueError('Measure outfeed pad distances beyond the blade keepout; far must exceed near.')
        return Geometry(verified=d.get('verified',False),
            clamps=(Clamp('main',Span(float(d['main_near']),float(d['main_far']))),
                    Clamp('outfeed',Span(-far,-near),'cut_piece',enabled,enabled,2)),
            pusher_front_offset=float(d['front_offset']),pusher_rear_extent=float(d['rear_extent']),
            cut_keepout=float(d['keepout']),margin=float(d['margin']),
            sensor=Span(sensor_distance,sensor_distance),
            max_clear_push=float(d['max_clear_push']),automatic_clearance=d.get('automatic_clearance',False))

    def controls(self):
        group=QGroupBox('Machine dimensions')
        layout=QVBoxLayout(group)
        note=QLabel('Physical dimensions in inches from the blade, positive toward Home. Second-clamp distances below are measured outward from the blade on the outfeed side.')
        note.setWordWrap(True); layout.addWidget(note)
        form=QFormLayout(); self.fields={}
        g=self.coordinator.geometry; main=next(iter(g.clamps),None)
        values={'main_near':main.footprint.near if main else 0,'main_far':main.footprint.far if main else 0,
                'front_offset':g.pusher_front_offset,'rear_extent':g.pusher_rear_extent,'keepout':g.cut_keepout,
                'margin':g.margin,'max_clear_push':g.max_clear_push}
        labels=('Main clamp pad near edge','Main clamp pad far edge','Pusher projection toward blade',
                'Pusher body extent toward Home','Blade swept-area keepout','Geometry clearance margin',
                'Maximum cleanup push')
        for (key,value),label in zip(values.items(),labels):
            spin=QDoubleSpinBox(); spin.setRange(0,162); spin.setDecimals(4); spin.setValue(value); spin.setSuffix(' in')
            spin.setMinimumHeight(36); self.fields[key]=spin; form.addRow(label,spin)
            if key=='rear_extent': spin.setToolTip('Physical moving assembly length behind the pushing face toward Home. This is NOT carriage travel or cleanup distance.')
        layout.addLayout(form)
        outfeed=next((c for c in g.clamps if c.key=='outfeed'),None)
        self.second_enabled=QCheckBox('Enable second / outfeed clamp — Mist TTL D18 (after wiring and testing)')
        self.second_enabled.setChecked(bool(outfeed and outfeed.installed and outfeed.commissioned))
        layout.addWidget(self.second_enabled)
        second_form=QFormLayout()
        for key,label,value in (('outfeed_near','Outfeed pad near edge — distance from blade',-outfeed.footprint.far if outfeed else 0),
                                ('outfeed_far','Outfeed pad far edge — distance from blade',-outfeed.footprint.near if outfeed else 0)):
            spin=QDoubleSpinBox();spin.setRange(0,162);spin.setDecimals(4);spin.setSuffix(' in');spin.setValue(value)
            spin.setMinimumHeight(36);self.fields[key]=spin;second_form.addRow(label,spin)
        layout.addLayout(second_form)
        self.second_note=QLabel('Second clamp is disabled until enabled and dimensions saved. ON must clamp; OFF must release. Timers report commanded state, not verified grip.')
        self.second_note.setWordWrap(True);layout.addWidget(self.second_note)
        save=QPushButton('Save machine dimensions'); save.clicked.connect(self.save); layout.addWidget(save)
        self.feedback=QLabel('Dimensions loaded.' if g.verified else 'Enter the physical machine dimensions once.')
        self.feedback.setWordWrap(True); layout.addWidget(self.feedback)
        return group

    def save(self):
        dry=self.owner.dry_run; p=self.owner.carriage_tab
        if dry.motion_locked() or p.armed or p.pending or p.homing or p.edge_searching:
            self.feedback.setText('Stop/disarm and cancel any paused sequence before changing geometry.'); return False
        data={k:w.value() for k,w in self.fields.items()}
        data.update(verified=True,automatic_clearance=True,second_enabled=self.second_enabled.isChecked())
        data['reference_signature']=self.current_reference_signature()
        try: g=self.geometry_from_data(data,self.sensor_distance())
        except (ValueError,TypeError) as e: self.feedback.setText(str(e)); return False
        self.owner.settings.setValue('supervision/geometry_v1',json.dumps(data)); self.coordinator.configure(g)
        self.reference_signature=tuple(data['reference_signature'])
        self.edge_key=None; self.last_decision=None
        self.feedback.setText('Geometry saved. Reacquire/register material; existing plans were invalidated.')
        return True

    def current_reference_signature(self):
        if not hasattr(self.owner,'board_sensor_location_input') or not hasattr(self.owner,'carriage_tab'): return ()
        return (self.owner.board_sensor_location_input.value(),self.owner.kerf_input.value(),'sensor_plus_kerf_v1')

    def sensor_distance(self):
        widget=getattr(self.owner,'board_sensor_location_input',None)
        if widget is not None:return float(widget.value())
        try:value=float(self.owner.settings.value('board_sensor_location',10.8))
        except (ValueError,TypeError):return 10.8
        return value if math.isfinite(value) and 0<=value<=2000 else 10.8

    def sync_reference(self,*_args):
        """The cutting field supplies both the motion offset and point detector."""
        current=self.current_reference_signature()
        if not current:return
        g=self.coordinator.geometry;point=Span(self.sensor_distance(),self.sensor_distance())
        geometry_changed=g.sensor!=point
        if geometry_changed or current!=self.reference_signature:
            if geometry_changed:self.coordinator.configure(replace(g,sensor=point))
            else:self.coordinator.invalidate('Sensor/kerf parameters changed; acquire a new material reference.')
            self.reference_signature=current
            self.position=None;self.last_decision=None
            if hasattr(self,'feedback'): self.feedback.setText('Reference parameters updated. Acquire a new board before Auto.')

    def context(self):
        p=self.owner.carriage_tab; d=self.owner.dry_run
        self.sync_reference()
        try: pos=160.5+int(p.x['HOME_OFFSET'])/127.12 if p.x.get('POS_KNOWN')=='1' else None
        except (KeyError,ValueError): pos=None
        sensor=p.inputs.get('BOARD_EDGE') if p.fresh('INPUTS') else None
        return Context(self.coordinator.geometry,self.coordinator.material,pos,
            fresh=d.fresh() and p.ready_link() and p.fresh('INPUTS'),reference_known=p.x.get('POS_KNOWN')=='1',
            door_closed=p.inputs.get('FENCE_DOOR')=='0',saw_up=p.inputs.get('SAW_UP')=='0' and p.inputs.get('SAW_DOWN')=='1',
            trigger_off=d.data.get('TRIGGER')=='0',clamps_off=d.data.get('CLAMP')=='0',
            sensor_clear=None if sensor not in ('0','1') else sensor=='1',
            carriage_idle=p.x.get('REMAINING')=='0' and not p.pending and not p.homing and not p.edge_searching,
            fault_free=p.x.get('FAULT')=='NONE' and d.data.get('FAULT')=='NONE' and not p.local_fault and not d.local_fault,
            config_revision=self.coordinator.config_revision,
            holding_channels=(1,2) if d.second_supported and self.second_requested() and d.data.get('SECOND_ENABLED')=='1' else (1,),
            held_channels=tuple(i for i,key in ((1,'MAIN_CLAMP'),(2,'SECOND_CLAMP')) if d.data.get(key)=='1'))

    def second_requested(self):
        return any(c.key=='outfeed' and c.installed and c.commissioned for c in self.coordinator.geometry.clamps)

    def review(self, action='cut', **parameters):
        self.last_decision=self.coordinator.decide(self.context(),action,**parameters)
        event=(self.last_decision.code,self.last_decision.reason)
        if event!=self.last_event:
            self.owner.log.append('SUPERVISION: '+': '.join(event)); self.last_event=event
            self.owner.dry_run.diagnostics.note(self.last_decision.code, self.last_decision.reason, time.monotonic(), {
                'geometry_revision': self.last_decision.config_revision,
                'material_revision': self.last_decision.material_revision,
                'permitted_clamps': self.last_decision.permitted_clamps,
                'inhibited_clamps': self.last_decision.inhibited_clamps,
                'target_in': self.last_decision.target,
            })
        return self.last_decision

    def register_stock(self):
        c=self.context(); d=self.owner.dry_run
        if not (c.fresh and c.reference_known and c.door_closed and c.saw_up and c.trigger_off and
                c.carriage_idle and c.fault_free and not d.sequence and d.data.get('CYCLE')=='0'):
            return False
        rear=c.geometry.pusher(c.position).near
        if rear<=0: return False
        self.coordinator.locate_stock(Span(0,rear),source='operator')
        # Registration locates infeed stock, not the original full board length.
        self.owner.cut_history.new_board()
        self.owner.log.append('SUPERVISION: operator registered stock spanning blade plane and contacting pusher; not grip feedback.')
        self.review(); return True

    def observe(self, kind):
        p=self.owner.carriage_tab; d=self.owner.dry_run; c=self.context()
        if kind=='BENCH_X':
            if not c.reference_known or p.x.get('FAULT')!='NONE' or (p.fresh('INPUTS') and p.inputs.get('FENCE_DOOR')!='0'):
                if self.coordinator.material.located: self.coordinator.invalidate('Reference/fault/guard change; material must be reconciled.')
                self.position=None; self.edge_key=None; return
            key=(p.x.get('MOVE_ID'),p.x.get('EDGE_MILLI'))
            if p.x.get('EDGE_VALID')=='1' and key!=self.edge_key and self.coordinator.geometry.verified:
                # A delayed old capture cannot restore a board reference after
                # calibration changed. Require the parameters of the new move.
                try:
                    captured=(int(p.x['SENSOR_OFFSET_MILLI']),int(p.x['TRIM_MILLI']))
                    expected=tuple(int(math.floor(v*1000+.5)) for v in self.current_reference_signature()[:2])
                except (KeyError,ValueError):captured=None;expected=()
                if captured!=expected:
                    self.coordinator.invalidate('Captured edge uses previous sensor/kerf parameters; acquire a new board.')
                    self.edge_key=key;self.position=c.position;return
                rear=self.coordinator.geometry.pusher(c.position).near
                front=self.coordinator.geometry.sensor.near
                if p.x.get('ACQUIRE_CONTINUOUS')=='1':front+=c.position-int(p.x['EDGE_MILLI'])/1000
                if rear>=front:
                    self.coordinator.locate_stock(Span(front,rear),'real edge acquisition')
                    self.owner.cut_history.new_board(rear-front, 'edge_estimate')
                else: self.coordinator.invalidate('Captured material extent is inconsistent.')
                self.edge_key=key; self.position=c.position; return
            if self.position is not None and c.position is not None:
                self.coordinator.push(c.position-self.position)
            self.position=c.position
        elif kind=='BENCH_DRY':
            value=d.data.get('DONE')
            if self.done is not None and value!=self.done:
                delta=(int(value)-int(self.done))&0xffffffff
                if delta==1: self.coordinator.cut_completed()
                else: self.coordinator.invalidate('Unexpected completed-cycle counter change; reconcile material.')
                stock=self.coordinator.material.stock
                self.owner.cut_history.completed(int(value),delta,
                    remaining=stock.far-stock.near if self.coordinator.material.located else None,
                    position=c.position,board_preset=self.owner.get_active_board_length())
            self.done=value

    def reset_session(self):
        self.coordinator.invalidate('Connection/session changed.')
        self.position=None; self.edge_key=None; self.done=None; self.last_decision=None

    def individual_clamp_allowed(self,key='main'):
        # Preserve explicitly commanded, unplugged wiring tests before geometry
        # commissioning; once measured, known pusher collision is never bypassed.
        g=self.coordinator.geometry; c=self.context()
        if not g.verified: return True
        from automation_supervision import assess_main_clamp
        clamp=next((item for item in g.clamps if item.key==key),None)
        if key=='outfeed' and (clamp is None or not clamp.installed or not clamp.commissioned):return False
        d=assess_main_clamp(c,clamp)
        return d.code not in ('PUSHER_OVERLAP','REFERENCE_UNKNOWN')

    def summary(self):
        if not self.coordinator.geometry.verified:
            return 'SUPERVISION SETUP REQUIRED — commission measured geometry in Settings before automatic cycles.'
        if self.last_decision and not self.last_decision.proceeds:
            return 'OPERATOR REQUIRED — '+self.last_decision.reason
        return 'Geometry supervision active; material location is modeled, not grip feedback.'
