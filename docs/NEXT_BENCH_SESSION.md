# Next bench session

Prepared 2026-11-08 while the operator was away. After the operator returned
and confirmed app closed/driver OFF, 0.13.0 was flashed/read back on COM4 and
the matching app reopened. Startup is disarmed/unconfigured, unknown position
and zero queued motion. Continue with acceptance below; no motion was sent by
the agent. Checkpoint `cab3a16` preserves matching 0.11.0 source; profile-only
checkpoint is `dd333ce`. The loading section remains for subsequent reloads.

Latest: the operator reported 0.13.0 testing good and requested faster,
editable rates. **0.14.0 is now flashed/read back**, and the matching app is
reopened disarmed. Native rate/acceleration controls are described in
[speed tuning](SPEED_TUNING.md); default Fast is 2500 pulses/s, not the old
127-pulses/s commissioning cap. Pre-tuning 0.13.0 is at `8602038`.

## Load and verify together

Close the current app to release COM4 and turn driver power off. Keep saw mains
unplugged, valve 12V disconnected, air isolated and suspect INA/MCP disconnected.
Load prepared 0.13.0, then read back HELLO/PINMAP/STATUS before opening the new
app. Expect CARRIAGE_V7, STEP2_DIR3_EN40, 127.12 pulses/inch, Commissioning
profile 0, disarmed/unconfigured, unknown position and no queued motion. Reading
identity must not arm, enable, home or move anything.

## Accept in this order

1. Reconfirm driver/door/saw-UP conditions and Home near the sensor with the
   default short search. Existing Home success does not replace rehoming after
   a flash, fault or motor release.
2. Keep Commissioning speed and accept the pending 0.11.0 absolute feature:
   approximately 0.1 inch toward the saw, then back to Home/load. Check displayed
   endpoint and STOP. Confirm the complete path before any long load preset.
3. Disarm, select an editable profile, enter pulse rate and acceleration, and
   apply. Inspect the acknowledged values before arming for the operator's test.
   A short move may not reach full speed because it ramps up and down; higher-rate
   physical operating limits remain to be established. See SPEED_TUNING.md.
4. Accept stationary board sensor operation, then a short bounded edge search
   with supported stock and verified clearance. Detection must stop/disarm.
   Review the captured geometry before rearming for the separate truing move.
5. After suppression/fuses and individual pneumatic hardware checks, return to
   blade-disconnected air commissioning. This prepared main-app build still
   exposes carriage controls only. Clamp retention/fault behavior and combined
   sequencing remain unresolved work before automatic cycles.

Record results in [the master checklist](../TEENSY_APP_MIGRATION_CHECKLIST.md).
Physical fault tests, the collision envelope and the recovered blade reference
remain open. No automated software check marks those items complete.

Detailed instructions: [profiles](MOTION_PROFILES.md),
[board edge/truing](BOARD_EDGE_COMMISSIONING.md),
[absolute targets](ABSOLUTE_POSITIONING.md), [Home](HOMING_COMMISSIONING.md).
