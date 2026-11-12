# Next bench session - current procedure

Use [Auto/Semi-Auto and intervention](AUTO_INTERVENTION_0222.md). App patch
0.22.2 uses existing 0.22 firmware; no flash is needed. Connect and Home, then
choose Automatic or Semi-Auto. Start with saw mains unplugged. Exercise Pause,
manual adjustment and Resume, and the selected repeat/scrap policy.

The older notes below are historical and do not describe the current workflow.

<details>
<summary>Historical bench notes (superseded)</summary>

Current prepared **0.19.0 / CARRIAGE_V13 / UNLOADED_V4**: single Manual Home,
full supported search bound, combined clamp/trigger/travel/brake/release cycle,
native Start Auto with the same cycle. Saw remains physically unplugged; guard
is a Teensy input only. Follow [Integrated dry runs](INTEGRATED_DRY_RUN.md).
0.18 was flashed and individual mechanisms passed. New combined acceptance pending.

Latest 2026-11-10: prepared **0.18.0 / CARRIAGE_V12 / UNLOADED_V3** replaces
Manual's repeated arms/checks with one enable gesture and hold-to-test trigger.
Not yet flashed; renewed isolation confirmation needed. Auto still never presses
the trigger. [Current Manual procedure](TRIGGER_TEST.md) supersedes 0.17 below.

2026-11-10 update: matching **0.17.0 / CARRIAGE_V11 / UNLOADED_V2** adds a
separate [Manual unpowered trigger test](TRIGGER_TEST.md). Auto still never
presses the blade trigger. Follow that procedure first; saw mains stay unplugged.
The prior 0.16 deployment below is historical. New physical acceptance pending.

Read the [prepared dry-run procedure](TONIGHT_DRY_RUN.md).

Matching app and **0.16.0 / CARRIAGE_V10 / UNLOADED_V1** firmware are prepared,
compiled/tested offline, then flashed/read back on COM4 with operator isolation
confirmed on 2026-11-09. **Physical testing remains pending.** Startup disarmed,
outputs OFF, position unknown, no queued motion; matching app required.

1. App closed, driver OFF, valve power disconnected, air isolated, saw unplugged:
   flash and verify prepared build. Boot disarmed with outputs OFF.
2. Check sensors and suppression/fuses. INA/MCP stay disconnected. Clamp ON
   holds/OFF releases; saw OFF returns UP. Blade trigger stays OFF.
3. Configure driver, Home, check short moves/Stop. Verify stored Normal/FAST
   after reboot; operator prefers below 4000 pps.
4. Load acknowledged Cylinder Timing settings, then accept one unloaded Manual
   clamp/stroke/return/release/Stop sequence before the cut-list test.
5. Add a short list and select Load. Run the separate unloaded test. Manually
   trip and **hold** Limit Y detector at SEARCH until truing motion starts, then
   release. Observe truing, list feeds/strokes, release and FAST return.
6. Record Stop, guard, endpoint, driver-alarm and communication-loss responses
   in the [fault matrix](TEENSY_FAULT_ACCEPTANCE_MATRIX.md). No automatic retry.

No board or blade power tonight. Unloaded stop/fault **releases** the clamp and
requests UP. Clamp readback is commanded, not verified grip. Production Start
Cycle/Resume remain unavailable. Trigger controls are only the separately armed
unpowered test described above, not part of Auto.

RAM profiles reset at reboot. Historically restored values: Gentle 150/200,
Normal 3500/4000, Fast 2500/1500 (pps / pps squared); records, not instructions
to overwrite later operator settings. Smooth 3000/1500 was reported; around
4000 pps a following error occurred. Driver reset investigation remains deferred.

Artifacts/source manifests: `tmp/commissioning/0.16.0`; deployed rollback
`tmp/commissioning/0.15.0`. Local commits/artifacts are not remote backup.
Update the [master checklist](../TEENSY_APP_MIGRATION_CHECKLIST.md) after tests.

</details>
