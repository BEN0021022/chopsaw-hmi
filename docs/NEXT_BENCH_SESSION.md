# Next bench session — 2026-11-09 unloaded testing

Read [Tonight's readiness audit and P0 implementation queue](TONIGHT_DRY_RUN.md).
Confirmed: no stock/cuts, saw mains unplugged, blade-trigger output disabled,
main clamp ON holds/OFF releases, saw valve OFF returns UP.

**Current baseline is still 0.15.0 / CARRIAGE_V9 / LOAD:FAST_V1.** It supports
carriage and separate single-output tests, not a held-clamp/saw cycle. Today's
Manual actuator/timing sequence is Simulator-only. Native cut-list stepping and
combined dry-run firmware/app work remain in the queue; a new combined build is
not yet prepared. Do not unlock Simulator handlers or fake board-edge detection.

All seven host firmware suites and 55 actual-sketch Qt motion records passed
again on 2026-11-09. Archived HEX checksum/source tree match the 0.15.0 manifest.
No flash has been performed during this offline preparation.

## Historical 2026-11-08 deployment record

Firmware 0.15.0 was verified on COM4. The app reopened on AUTO, disarmed, with no
queued motion. No Home, arm, jog or load was sent by the agent during deployment.
A flash clears the position reference: Home again before absolute or load moves.

At deployment, saved RAM profiles were restored: Gentle 150/200, Normal
3500/4000, Fast 2500/1500 (pulse rate/acceleration). Commissioning was selected.
Later operator edits remain authoritative; these are deployment records, not
instructions to overwrite settings. RAM profile edits reset on controller reboot.

## First checks

1. Keep saw mains unplugged, valve power disconnected and air isolated. Power
   the driver and confirm its healthy indication and carriage clearance.
2. Confirm shared preparation/setup. Home while disarmed. The shared search
   defaults to two inches; select an appropriate bounded limit on MANUAL/CARRIAGE
   if farther from the sensor.
3. On AUTO, explicitly arm and test short jogs both ways and STOP. Then test
   selected stock Load Position with the whole path clear. Load uses stored FAST.
4. Verify Home, board edge, door, saw endpoints and driver-alarm pills. Clamp
   stays UNKNOWN without feedback; current sensing remains deferred.
5. Test cut-list Add/import/edit/update/clear. Planning sends no motion.
   Cycle Start/Resume remain unavailable; Cut Complete is removed.

## Following work

- Accept board-edge search and the separate captured truing move.
- Fit/verify coil suppression and fuses; test individual pneumatic outputs with
  blade power disconnected.
- Define clamp retention and fault/air-loss behavior before combined sequencing.
  Then migrate automatic cut-list completion/recovery.
- Complete physical fault acceptance, release and GitHub backup.

The operator confirmed Home and profiles working, with smooth motion at
3000 pps / 1500 pps?. Around 4000 pps a seven-flash following fault occurred;
the operator chose to stay below 4000. ENA release did not clear that driver
fault; further reset work is deferred. No automatic retry was introduced.

Rollback source: `e51f14f` (pre-AUTO, firmware 0.14.0), `cab3a16` (0.11.0).
Local manifests/readbacks are under `tmp/commissioning`. Local commits/artifacts
are not a GitHub backup or published release.

Record results in [the master checklist](../TEENSY_APP_MIGRATION_CHECKLIST.md).
Details: [Auto](AUTO_TAB_COMMISSIONING.md), [speed tuning](SPEED_TUNING.md),
[edge/truing](BOARD_EDGE_COMMISSIONING.md), [fault tests](TEENSY_FAULT_ACCEPTANCE_MATRIX.md).
