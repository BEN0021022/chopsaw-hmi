# Recovery and pneumatic commissioning checklist

Updated 2026-11-08. This records user observations separately from unfinished
machine protections. It is not authorization for blade-powered cutting.

## Recovery checks completed

- [x] New Teensy 4.1 identified, flashed, and responding on COM4.
- [x] Empty breakout visually inspected; user found no visible damage.
- [x] USB-only logic test: approximately 4.85V and 3.3V reported by user.
- [x] External 5V / USB power-blocker setup: communications and rail checks passed.
- [x] Door switch transitions confirmed by user on Door/D29.
- [x] Saw Up originally confirmed on Cyc/St/D17; later reported not working.
- [x] Prepare build 0.4.1 moving Saw Up to Limit Z/D22; compile, HMI tests,
      83 policy checks and 21 serial integration checks passed.
- [x] Flash 0.4.1 and verify INPUT_MAP:DOOR29_UP22_DOWN16 and D22/LIMIT_Z
      assignment on COM4 with outputs OFF/disarmed. No output-ON commands sent.
- [x] User confirmed actual Saw Up switch on Limit Z/D22 works and dashboard
      reports ready with door closed and saw up. Leave Cyc/St disconnected.
- [x] Saw Down transitions confirmed on Fd/Hld/D16 after terminal insulation was corrected.
- [x] Banner board-edge sensor tested successfully on Limit Y/D21 with 12V supply.
- [x] AUX1/D32 and AUX2/D33 MOSFET indicator tests passed, reported by user.
- [x] Flood/D19 MOSFET indicator test passed, reported by user.
- [x] Firmware 0.3.2 and HMI agree on output map AUX2_AUX1_FLOOD.
- [x] Output-map mismatch blocks HMI output-test arming; automated UI tests pass.
- [x] MCP23017 and INA228 set aside and kept disconnected.
- [x] AUX0/D31 removed from commanded outputs after an approximately 0.01V output test.
- [ ] ST0/ST1 buffer/socket investigation deferred; do not assume those paths healthy.
- [ ] Limit X physical sensor validation not yet recorded.

## X-axis preparation

- [x] User confirmed motor is coupled, both directions have clearance, selector
      is 5V, ENA/ALM connected, SW1-SW4 all ON/full-step, driver power OFF for setup.
- [x] Prepare 0.5.1 single-step diagnostic; 83 policy and 40 serial integration
      checks passed, HMI regression passed, and Teensy compilation passed.
- [x] Flash and identify 0.5.1 with X_TEST:SINGLE_STEP_V1; readback STEP=0,
      DIR=0, ENA=1, zero budget, unconfigured/disarmed, and pneumatic outputs OFF.
      No STEP commands sent. Fixes ENA startup latch initialization found in 0.5.0.
- [ ] Measure X STEP/DIR/ENA levels with driver power OFF.
      User confirmed DIR switches and Home verification passes. X En remains
      approximately 4.85V with driver power OFF and dashboard ENA=0; unresolved.
      User then confirmed the same 4.85V unloaded with driver physically
      disconnected. Retire Axis X En path pending repair; exact cause unconfirmed.
- [x] Remap X enable to spare Axis Y En/D40 in 0.5.2; 83 policy + 43 integration
      checks, HMI tests, and Teensy build passed. Flash/readback confirmed new
      X_MAP:STEP2_DIR3_EN40 and disarmed zero-budget state.
- [x] User confirmed unloaded Axis Y En switches LOW/HIGH and X DIR switches.
- [x] User confirmed remapped ENA=0 produces motor holding torque.
      Enable profile is LOW (0); original Axis X En stays disconnected.
- [x] User confirmed physical Limit X LOW/HIGH transition and HOME_VERIFIED=1
      before 0.5.2 reboot; repeat after reboot. Driver healthy ALARM_RAW=1.
- [x] Validate remapped enable behavior with driver powered after voltage checks:
      user confirmed LOW enables motor holding. No STEP command recorded yet.
- [x] User performed single-pulse checks: audible clicks, travel too small to
      see. Direction and actual displacement remain unverified.
- [x] Prepare 0.6.0 interruptible bounded jogs: 13/64/127 pulses per click,
      254-pulse total budget, 40 pulses/s. 83 policy + 87 scheduler/command
      checks, Qt tests, and Teensy compile passed.
- [x] Flash/read back 0.6.0 on COM4: BOUNDED_JOG_V1, correct D40 map,
      disarmed/unconfigured, zero budget/remaining, STEP/DIR LOW, ENA HIGH.
      No physical jog commands sent during software verification.
- [x] User reported seven-flash CL57T position-following fault during jogs,
      found a loose encoder wire, secured it, and confirmed motion then works.
      This is an observed resolution, not a complete motor/encoder acceptance test.
- [x] User confirmed direction A (DIR LOW) moves toward the saw; direction B
      (DIR HIGH) moves away from the saw toward the homing sensor.
- [x] Recover old MEGA V2.5 firmware calibration: 127.12 pulses/inch at
      full stepping. Preserved exact source and checksum under archive/legacy-mega-v2.5.
      User requests reuse of the previously dialed-in value instead of remeasurement.
- [ ] Validate alarm/limit/door cancellation under controlled carriage motion.

See [X stepper commissioning](X_STEPPER_COMMISSIONING.md). No continuous jogging,
homing, production position, or automatic cycles are established.

## Current output assignments

| Command | Function | 5V TTL/SSR header | Pin |
|---|---|---|---|
| OUT 0 | Saw travel valve | AUX2 Sig/Gnd | D33 |
| OUT 1 | Main left clamp valve | AUX1 Sig/Gnd | D32 |
| OUT 2 | Blade-trigger pneumatic valve | Flood Sig/Gnd | D19 |

## Before powering solenoid loads

- [x] User confirmed saw mains plug physically disconnected; keep it disconnected throughout commissioning.
- [ ] Air supply isolated and stored pressure exhausted while wiring.
- [ ] Each valve coil voltage, current, polarity, and branch fuse checked.
- [ ] Actual flyback suppression verified at each inductive coil/output;
      an indicator LED or MOSFET body diode alone is not confirmation.
- [ ] Current-sensor board and suspect MCP remain completely disconnected.
- [ ] Restore only reviewed fused 12V valve power after wiring with all power off.
- [ ] With air still disconnected, command one coil briefly; verify ON/OFF
      switching, stable logic communications, and stable power rails.

## Before putting air on the attached saw

- [x] User confirmed saw-travel valve OFF returns the saw fully UP and ON drives it DOWN.
- [ ] Define behavior on electrical power loss and on air loss; valve spring
      return alone does not establish the mechanical outcome on air loss.
- [ ] Confirm clamp OFF behavior and whether releasing it on a fault is acceptable
      for this blade-disconnected test. Do not adopt it as a cutting fault policy.
- [ ] Confirm switches sense actual endpoints and cannot both assert together.
- [x] Implement logic-only controller door/position checks and latched fault
      handling in build 0.4.0; 83 native policy checks, 19 serial integration
      checks, and HMI regression tests passed; Teensy compilation passed.
- [x] Flash 0.4.0; verify version/map/interlock identity and all outputs OFF,
      disarmed, with door-open / neither-endpoint status blocking ARM on COM4.
- [ ] User manual acceptance of the checks with valve power disconnected and
      air isolated. No output-ON commands were sent during flashing/verification.
- [ ] Define guarded operator position, clear travel/pinch areas, saw support,
      flow control, regulator setting, and an accessible manual air dump.
- [ ] Respect the installed AirTAC valve's minimum operating pressure: its
      photographed label states 0.15MPa minimum (approximately 22psi). Use the
      lowest suitable pressure within the valve's range and assess cylinder force.
- [ ] Test one mechanism at a time, briefly, with the blade electrically isolated.
- [ ] Verify OFF/return after each test; stop on unexpected direction, binding,
      missing position transitions, communication loss, or abnormal heating.

## Before any blade-powered testing

- [ ] Trigger cylinder releases the original switch fully on OFF and in defined
      loss-of-power / loss-of-air cases, without defeating the trigger return.
- [ ] Original brake behavior validated and blade stopping accounted for.
- [ ] Independent appropriate guarding, E-stop/hazardous-energy controls, and
      pneumatic fault response implemented and validated.
- [ ] Local machine state handling, travel timeouts, confirmation requirements,
      fault latching, and deliberate reset/rearm implemented and tested.
- [ ] No automatic restart from door closure, reconnect, reboot, or power restoration.

References: [switch plan](SAW_AND_DOOR_SWITCH_PLAN.md),
[pin map](TEENSY_PIN_MAP.md), [Sensor Bench guide](SENSOR_BENCH_GUIDE.md),
[TI explanation of inductive-load discharge](https://www.ti.com/document-viewer/lit/html/snvaa45).
