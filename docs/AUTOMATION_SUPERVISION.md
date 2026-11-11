# Automation supervision - prepared app integration, 2026-11-11

This is an app-side planning layer for the current **saw-unplugged** commissioning
scope. Firmware 0.19 is unchanged. No hardware was flashed, connected or actuated
while implementing this layer. It is not a safety-rated interlock, independent
guard system or approval for powered production.

## Small policies, one owner

`automation_supervision.py` has no Qt, serial or actuator writes. Machine x=0 is
the blade; positive points toward Home. Geometry and material are separate:

- `assess_main_clamp`: installation/commissioning, wood contact footprint,
  pusher closing-envelope overlap, reference and location confidence.
- `assess_cut_holding`: eligible holding roles and whether the installed executor
  can actually implement that holding arrangement.
- `plan_sensor_clearance`: expected remnant/detector state, pusher contact,
  minimum bounded clearance target, commissioned automatic-cleanup permission.
- `validate_next_action`: current reference/freshness, guard, UP/trigger OFF,
  stationary carriage, blade keepout and known action. Unknown actions block.
- `AutomationCoordinator`: owns geometry/material revisions, one decision/event
  history and pause reason. Policies return decisions; only the existing native
  runner requests acknowledged commands.

Decisions are PROCEED, ADAPT, OPERATOR_REQUIRED or BLOCK, with reason codes,
permitted/inhibited clamp names and optional cleanup target. Future rules join
the coordinator; optimizations cannot override a hard constraint. Grip and blade
standstill are not inferred from material support, valve commands or timers.

## Commission geometry once

Settings adds **Automation supervision — geometry commissioning**. Automatic
combined cycles in this prepared app remain unavailable until measured data is
saved/verified. There are no guessed 9/10/12-inch clamp footprints. Record:

1. Near/far edges of the main clamp's actual contact pad.
2. Pusher projection toward the blade and body extent toward Home, relative to
   the carriage's reported reference. Use conservative projected envelopes.
3. Positive blade swept-area keepout and clearance margin. The pusher's ability
   to approach displayed zero is not permission to cycle the blade there.
4. Actual detector zone and native edge/truing datum. Existing motion calibration
   is not rewritten by this layer. Physically verify the sensor offset/trim
   convention and resulting truing position before commissioning the model.
5. Maximum clearing push. Automatic clearing stays disabled until separately
   accepted in unplugged tests; it is not enabled by a routine cycle click.

Settings changes require disarmed/cancelled operation. Changing native sensor
offset or trim invalidates geometry verification and material/plans. Configuration
and material revisions reject stale cleanup decisions. Reconnect/fault/reference
loss/guard opening/Stop require material reconciliation; no automatic resumption.

## Material model and normal workflow

Automatic acquisition uses the real edge capture and a commissioned native truing
datum to establish the estimated remaining infeed interval. Every push translates
that interval while contact is known; withdrawing the pusher does not drag stock
back. Successful controller DONE commits a cut boundary, never a PC delay.

For stationary Manual operations without acquisition, **Register stock across
blade plane / against pusher** is an explicit operator location registration.
It sends no actuator command and does not verify grip. Unknown stock is not
silently replaced with a board-length preset, assumed hand, or gravity support.

Before DARM/DCUT at each Auto cut, the coordinator assesses holding. Known main
clamp interference also inhibits individually requested clamping/lowering through
the app. Individual unplugged bench controls before geometry commissioning retain
their diagnostic behavior; they are not an approved powered-cut path.

## Operator-required state and current executor boundary

No eligible holding plan pauses Auto **before pneumatic arm**, with carriage
stationary, clamp/trigger OFF, an explicit status and an amber Manual Cycle review
button. There is no arbitrary time limit on that unenergized human pause.

The review click re-evaluates current conditions; it cannot invent holding or
convert an acknowledgment into a clamp-free automatic stroke. Only a newly valid
holding plan may continue after an explicit gesture. Stop cancels rather than
resumes. Geometry cannot be changed underneath a paused live sequence.

**The requested externally secured, no-main-clamp Manual Cycle is not yet an
executable recovery path.** Firmware 0.19 DCUT always operates the main clamp.
It must not be sent when that clamp is inhibited. A future executor extension
needs an explicit selected-clamp/approved-fixture plan, fresh one-shot operator
authorization, immutable geometry/material revisions, and controller-side
validation. The approved external securing method must first be defined; presumed
hand-holding is not encoded as machine holding. A new outfeed cylinder alone
does not commission its footprint, I/O or holding role.

The outfeed clamp is therefore shown as PLANNED / unavailable. Registering future
devices/policies does not silently map them to the main clamp's output.

## Acquisition-zone cleanup

After the last successful cut and normal release/brake sequence, assess the
remnant before returning. If already clear and model/detector agree, return
normally. If obstructed, in contact, within range and automatic clearing is
commissioned: select stored Gentle, recheck the plan, make one bounded absolute
push to move the modeled material rear past the detector plus margin, stop and
verify a stable clear signal, then return using FAST.

This does not push blindly to zero or fully eject every remnant. Detector/model
disagreement, lost contact, excessive distance or failure to clear requires
operator reconciliation. No extra push/retry occurs. A clear detector is not
proof of an empty outfeed path; downstream handling still needs a separate policy.
The existing native soft limits, watchdog and per-stage deadlines remain.

## Verification / remaining commissioning

- Pure policy tests cover footprint/keepout boundaries, stale/unknown state,
  future/unavailable devices, minimum cleanup, mismatches, revisions and push-only
  material tracking.
- Actual sketch/Qt tests cover acknowledged normal Manual/Auto cycles, Gentle
  sensor clearing then FAST return, operator pause before arm, an amber review
  click producing no forbidden command, no geometry edits under a paused plan,
  source-command guards, configuration ACK, cancellation and feedback loss.
- Existing firmware, carriage/UI and complete simulator regressions pass.
- No running machine/app was updated. Measured geometry, physical coordinator
  acceptance, selected-clamp/approved-fixture executor support and powered-machine
  safeguarding remain separate unfinished steps.
