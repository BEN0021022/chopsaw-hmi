# Auto tab preparation - controller/app 0.15.0

Prepared 2026-11-08. This slice restores planning and operator-requested carriage
operations. Cycle Start, Resume and automatic cutting remain unavailable on live
Teensy. Full Auto remains locked. No pneumatic output is exposed by this change.

## Available controls

- Add cut, edit/update the cut-list text, import a list, clear the list, choose
  stock size and review kerf/utilization. Planning remains available disconnected.
  Loading a saved cut list routes to the actual AUTO tab, not a numeric tab index.
- Shared isolation/setup, Home and arm state. Home uses the same bounded search
  limit set on CARRIAGE/MANUAL and runs while disarmed. Explicit arm is required
  for jogs and Load Position.
- Variable jog and quick increments in both directions. Home/+ moves away from
  the saw; saw/- moves toward it. Native jogs remain at most two inches per click,
  never queue, and use the selected acknowledged profile.
- Load Position uses the selected stock radio. Standard/Home uses the actual Home
  pull-off maximum; other presets remain 135/111/87/63 inches. It requires a valid
  Home reference, settled arm state, healthy interlocks and an idle carriage.
- STOP/DISARM cancels carriage motion without clearing or advancing the cut list.

Cut Complete is removed from both operator layouts. Its old completion helper is
retained only for the archived-protocol simulator test harness; live Teensy calls
cannot advance that old workflow.

## FAST loading contract

`XLOAD <integer milliinches>` uses exactly the XMOVE validation and per-pulse
travel guards. Only an accepted request selects stored FAST (profile 3) and
starts its ramp. Invalid, unhomed, disarmed, busy or out-of-range requests do
not select a different profile or queue a move. It does not arm automatically
or edit the FAST rate/acceleration values. The controller reports the accepted
profile and normal move ID/remaining/target telemetry. CARRIAGE Load uses this
same path; other absolute targets retain the selected profile.

Firmware identity: 0.15.0 / CARRIAGE_V9 / LOAD:FAST_V1. The matching app rejects
an older identity for motion. Existing rate/acceleration values can be read
before a flash and restored as disarmed nonmotion parameter writes afterwards;
position/setup/arm are never restored. Rehome after the update.

## Feedback

AUTO's Home, board edge, guard door, saw UP/DOWN and driver-alarm pills use
fresh native input telemetry. Stale/disconnected inputs show UNKNOWN. Position
is unknown until a valid reference is reported. No sensor indicator sends a
motion command or advances a cut.

Clamp feedback remains UNKNOWN because no clamp-confirmation sensor is
configured. The disconnected current monitor's old green/zero display is
hidden in live Teensy mode. Uncommissioned outfeed/fence inputs remain UNKNOWN.
These states must not be inferred from output commands or default raw levels.

## Verification

Qt tests cover actual Auto button routes, input polarity/freshness, planning
without serial writes, all load presets, no overlapping requests, explicit arm,
fault/stale guards, STOP preserving list progress and all automatic entry points
remaining blocked. Native sketch tests cover FAST selection only on accepted
Load, stored parameters, queue rejection and shared per-pulse limits. Simulator
regressions pass; layout inspected at 1280x900. Physical Auto-tab button tests
remain for the operator; no remote motion is performed during deployment.
