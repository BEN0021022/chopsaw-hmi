# Next bench session - after 2026-11-08

Active firmware/app: **0.15.0 / CARRIAGE_V9 / LOAD:FAST_V1**, verified on COM4.
The latest app reopened on AUTO, disarmed, with no queued motion. No Home,
arm, jog or load was sent by the agent during deployment. A flash clears the
position reference: Home again before absolute or load moves.

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
