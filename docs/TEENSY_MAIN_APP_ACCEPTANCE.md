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
