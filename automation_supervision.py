"""Pure geometry/material policies. No Qt, serial, timers or actuator writes.

Machine x=0 is the blade; +x points toward Home. Measured geometry and estimated
material location are distinct from physical grip/standstill feedback.
"""
from dataclasses import dataclass, field, replace
from enum import IntEnum
import math


class Outcome(IntEnum):
    PROCEED = 0
    ADAPT = 1
    OPERATOR_REQUIRED = 2
    BLOCK = 3


@dataclass(frozen=True)
class Span:
    """Ordered x endpoints (near=min x, far=max x), including negative outfeed x."""
    near: float
    far: float

    def __post_init__(self):
        if not all(math.isfinite(x) for x in (self.near, self.far)) or self.near > self.far:
            raise ValueError('Invalid material/geometry span')

    def overlaps(self, other):
        return self.near <= other.far and other.near <= self.far

    def contains(self, other, margin=0):
        return self.near <= other.near-margin and self.far >= other.far+margin

    def shifted(self, amount):
        return Span(self.near+amount, self.far+amount)

    def expanded(self, margin):
        return Span(self.near-margin, self.far+margin)


@dataclass(frozen=True)
class Clamp:
    key: str
    footprint: Span
    role: str = 'remaining_stock'
    installed: bool = True
    commissioned: bool = True
    controller_channel: int | None = 1


@dataclass(frozen=True)
class Geometry:
    verified: bool = False
    clamps: tuple[Clamp, ...] = ()
    pusher_front_offset: float = 0.0
    pusher_rear_extent: float = 0.0
    physical_min: float = 0.0
    cut_keepout: float = 0.0
    margin: float = 0.25
    sensor: Span = field(default_factory=lambda: Span(10.8, 10.8))
    max_clear_push: float = 12.0
    automatic_clearance: bool = False

    def __post_init__(self):
        if type(self.verified) is not bool or type(self.automatic_clearance) is not bool:
            raise ValueError('Commissioning flags must be explicit booleans')
        values=(self.pusher_front_offset,self.pusher_rear_extent,self.physical_min,
                self.cut_keepout,self.margin,self.max_clear_push)
        if not all(math.isfinite(v) and v >= 0 for v in values): raise ValueError('Invalid geometry value')
        if len({c.key for c in self.clamps}) != len(self.clamps): raise ValueError('Duplicate clamp key')
        if self.verified and (self.cut_keepout <= 0 or self.margin <= 0 or not self.clamps):
            raise ValueError('Verified geometry needs clamps, positive margin and blade keepout')
        if self.verified and any(c.commissioned and c.footprint.far<=c.footprint.near for c in self.clamps):
            raise ValueError('Clamp contact footprints need a measured width')

    def pusher(self, position):
        if not math.isfinite(position): raise ValueError('Unknown pusher position')
        return Span(position-self.pusher_front_offset, position+self.pusher_rear_extent)


@dataclass(frozen=True)
class Material:
    stock: Span | None = None
    confidence: str = 'unknown'
    contact: bool = False
    revision: int = 0
    source: str = ''

    @property
    def located(self): return self.stock is not None and self.confidence in ('estimated','operator_registered')


@dataclass(frozen=True)
class Context:
    geometry: Geometry
    material: Material
    position: float | None
    fresh: bool = False
    reference_known: bool = False
    door_closed: bool = False
    saw_up: bool = False
    trigger_off: bool = False
    clamps_off: bool = False
    sensor_clear: bool | None = None
    carriage_idle: bool = False
    fault_free: bool = False
    config_revision: int = 0
    holding_channels: tuple[int, ...] = (1,)
    held_channels: tuple[int, ...] = ()


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    code: str
    reason: str
    permitted_clamps: tuple[str, ...] = ()
    inhibited_clamps: tuple[str, ...] = ()
    target: float | None = None
    material_revision: int = 0
    config_revision: int = 0

    @property
    def proceeds(self): return self.outcome <= Outcome.ADAPT


def assess_main_clamp(ctx, clamp=None):
    g=ctx.geometry
    if not g.verified: return Decision(Outcome.OPERATOR_REQUIRED,'GEOMETRY_REQUIRED','Measure and commission clamp/pusher geometry first.')
    clamp=clamp or next((c for c in g.clamps if c.key=='main'),None)
    if clamp is None or not clamp.installed or not clamp.commissioned:
        return Decision(Outcome.OPERATOR_REQUIRED,'CLAMP_UNAVAILABLE','Clamp is not installed and commissioned.')
    if ctx.position is None or not math.isfinite(ctx.position) or not ctx.reference_known:
        return Decision(Outcome.BLOCK,'REFERENCE_UNKNOWN','Pusher position is unknown; Home/reconcile before clamping.')
    if g.pusher(ctx.position).overlaps(clamp.footprint.expanded(g.margin)):
        return Decision(Outcome.OPERATOR_REQUIRED,'PUSHER_OVERLAP',f'{clamp.key}: pusher overlaps clamp closing envelope.',inhibited_clamps=(clamp.key,))
    if not ctx.material.located:
        return Decision(Outcome.OPERATOR_REQUIRED,'MATERIAL_UNKNOWN','Material location is unknown; acquire an edge or register stock.')
    if not ctx.material.stock.contains(clamp.footprint,g.margin):
        return Decision(Outcome.OPERATOR_REQUIRED,'NO_MATERIAL_COVERAGE',f'{clamp.key}: insufficient material under clamp footprint.',inhibited_clamps=(clamp.key,))
    return Decision(Outcome.PROCEED,'CLAMP_ELIGIBLE',f'{clamp.key}: geometry permits commanded clamping, not proof of grip.',permitted_clamps=(clamp.key,))


def assess_cut_holding(ctx):
    if ctx.material.located and not ctx.material.contact:
        return Decision(Outcome.OPERATOR_REQUIRED,'PUSHER_CONTACT_UNKNOWN','Material reference lost when pusher withdrew; reacquire/register stock before another cut.')
    checks=[assess_main_clamp(ctx,c) for c in ctx.geometry.clamps if c.role in ('remaining_stock','cut_piece')]
    permitted=tuple(k for d in checks if d.proceeds for k in d.permitted_clamps)
    inhibited=tuple(k for d in checks for k in d.inhibited_clamps)
    executable=tuple(c.key for c in ctx.geometry.clamps if c.key in permitted and c.controller_channel in ctx.holding_channels)
    if executable:
        return Decision(Outcome.PROCEED,'HOLDING_PLAN_AVAILABLE','Eligible clamps: '+', '.join(executable)+'. Controller settling/interlocks still required.',executable,inhibited)
    if permitted:
        return Decision(Outcome.OPERATOR_REQUIRED,'HOLDING_EXECUTOR_UNAVAILABLE',
                        'An alternative clamp is geometrically eligible, but its controller channel is unavailable. Main clamp must not be substituted.',inhibited_clamps=inhibited)
    block=next((d for d in checks if d.outcome==Outcome.BLOCK),None)
    if block: return block
    detail='; '.join(d.reason for d in checks) or 'No commissioned holding device covers remaining stock.'
    return Decision(Outcome.OPERATOR_REQUIRED,'HOLDING_REQUIRED',detail+' Automatic cut paused; approved alternative holding is required.',inhibited_clamps=inhibited)


def validate_next_action(ctx, action):
    if action not in ('cut','clear_sensor','feed'):
        return Decision(Outcome.BLOCK,'UNKNOWN_ACTION','No commissioned policy exists for this action.')
    if not (ctx.fresh and ctx.reference_known and ctx.position is not None and math.isfinite(ctx.position) and ctx.fault_free):
        return Decision(Outcome.BLOCK,'STATE_UNKNOWN','Fresh, homed, fault-free machine state is required.')
    if not ctx.door_closed: return Decision(Outcome.BLOCK,'GUARD_OPEN','Guard is open.')
    if not ctx.saw_up or not ctx.trigger_off or not ctx.carriage_idle:
        return Decision(Outcome.BLOCK,'MACHINE_BUSY','Saw must be UP, trigger released and carriage stationary before this action.')
    if action=='cut':
        if not ctx.geometry.verified: return assess_main_clamp(ctx)
        if ctx.geometry.pusher(ctx.position).near <= ctx.geometry.cut_keepout:
            return Decision(Outcome.BLOCK,'BLADE_KEEP_OUT','Pusher occupies the configured blade swept-area keepout. No manual override.')
        if ctx.material.located and not ctx.material.stock.near<=0<=ctx.material.stock.far:
            return Decision(Outcome.OPERATOR_REQUIRED,'NO_STOCK_AT_CUT','Tracked material does not span the blade plane; reconcile geometry/material.')
        return assess_cut_holding(ctx)
    if action in ('clear_sensor','feed') and not ctx.clamps_off:
        return Decision(Outcome.BLOCK,'CLAMP_HELD','Release clamps before pushing a remnant.')
    return Decision(Outcome.PROCEED,'STATE_VALID','Machine state permits planning this action.')


def plan_board_feed(ctx, length, kerf):
    """Fit ONE next cut to the current referenced board, never the whole queue."""
    state=validate_next_action(ctx,'feed')
    if not state.proceeds: return state
    if not ctx.geometry.verified:
        return Decision(Outcome.OPERATOR_REQUIRED,'GEOMETRY_REQUIRED','Measured geometry is required before feeding.')
    if length is None or kerf is None or not math.isfinite(length) or length<=0 or not math.isfinite(kerf) or kerf<0:
        return Decision(Outcome.BLOCK,'INVALID_LENGTH','Cut length and kerf must be finite and valid.')
    if not ctx.material.located or not ctx.material.contact:
        return Decision(Outcome.OPERATOR_REQUIRED,'MATERIAL_UNKNOWN','A located, contacting board is required before feeding.')
    if not ctx.material.stock.near<=0<=ctx.material.stock.far:
        return Decision(Outcome.OPERATOR_REQUIRED,'NO_STOCK_AT_CUT','Tracked stock does not span the blade plane.')
    distance=length+kerf
    target=ctx.position-distance
    # Reserve a full calibrated pulse at the blade boundary so target rounding
    # cannot turn a nominally fitting cut into a keepout crossing.
    boundary=max(ctx.geometry.physical_min,ctx.geometry.cut_keepout)+1/127.12
    usable=min(ctx.geometry.pusher(ctx.position).near,ctx.material.stock.far)-boundary
    if target<0 or ctx.geometry.pusher(target).near<=boundary or ctx.material.stock.far-distance<=boundary:
        return Decision(Outcome.ADAPT,'NEXT_BOARD_REQUIRED',
                        f'Next cut {length:g} in plus {kerf:g} in kerf needs another board; '
                        f'current usable remainder is {max(0,usable):.3f} in.')
    return Decision(Outcome.PROCEED,'FEED_TARGET_AVAILABLE','Next cut fits this referenced board; holding is reviewed after positioning.',target=target)


def assess_manual_cycle(ctx):
    """Operator-positioned Manual stock; do not invent a contacting-board model."""
    state=validate_next_action(replace(ctx,clamps_off=True),'feed')
    if not state.proceeds:return state
    if not ctx.geometry.verified:
        return Decision(Outcome.OPERATOR_REQUIRED,'GEOMETRY_REQUIRED','Save the machine dimensions first.')
    if ctx.geometry.pusher(ctx.position).near<=ctx.geometry.cut_keepout:
        return Decision(Outcome.BLOCK,'BLADE_KEEP_OUT','Pusher is inside the blade keepout.')
    main=next((c for c in ctx.geometry.clamps if c.key=='main' and c.installed and c.commissioned),None)
    chosen=[]
    if main and not ctx.geometry.pusher(ctx.position).overlaps(main.footprint.expanded(ctx.geometry.margin)):
        chosen.append('main')
    # A Manual cycle may retain an explicitly engaged outfeed clamp. With no
    # material extent measurement, do not automatically lower it onto assumed stock.
    for clamp in ctx.geometry.clamps:
        if (clamp.key=='outfeed' and clamp.installed and clamp.commissioned and
                clamp.controller_channel in ctx.holding_channels and clamp.controller_channel in ctx.held_channels and
                not ctx.geometry.pusher(ctx.position).overlaps(clamp.footprint.expanded(ctx.geometry.margin))):
            chosen.append(clamp.key)
    if chosen:
        return Decision(Outcome.PROCEED,'MANUAL_CYCLE_AVAILABLE','Manual cycle uses operator-positioned stock and '+', '.join(chosen)+'; grip is not measured.',tuple(chosen))
    return Decision(Outcome.OPERATOR_REQUIRED,'PUSHER_OVERLAP' if main else 'CLAMP_UNAVAILABLE',
                    'Main clamp unavailable at this position; explicitly secure stock with the commissioned outfeed clamp or reposition.')


def plan_operator_cut(ctx, next_length=None, kerf=0):
    """Unplugged operator-controlled stroke; return only for last usable cut.

    This decision never supplies holding proof or executes a stroke. A fresh
    operator gesture is required after positioning/any early return finishes.
    """
    state=validate_next_action(ctx,'feed')
    if not state.proceeds:return state
    if not ctx.geometry.verified or not ctx.material.located or not ctx.material.contact:
        return Decision(Outcome.BLOCK,'OPERATOR_REFERENCE_REQUIRED','Located contacting stock is required to plan operator intervention.')
    if ctx.geometry.pusher(ctx.position).near<=ctx.geometry.cut_keepout:
        return Decision(Outcome.BLOCK,'BLADE_KEEP_OUT','Pusher is inside the blade keepout.')
    if not ctx.material.stock.near<=0<=ctx.material.stock.far:
        return Decision(Outcome.BLOCK,'NO_STOCK_AT_CUT','Stock must span the cut plane.')
    main=assess_main_clamp(ctx)
    if main.code not in ('PUSHER_OVERLAP','NO_MATERIAL_COVERAGE'):
        return Decision(Outcome.BLOCK,'OPERATOR_PATH_UNAVAILABLE','This path only handles an installed main clamp unable to hold this piece.')
    if ctx.sensor_clear is None or ctx.material.stock.overlaps(ctx.geometry.sensor)==ctx.sensor_clear:
        return Decision(Outcome.BLOCK,'MATERIAL_SENSOR_DISAGREEMENT','Detector and tracked material disagree; reconcile before returning or cutting.')
    after=replace(ctx,material=replace(ctx.material,stock=Span(0,ctx.material.stock.far)))
    if next_length is not None:
        following=plan_board_feed(after,next_length,kerf)
        if not following.proceeds:return following
        if following.code=='FEED_TARGET_AVAILABLE':
            return Decision(Outcome.ADAPT,'OPERATOR_CUT_STAY','Secure the unclamped wood and request this cut; carriage stays forward because another cut fits.',inhibited_clamps=('main',))
    if ctx.sensor_clear:
        return Decision(Outcome.ADAPT,'OPERATOR_CUT_RETURN','Last usable cut is positioned and detector is clear; return carriage, then wait for operator-secured cut.',inhibited_clamps=('main',))
    return Decision(Outcome.ADAPT,'OPERATOR_CUT_STAY','Secure the unclamped wood and request this cut; detector clearance is needed before carriage return.',inhibited_clamps=('main',))


def plan_sensor_clearance(ctx):
    state=validate_next_action(ctx,'clear_sensor')
    if not state.proceeds: return state
    g=ctx.geometry; m=ctx.material
    if not g.verified: return Decision(Outcome.OPERATOR_REQUIRED,'GEOMETRY_REQUIRED','Sensor clearance geometry is not commissioned.')
    if ctx.sensor_clear is None: return Decision(Outcome.BLOCK,'SENSOR_UNKNOWN','Board detector state is unknown.')
    if not m.located: return Decision(Outcome.OPERATOR_REQUIRED,'MATERIAL_UNKNOWN','Remnant position is unknown; reconcile material before returning.')
    expected_blocked=m.stock.overlaps(g.sensor)
    if expected_blocked != (not ctx.sensor_clear):
        return Decision(Outcome.OPERATOR_REQUIRED,'MATERIAL_SENSOR_DISAGREEMENT','Detector and tracked material disagree; do not blindly push or assume empty.')
    if ctx.sensor_clear:
        return Decision(Outcome.PROCEED,'ACQUISITION_ZONE_CLEAR','Detector zone is clear; downstream material is not assumed gone.')
    if not m.contact:
        return Decision(Outcome.OPERATOR_REQUIRED,'PUSHER_CONTACT_UNKNOWN','Pusher has withdrawn; remnant contact must be re-established explicitly.')
    target=ctx.position+(g.sensor.near-g.margin-m.stock.far)
    if (target < g.physical_min or g.pusher(target).near < g.physical_min or
            target >= ctx.position or ctx.position-target > g.max_clear_push):
        return Decision(Outcome.OPERATOR_REQUIRED,'CLEARANCE_OUT_OF_RANGE','Required clearing push exceeds commissioned range; clear manually.')
    if not g.automatic_clearance:
        return Decision(Outcome.OPERATOR_REQUIRED,'CLEARANCE_NOT_COMMISSIONED','Bounded sensor-clearing move is planned but automatic clearing is not commissioned.',target=target)
    return Decision(Outcome.ADAPT,'CLEAR_ACQUISITION_ZONE','Push only to clear the acquisition zone, verify detector clear, then return.',target=target)


class AutomationCoordinator:
    """Single decision owner. Policies are pure; execution remains elsewhere."""
    def __init__(self, geometry=None):
        self.geometry=geometry or Geometry()
        self.material=Material()
        self.config_revision=0
        self.paused=None
        self.events=[]

    def configure(self, geometry):
        self.geometry=geometry; self.config_revision+=1
        self.invalidate('Geometry changed; reconcile material.')

    def invalidate(self, reason):
        self.material=Material(revision=self.material.revision+1,source=reason)
        self.paused=None

    def locate_stock(self, stock, source='edge acquisition'):
        self.material=Material(stock,'operator_registered' if source=='operator' else 'estimated',True,self.material.revision+1,source)

    def push(self, delta):
        if not self.material.located or delta==0: return
        if delta>0:
            self.material=replace(self.material,contact=False,revision=self.material.revision+1)
        elif self.material.contact:
            self.material=replace(self.material,stock=self.material.stock.shifted(delta),revision=self.material.revision+1)

    def cut_completed(self):
        m=self.material
        if not m.located or not m.stock.near<=0<=m.stock.far:
            self.invalidate('Completed stroke cannot be reconciled with tracked stock.'); return
        self.material=replace(m,stock=Span(0,m.stock.far),revision=m.revision+1)

    def decide(self, ctx, action='cut', *, length=None, kerf=None):
        # New rules join here; a blocking result cannot be overridden by an
        # optimization. No individual function can write GPIO/serial.
        ctx=replace(ctx,geometry=self.geometry,material=self.material,config_revision=self.config_revision)
        d=(plan_sensor_clearance(ctx) if action=='clear_sensor' else
           plan_operator_cut(ctx,length,kerf) if action=='operator_cut' else
           plan_board_feed(ctx,length,kerf) if action=='feed' else validate_next_action(ctx,action))
        d=replace(d,material_revision=self.material.revision,config_revision=self.config_revision)
        event=(d.code,d.reason)
        if not self.events or self.events[-1]!=event: self.events.append(event); self.events=self.events[-100:]
        if not d.proceeds: self.paused=d
        return d

    def still_valid(self, decision):
        return decision.proceeds and decision.config_revision==self.config_revision and decision.material_revision==self.material.revision
