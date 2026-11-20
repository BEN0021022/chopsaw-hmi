# Full Auto machine view

App update, 2026-11-19. Uses deployed 0.27 firmware; no flash or wiring change.

Full Auto opens on **Machine / live cycle**. Layout/scenarios and cycle
diagnostics remain separate pages. The machine page is readable offline;
Start requires the same live readiness as Auto, while Stop is available
whenever a serial connection is open.

- **Start Cycle** calls the existing Auto coordinator, including next-board
  continuation and whichever Automatic/Semi-Auto mode is selected in Auto.
  Both pages operate one sequence and one cut list. Start disables during an
  active cycle; the view never starts or advances a cycle on its own.
- **STOP / INTERRUPT**, beside Start at the bottom, calls the existing immediate
  software stop. Native operation stops carriage/cycle, releases the trigger,
  returns the saw toward UP and retains engaged clamps under existing rules.
  This is a software control, not a hardware emergency-stop replacement.
- When per-cut/operator approval is needed, the matching amber action appears
  on this page too. Its click and enable state are shared with Auto. Automatic
  clamped early return does not display an irrelevant operator approval.
- Only main and outfeed clamps remain. The retired fence clamp is removed from
  the drawing, status row, virtual sequence and cylinder-timing selector.
  Old stored fence timing keys are unused; other saved settings are preserved.

## Animation sources

Carriage position comes from fresh referenced pulse-count telemetry. Saw UP/DOWN
comes from the endpoint inputs; intermediate direction is shown from the
controller's travel command/phase. Intermediate drawing positions are illustrative,
not a measurement of continuous cylinder travel. Clamp pads use saved measured
locations and move/color with their individual commanded outputs. They do not
claim grip feedback. Guard, driver, Home and board-detector pills use fresh inputs.

The colored stock extent follows the shared detector-based material model,
including cut completion and stock remaining in place during early return.
Physical cut-piece ejection is not invented because it is not sensed. Unknown
reference, stale feedback and disconnected state hide the old carriage/stock
and show unknown outputs/endpoints rather than replaying a simulator animation.
The view/painting functions send no commands. The virtual-machine backend keeps
its separate illustrative animation, updated to two clamps.

## Validation

`test_full_auto_live.py` runs the actual C++ sketch through the Qt app without
physical ports: Full Auto Start, moving-carriage Stop, restart/acquisition,
both clamps, last-cut/return overlap, shared per-cut approval, stop during a
clamped stroke, stale/unknown feedback and non-actuating refresh. Screenshots
are under `tmp/ui-full-auto`. Timing sequencing/migration and offline workbench
checks pass; existing second-clamp and 0.27 recovery integrations pass.
Existing operator-return/overlap, UI safety boundaries and carriage integration
tests also pass. The updated app was reopened on Machine / live cycle; no serial
ports were enumerated at handoff, so live values remain UNKNOWN and Start stays
disabled until connection/readiness. No machine actions were sent by the agent.

The older `test_sim_cycle.py` assumed an unhomed keypad move was allowed; that
failure was reproduced on the unchanged baseline. Release preparation updates
the fixture to Home before referenced keypad motion, then Home again after
motor release, matching the application's reference policy.
Physical acceptance of the new view/buttons remains for the operator.
