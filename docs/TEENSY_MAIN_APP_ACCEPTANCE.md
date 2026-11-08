# Main-app carriage acceptance record

2026-11-08 software integration, controller 0.7.0.

Completed in software:
- New Teensy Carriage backend and CARRIAGE tab on the existing main serial connection.
- Recovered 127.12 pulses/inch, arbitrary bounded 1-254 pulse jogs, direction labels.
- Controller pulse-count displacement and MOVE_ID acknowledgments; no homed position claim.
- Fresh identity/safety/motion guards, explicit setup/arm, stop/disconnect/reboot handling.
- Main-app raw-write rejection of MEGA, G-code and pneumatic commands.
- Native firmware: 83 policy, 87 frozen-bench integration, 94 controller integration
  checks passed. New main-app Qt, backend, safety and Sensor Bench tests passed.
- Existing simulator manual/automatic cut-list cycles passed. Arduino compile passed.
- App layout inspected at 1280x900 using an offscreen Qt rendering with Segoe UI.
- Firmware flashed and read back on COM4 with new app identity, D40 mapping,
  disarmed/unconfigured, zero move/budget/count, STEP/DIR LOW and ENA HIGH.

No hardware jog, enable, arm or pneumatic command was sent by the agent during
integration. Driver power OFF and saw/air/valve isolation were confirmed by user.

Main app launched and connected to COM4 in Teensy Carriage mode. Identity
accepted, motion/safety telemetry fresh, disarmed/unconfigured and zero pulses
queued. No arm/configure/move sent by the agent.

Pending operator checks in main app:
- [ ] Fresh Home transition, door closed, Saw UP only; driver healthy.
- [ ] Setup/arm acknowledgment; initial 0.1-inch jog A and B.
- [ ] Verify commanded displacement, completed jog and budget behavior.
- [ ] Stop during motion; no automatic resume.
- [ ] Controlled guard/alarm/Home cancellation; reset never arms.
- [ ] Disconnect and reconnect; no automatic motion or stale position authority.

This record does not establish production cutting, automatic homing, absolute
blade reference, pneumatic sequencing or independent safety acceptance.

## Manual jog update: controller 0.9.0

User reported the old step allowance exhausted during carriage testing. Source
confirmed 254 cumulative pulses per arm, with automatic disarm at zero. Version
0.9.0 removes that cumulative allowance from native manual mode. Each click is
still limited to 254 pulses (~2 inches), at 40 pulses/s, with no queued moves.
Completed moves remain armed. STOP, Home/driver/guard/saw faults and heartbeat
loss still cancel/disarm; there is no automatic rearm or unsolicited movement.

The main app now requires CARRIAGE_V3 / MANUAL_JOG_V1 and MAX_JOG/RATE_PPS;
JOG_READY gates buttons until driver enable has settled. Status prompts identify
missing isolation confirmation, Home-input verification or setup/arm steps.

Validation: 83 policy, 87 frozen-bench integration and 111 manual-controller
checks passed. The manual tests include six 254-pulse moves under one arm,
40 pulses/s across rapid jog boundaries, pulse counts/directions, all fault/stop
cancellations, malformed commands, no catch-up bursts and timer rollover. Main-app
Qt tests exercise twenty consecutive two-inch requests without an arm allowance.
Backend, UI boundary and Sensor Bench regression checks passed. Arduino build
passed; 0.9.0 flashed and read back on COM4, disarmed, zero pending steps, ENA HIGH.
Driver power OFF and machine isolation confirmed before flashing. No physical
arm/jog/enable was commanded by the agent; operator acceptance remains pending.

### Startup Home check change

At the user's request, 0.9.0 manual setup no longer requires a Home LOW/HIGH
transition on restart or motor release. Firmware and app use HOME_CHECK:LEVEL_ONLY
and CARRIAGE_V3: actual Home must be clear, with door/saw/driver checks unchanged.
An active Home input still blocks setup and trips active motion. No machine
coordinate or homed state is inferred. Tests explicitly arm and jog from a fresh
boot without any Home transition and also verify active-limit rejection.
The manual-controller suite now passes 111 checks, including a long-armed-idle
microsecond timing regression. Operator confirmation in the reopened app remains
pending. No arm/jog/enable was sent by the agent during this update.

## Homing update: controller 0.10.0

User confirmed manual motion testing passed before this update. Implemented
bounded XHOME with default two-inch initial search, start-on-sensor release,
backoff, slow latch, release and pull-off. Success establishes the recovered
160.5-inch sensor reference and disarms; displayed position accounts for the
pull-off. Interruptions/faults/reboot/motor release invalidate position.

Validation: 83 policy, 87 frozen-bench, 112 manual-controller and 209 homing
policy/sketch checks passed. Main-app/Qt, backend and capability-boundary tests
passed; legacy simulator/manual/full-cycle regressions passed. Layout rendered
and inspected at 1280x900, dark scrollable content and fixed STOP controls.
Arduino compile passed; flashed/read back on COM4, correct homing identity,
Home IDLE, unconfigured/disarmed, unknown position and no queued motion.
Main app reopened and accepted fresh telemetry with search default 2.00 inches.
No HOME/arm/jog/enable command was sent by the agent. User confirmed driver
power OFF and saw/valve/air isolation before flashing.

Pending physical acceptance: first bounded Home from near sensor, repeatability,
reference correctness, stop and failure behavior. Absolute moves remain blocked.
Operator instructions: HOMING_COMMISSIONING.md. Remaining rough effort estimate:
MIGRATION_EFFORT_ESTIMATE.md (12-24 active hours plus physical/hardware time).

## Referenced positioning update: 0.11.0

User reported automatic homing succeeded on 0.10.0. Added inch targets,
Home/load and 135/111/87/63-inch presets, firmware request/per-pulse soft limits,
full-step rounding, long-move telemetry and guarded main-app set_length routing.
New 113 positioning checks passed alongside 83 policy, 87 bench, 112 manual and
209 homing checks. Qt/backend/boundary/Sensor Bench checks pass. New firmware
compiled and flashed/read back on COM4, disarmed and no reference/queued move.
No motion/arm/Home command sent by the agent. New absolute/load physical tests
are pending; existing Home success is not a physical lower-envelope acceptance.
MIGRATION tab now shows the master checklist without editing it or moving hardware.

## Offline preparation while operator away: 0.12.0 and 0.13.0

Live board and open app remain at 0.11.0. No flash, arm, Home, jog, valve or
other hardware-output command was sent during this preparation.

0.12.0 adds bounded Commissioning/Gentle/Normal/Fast profiles with acknowledged,
disarmed-only RAM selection. 0.13.0 includes those profiles plus bounded edge
search and an explicit separate captured truing move. Home remains the sole
coordinate reference. Detection disarms; stale captures cannot be replayed.
No main-app pneumatic or automatic cutting path is enabled.

Native checks: 83 policy, 87 frozen bench, 112 manual controller, 209 Home,
113 positioning, 1637 profile/ramp and 165 board-edge checks pass. Real sketch
serial output replays into the real Qt panel (55 motion records). Main-app,
backend, safety-boundary and Sensor Bench regressions pass. Arduino Teensy 4.1
compile passes. See MOTION_PROFILES.md and BOARD_EDGE_COMMISSIONING.md for
pending physical acceptance; no new physical pass is implied.

Manual-mode and complete cut-list simulator regressions pass. Offscreen Qt
layout was rendered and inspected at 1280x900 using the Windows Segoe UI fonts:
new edge/geometry controls fit without horizontal overflow, and STOP/release
remain outside the scrolling area. This was a mock-window render, not a live
machine-control test or an interaction with the open hardware session.
