# Counted-position fault recovery - 0.27

Deployed 2026-11-19: firmware **0.27.0 / CARRIAGE_V20**, capability
`RECOVERY:COUNTED_STOP_V1`. Flashed/read back on COM4; physical acceptance pending.

## Operator workflow

A guard/saw-sensor fault immediately stops pulses, releases the trigger and
returns saw travel toward UP. Any engaged clamps remain held. The active
cut-list checkpoint retains the first cut without a confirmed completion.
Clearing the error never restarts motion or a stroke.

1. Clear the cause and allow the saw to return UP. If clamps were retained,
   use **Release retained clamps** in Auto when its existing release conditions
   permit it. Clear Error stays unavailable until they are released.
2. **Confirm / Clear Error** clears the latched fault. Home, jog and Load become
   available with a healthy link, clear actuators and a known carriage reference.
3. Move stock back out of the detector/clamp area as needed. The checkpoint
   remains active through manual positioning; Pause is unavailable in recovery.
4. With the detector clear, press **Resume Cycle**. The system acquires stock
   on Gentle, advances sensor distance plus kerf continuously, makes a new
   truing cut, then continues the unfinished cut list using the usual profiles.

The previous material location is discarded on fault; the new detector capture
establishes it again. A partially executed cut is not marked complete. A matching
late controller DONE advances its pending index once; unexpected count/config
changes block Resume for reconciliation. List/reference edits also block Resume.
**Cancel Cycle** explicitly discards the checkpoint while retaining the entered
list. **Stop** remains available and does not erase an existing fault checkpoint.
If all cuts were confirmed before the fault, finite-list Resume finishes without
repeating them; a repeat list acquires the next board from its first cut.

## Position confidence

The stored coordinate is the count of emitted pulses, **not encoder feedback**.
Controlled door, conflicting/lost saw-position signals and saw endpoint timeout
stops preserve an already-known coordinate only with a configured controller,
healthy driver alarm and no active homing. Holding enable is retained. This also
applies to a controlled sensor stop during the last-cut carriage return.

Driver alarm (including one arriving after the first sensor fault), watchdog,
invalid command, Home/edge/soft-limit failure, interrupted homing, motor release
and restart still invalidate position. Home is then required before manual
referenced movement or Resume. A reference is never created just by clearing an
error. An application restart/disconnect does not persist this in-memory cycle
checkpoint. Recovery does not prove that stock remained against the pusher.

## Verification and deployment

- Full offline regression harness passed on the private Python 3.13.17 runtime:
  actual C++ sketch, protocol replay and Qt integrations, both clamps, early
  returns, multi-board scrap handling, Pause, homing, profiles and wheel guard.
- New actual-sketch/Qt tests interrupt cut two during feed and during a clamped
  saw stroke. They verify stationary retained coordinates, guarded clamp release,
  Clear Error without motion, manual Load/jog availability, clear-detector Resume,
  Gentle acquisition/truing, cuts two/three only and nonduplicated cut history.
- Firmware checks cover controlled sensor retention, later driver alarm loss,
  reboot unknown state and controlled stops during the clamped early return.
- Teensy 4.1 compilation succeeded. Artifacts and test logs are under
  `tmp/commissioning/0.27.0`. Final added return-stop assertions and recovery tests
  also pass after the broad run.

Earlier intermittent native Qt/interpreter crashes remain an unresolved runtime
issue; the clean run here does not establish their cause or fix. No physical
motion or valve commands were sent during development. Deployment must capture
the existing RAM profiles, flash only after hardware isolation confirmation,
read back idle/off startup and restore those profiles. Physical recovery tests
remain to be performed by the operator.

Upload and readback succeeded after the operator confirmed driver power OFF,
valve power disconnected, air isolated and saw mains unplugged. Startup was
disarmed, unconfigured/unhomed, with outputs OFF and second clamp disabled until
normal app configuration. Captured profiles were restored: Gentle 600/600,
Normal 2500/1500 and Fast 3500/2000. The matching app reopened on Auto,
connected/fresh/compatible, no faults or queued actions; saved outfeed enable
and geometry remain intact. No Home, arm, motion or valve commands were sent.
Source `3df2b0df517f0b8620aacc77f42f39212a9c6deb`, firmware tree
`f4e591ce27c4feb0746d4750c54116465140fcfd`; artifact hashes and deployment
captures are recorded in the local manifest. Rollback 0.26 is preserved.
