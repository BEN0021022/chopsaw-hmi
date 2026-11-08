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
