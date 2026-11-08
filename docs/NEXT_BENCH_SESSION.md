# Next bench session

Prepared 2026-11-08 while the operator was away. The board and open app remain
on 0.11.0. New source is 0.13.0; do not mix the edited app with old firmware
and expect motion to be available. Checkpoint `cab3a16` preserves the matching
0.11.0 source. Profile-only checkpoint is `dd333ce`.

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
3. Disarm and apply Gentle; inspect acknowledged rate/acceleration. Accept short
   out-and-back, stopping and direction changes before Normal or Fast. A label
   named Fast is still initially capped at about one inch/second.
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
