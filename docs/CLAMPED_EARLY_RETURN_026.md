# Clamped last-cut early return — 0.26

Flashed/read back 2026-11-19. Firmware 0.26.0 / CARRIAGE_V19 and matching app required.
Physical acceptance pending; existing saw-unplugged commissioning scope remains.

The previous early return applied to an unclampable operator-controlled cut.
Adding an eligible outfeed clamp made the normal holding plan succeed, taking
the sequential cut-then-return path. This update adds a separate clamped path.

## Planner

After positioning a production-list item (never the initial truing stroke),
the coordinator reviews the selected holding plan and the next queued cut.
Another fitting cut keeps the carriage forward. A last usable cut can return
early if the selected clamps are clear of the entire return sweep and the Load
target is behind the current position. Main, outfeed or both are supported.
Semi-Auto still waits for its explicit per-cut approval before starting.

Required detector-zone cleanup keeps the carriage forward until the stroke
finishes and the cleanup push completes. Repeated-list boundaries use the
between-board clearing setting; finite-list completion uses the end-of-list
setting. A finite list retaining its remainder can return with that remainder
still covering the detector. A withdrawn pusher never feeds again using the
old contacting-board reference. Existing unclampable operator cuts remain.

## Controller

New capability: `AUTO_RETURN:CLAMPED_LAST_CUT_V1`.
`DCUTRET <config-id> <next-request-id> <clamp-mask> <load-milli> <minimum-milli>`
atomically accepts one combined cycle and one positive-direction Fast return.
Config/request binding, enabled mask, known/configured position, Home clear,
guard, saw UP, driver alarm, soft limits and strictly increasing target are
checked before acceptance. The host minimum includes blade and selected-clamp
clearances. Geometry/model revisions bind the app's selected plan.

No step is scheduled until every selected clamp has completed its engage and
settle timing. This is commanded/timed holding, not force or grip feedback.
The controller then enables the motor, observes its 200 ms startup interval,
and runs the stored Fast profile while the combined stroke continues. Selected
clamps stay under the existing cycle's control through saw return/brake waits
and their independent release/clearance timings.

The controller authorizes only this away-from-blade move during saw travel.
Ordinary motion, mode changes, manual clamp changes and replayed requests stay
blocked. OFF/Cancel or trigger-release abort revokes the pending/active return;
guard, driver, watchdog, conflicting endpoints, holding-state loss or saw
timeout stops both. Stop/fault retains any engaged clamp as before.

X readback adds RETURN_AUTO, RETURN_PENDING and RETURN_HOLD_MASK. The matching
app validates them, waits for both cut DONE and carriage at Load, then advances
the list once. Routine Pause waits for both and preserves the board-done
checkpoint; Cancel interrupts immediately. Older firmware retains sequential
clamped cycles and the prior explicit operator-return path.

## Verification

Actual-sketch tests cover all three clamp masks, clamp-settle exclusion, saw/
return pulse overlap, both completion orders, replay/config/target rejection,
disabled second clamp, Home input and stop/fault revocation. Actual Qt/sketch
tests cover outfeed-only overlap with main OFF, Pause/Resume after both finish,
0.25 fallback and older second-clamp capability lockout. Policy tests cover
following-cut fit, required cleanup, finite remainder retention and unknown
feedback. Deployment captures and build/test results belong in
`tmp/commissioning/0.26.0`.

Prior native Qt test-process crashes remain documented in the 0.25 record;
full-harness failures and isolated outcomes are retained separately.

## Deployment

Source `bdb7efe31fbed75cca63c9150fa3c50af8a4f777`; firmware tree
`3a0adc6b556df6c5a6eaff688dfe28ed0ba81357`. Teensy 4.1 compile/upload succeeded.
Captured pre-flash 0.25 identity and idle outputs after operator confirmed app
closed, power and air off. Readback confirms 0.26 / V19 and automatic-return
capability; all outputs OFF, return flags zero, unconfigured/unhomed startup.
Restored captured Gentle 600/600, Normal 2500/1500 and Fast 3500/2000 profiles.
App reopened connected/fresh/compatible on Auto, no queued action; the saved
second-clamp enable/footprint is retained. Only identity/status and profile
configuration were sent by the agent; no Home, arm, motion or valve test.

The final clamped-return controller test passed 196385 checks; existing C++
policies/sketches passed 26555 checks. The final focused dry-run/continuous-return
tests passed again. The new Qt/sketch outfeed-only overlap + pause path, 0.25
fallback, legacy clamp lockout, cycle intervention, pause checkpoints, acquisition,
homing and startup profiles passed. The broad run and isolated multiboard and
operator-return cases encountered native access-violation/interpreter-cache
crashes, so a clean full regression run is not established. These remain an
unresolved validation limitation; their logs are preserved. Physical acceptance
of the new clamped return remains pending.
