"""Read-only planning fixtures and lookahead, using the execution coordinator.

Example geometry is confined to scenarios. Nothing here saves machine settings,
advances the real material model, opens a port or sends a command.
"""
from dataclasses import dataclass, replace
import math
from automation_supervision import (
    AutomationCoordinator, Clamp, Context, Decision, Geometry, Material, Outcome, Span,
)


@dataclass(frozen=True)
class Scenario:
    title: str
    context: Context
    action: str
    expected: str


@dataclass(frozen=True)
class PreviewStep:
    label: str
    position: float | None
    decision: Decision


def evaluate(context, action='cut'):
    """An isolated coordinator; viewing never changes a live pause/revision."""
    coordinator = AutomationCoordinator(context.geometry)
    coordinator.material = context.material
    coordinator.config_revision = context.config_revision
    return coordinator.decide(context, action)


def example_scenarios():
    geometry = Geometry(True, (Clamp('main', Span(9, 10)),), 0, 6, 0, 1,
                        .25, Span(10.8, 10.8), 24, True)
    base = Context(geometry, Material(Span(-20, 40), 'estimated', True, 1,
                                    'offline example'), 40,
                   True, True, True, True, True, True, False, True, True)
    def stock(near, far):
        return Material(Span(near, far), 'estimated', True, 1, 'offline example')
    planned = replace(geometry, clamps=geometry.clamps + (
        Clamp('outfeed', Span(-12, -11), 'cut_piece', False, False, None),))
    return (
        Scenario('Normal stock / main clamp available', base, 'cut', 'HOLDING_PLAN_AVAILABLE'),
        Scenario('Pusher beneath main clamp', replace(base, position=8,
                 material=stock(-20, 8)), 'cut', 'HOLDING_REQUIRED'),
        Scenario('Short piece between clamps / outfeed planned', replace(base,
                 geometry=planned, position=5, material=stock(-8, 5)), 'cut', 'HOLDING_REQUIRED'),
        Scenario('Remnant blocks next board acquisition', replace(base, position=20,
                 material=stock(0, 20)), 'clear_sensor', 'CLEAR_ACQUISITION_ZONE'),
        Scenario('Detector disagrees with modeled stock', replace(base, position=20,
                 material=stock(0, 20), sensor_clear=True), 'clear_sensor', 'MATERIAL_SENSOR_DISAGREEMENT'),
        Scenario('Pusher withdrew / contact lost', replace(base,
                 material=replace(base.material, contact=False)), 'cut', 'PUSHER_CONTACT_UNKNOWN'),
        Scenario('Home reference unknown', replace(base, reference_known=False,
                 position=None), 'cut', 'STATE_UNKNOWN'),
        Scenario('Guard open', replace(base, door_closed=False), 'cut', 'GUARD_OPEN'),
        Scenario('Telemetry stale', replace(base, fresh=False), 'cut', 'STATE_UNKNOWN'),
        Scenario('Pusher enters blade keepout', replace(base, position=.5,
                 material=stock(-20, .5)), 'cut', 'BLADE_KEEP_OUT'),
        Scenario('Future clamp eligible / executor unavailable', replace(base,
                 geometry=replace(geometry, clamps=(Clamp('outfeed', Span(-12, -11),
                 'remaining_stock', True, True, 2),))), 'cut', 'HOLDING_EXECUTOR_UNAVAILABLE'),
    )


def preview_cut_list(context, lengths, kerf):
    """Forecast NEXT cuts from the displayed trued/contacting stock state.

    No acquisition/truing guess, no return pulling material back, and no cut after
    the first unsupported step. Future sensor state is modeled, never readback.
    """
    initial = evaluate(context)
    if not initial.proceeds:
        return (PreviewStep('Starting state', context.position, initial),)
    if not math.isfinite(kerf) or kerf < 0:
        return (PreviewStep('Cut list', None, Decision(Outcome.BLOCK, 'INVALID_KERF', 'Kerf must be finite and nonnegative.')),)
    coordinator = AutomationCoordinator(context.geometry)
    coordinator.material = context.material
    coordinator.config_revision = context.config_revision
    result = []
    position = context.position
    for index, length in enumerate(lengths):
        if not math.isfinite(length) or length <= 0:
            result.append(PreviewStep(f'Cut {index+1}', None, Decision(Outcome.BLOCK,
                          'INVALID_LENGTH', 'Cut lengths must be finite and positive.')))
            return tuple(result)
        position -= length + kerf
        coordinator.push(-(length + kerf))
        current = replace(context, position=position)
        decision = coordinator.decide(current)
        result.append(PreviewStep(f'Cut {index+1} / {length:g} in', position, decision))
        if not decision.proceeds:
            return tuple(result)
        coordinator.cut_completed()
    if result:
        current = replace(context, position=position, clamps_off=True,
                          sensor_clear=not coordinator.material.stock.overlaps(context.geometry.sensor))
        result.append(PreviewStep('Remnant / detector clearance (predicted)', position,
                                  coordinator.decide(current, 'clear_sensor')))
    return tuple(result)
