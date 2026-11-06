# Chop Saw HMI — Six-Stage Hardware and Software Roadmap

Project root: `C:\Users\bensc\Projects\ChopSawHMI`

Goal: preserve the known-good Arduino Mega workflow while building a safe,
documented Teensy/grblHAL electronics stack for motion, sensors, pneumatic
clamps, automatic actuator control, and INA228 current monitoring.

Legend:

- `[x]` complete in the current working tree
- `[ ]` still required
- **Gate** means later work must not proceed until the gate is satisfied

## Design rules that apply to every stage

- [x] Keep Legacy Mega and the simulator available during migration.
- [x] Default automatic clamp/saw control to OFF.
- [x] Treat unsupported controller operations as blocked, not successful.
- [ ] Keep emergency stop, driver disable, actuator direction exclusion,
  pneumatic dump, and guarding independent of the Windows application.
- [ ] Define safe power-up, disconnect, watchdog-timeout, and reboot states for
  every physical output before connecting a load. Clamp-test D31-D33 now have
  these controls in firmware; physical validation and all other outputs remain.
- [ ] Never assign a Teensy pin until the exact Teensy, breakout/carrier board,
  grblHAL board map, voltage domain, and boot behavior are documented.
- [ ] Preserve spare protected inputs, outputs, I2C capacity, and connector
  positions for future sensors.

## Stage 1 — Stabilize, document, and checkpoint the baseline

### Repository and reproducibility

- [x] Move the active project out of OneDrive to the stable project path above.
- [x] Remove stale project-name and old-path references.
- [x] Confirm Git access and repository integrity.
- [x] Preserve the existing GitHub remote.
- [x] Add a project README with setup, test, build, mode, and safety notes.
- [x] Add pinned Python dependencies in `requirements.txt`.
- [x] Ignore local virtual environments and Python/test caches.
- [ ] Review the complete working-tree diff as one migration checkpoint.
- [ ] Commit and push the checkpoint to GitHub.
- [ ] Build and tag a known-good Mega-compatible release before production
  Teensy changes.

### Runtime and test stability

- [x] Give the serial listener an explicit stop event.
- [x] Close and join the serial listener during disconnect and application exit.
- [x] Stop the virtual-controller worker during close.
- [x] Stop listener exceptions from repeating forever during Qt shutdown.
- [x] Isolate UI tests from the operator's saved `QSettings`.
- [x] Make the full-cycle test explicitly enable automatic clamp/saw mode.
- [x] Add direct backend command-contract tests.
- [x] Add UI safety-boundary tests with in-memory serial hardware.
- [x] Run and pass the entire regression suite after the Stage 1/2 changes.

**Stage 1 gate:** all tests pass, the diff is reviewed, and the checkpoint is
committed/pushed before the real Teensy stack is energized.

## Stage 2 — Enforce controller capability and software safety boundaries

### Completed software boundaries

- [x] Add the controller backend layer and controller selector.
- [x] Persist controller mode in `QSettings`.
- [x] Preserve the Legacy Mega command translations.
- [x] Add explicit safety-relevant capabilities to each backend.
- [x] Keep Teensy Hardware Test and grblHAL operational tabs locked until their
  required feedback and protocol handling are validated.
- [x] Lock controller and serial-port selection while connected.
- [x] Report unsupported actions instead of silently treating empty commands as
  success.
- [x] Update clamp state only after a command was actually sent.
- [x] Start position prediction only after a move command was actually sent.
- [x] Remove the fake two-second saw-complete event from real connections.
- [x] Require genuine saw-position feedback before completing an automatic cut.
- [x] Release clamps and block the cycle when automatic saw capability is absent.
- [x] Invalidate delayed clamp/saw callbacks when a cycle is canceled,
  disconnected, restarted, or resumed.
- [x] Add one HMI actuator-direction API with an off-first forward/reverse command
  sequence.

### Hardware-independent safety work still required

- [ ] Add a controller heartbeat/watchdog contract and visible communication-loss
  fault state.
- [ ] Add timeouts for homing, motion, clamp confirmation, saw-down, and saw-up.
- [ ] Add explicit machine states: `SAFE`, `NOT_HOMED`, `READY`, `MOVING`,
  `CLAMPING`, `CUTTING`, `FAULT`, and `ESTOP`.
- [ ] Require fault acknowledgment and re-home where position certainty is lost.
- [ ] Define soft travel limits and collision envelopes in one shared machine
  configuration.
- [ ] Define and test positive/negative carriage direction before powered motion.
- [ ] Prevent motion while saw-down, actuator-unsafe, guard-open, or clamp states
  violate the final sequence.
- [ ] Add firmware and electrical actuator forward/reverse exclusion; the HMI
  interlock is only one layer.
- [ ] Decide which faults may be reset from the HMI and which require a physical
  reset.

**Stage 2 gate:** an incomplete backend cannot expose operational controls or
manufacture successful feedback, and the final hardware design has independent
fail-safe layers.

## Stage 3 — Hardware architecture, inventory, BOM, and Teensy pin map

This is the next planning stage and the ordering gate.

### Inventory and architecture

- [ ] Inventory everything already owned, ordered, or installed, including exact
  manufacturer part numbers and board revisions.
- [x] Identify the controller as a PJRC Teensy 4.1 on a Brookwood Design / The
  Grbl Project T41U5XBB V2.20 breakout board.
- [x] Start `docs/HARDWARE_INVENTORY.md` from the photographed owned hardware;
  unidentified modules and missing ratings remain explicitly open.
- [x] Start `docs/POWER_ARCHITECTURE.md` with the safe USB-only bench state and
  planned voltage domains; select a verified data-only USB cable for external
  5 V operation while leaving JP105 unmodified.
- [ ] Record the stepper/servo driver, motor, encoder, power supplies, contactors,
  relays, valves, actuator, sensors, E-stop devices, and existing Mega wiring.
- [ ] Draw a block diagram showing mains, 24 VDC, motor power, 5 V, 3.3 V,
  grounds, isolation boundaries, USB, I2C, and field wiring.
- [ ] Decide whether machine I/O is 24 V industrial, 12 V, 5 V, dry-contact, or a
  documented mixture.
- [ ] Select protected/isolated input conditioning suitable for every sensor
  voltage and signal type.
- [ ] Select output drivers for pneumatic valves, relays/contactors, actuator
  direction, enable lines, and future auxiliary loads.
- [ ] Define flyback, fuse, transient, reverse-polarity, and connector protection.
- [ ] Calculate power budgets and fuse sizes for logic, sensors, valves, actuator,
  and motor controls.
- [ ] Decide the hardwired E-stop chain and how its state is reported back to the
  Teensy without making software responsible for stopping energy.

### INA228 current-monitoring design

- [ ] Identify the exact current to measure: carriage motor, actuator, saw, whole
  DC bus, or multiple branches.
- [ ] Record normal, acceleration, stall, and worst-case fault current ranges.
- [x] Select Adafruit INA228 product 5832 and confirm its 85 VDC common-mode
  limit, onboard 15 mOhm shunt, default `0x40` address, and 3.3 V logic option.
- [x] Visually confirm the owned INA228 front/back, terminal labels, open A0/A1
  address jumpers, board ratings, and apparent open VBUS jumper.
- [ ] Size the shunt for current range, measurement resolution, dissipation, and
  fault energy.
- [ ] Decide high-side versus low-side measurement and document grounding impact.
- [x] Confirm the USB-bench I2C voltage and addresses: MCP23017 at `0x27` and
  INA228 at `0x40`, both powered from the 3.3 V header. Final machine cable
  length/routing and motor-noise testing remain open.
- [ ] Decide whether one sensor is sufficient or reserve addresses/connectors for
  additional current channels.

### Pin-map document requirements

- [x] Create `docs/TEENSY_PIN_MAP.md` as the single authoritative pin map and
  record the assignments reported by the current validation firmware.
- [ ] Record every signal's Teensy pin, breakout terminal, connector/pin, wire
  label/color, direction, voltage, active level, pull-up/down, boot behavior,
  safe state, source/load, and firmware name.
- [ ] Reserve and document step, direction, enable, home/limit, board-present,
  saw-up, saw-down, fence/clamp confirmation, guard, E-stop status, and actuator
  limit inputs.
- [ ] Reserve and document clamp-valve, actuator forward/reverse, saw request,
  motor enable, alarm/reset, and spare auxiliary outputs.
- [x] Reserve Teensy D24/SCL and D25/SDA on the T41U5XBB I2C header for the
  INA228, MCP23017, and future uniquely addressed 3.3 V-compatible devices.
- [ ] Reserve UART/SPI/CAN or other expansion buses only after checking conflicts
  with the selected grblHAL board map.
- [ ] Maintain at least 25% protected input/output capacity as labeled spares.
- [ ] Check all assigned pins against Teensy boot straps, onboard LEDs, timers,
  PWM requirements, interrupts, and grblHAL ownership.
- [x] Create `docs/HARDWARE_BOM.md` with `OWNED`, `ORDERED`, `NEEDED`, and
  `OPTIONAL/FUTURE` sections; purchasing links and exact part numbers remain
  open where load ratings or module identities are unknown.

**Stage 3 gate:** BOM, voltage domains, safety architecture, current-sensor design,
and the reviewed pin map are complete before final wiring or PCB work.

## Stage 4 — Teensy bench firmware and standard HMI protocol

### Protocol contract

- [x] Write `docs/CONTROLLER_PROTOCOL.md` with Sensor Bench Protocol v2,
  controller identity, `MOTION:0`, and exactly three guarded test outputs.
- [x] Define framing, line endings, constrained command IDs, errors, status,
  output arming, keepalive timeout, maximum-on timeout, and OFF behavior.
- [x] Define sensor-bench heartbeat timing, stale-data handling, and a safe boot
  state in which D31-D33 are latched LOW before becoming outputs.
- [ ] Define normalized position, motion state, digital I/O, clamp, saw, guard,
  E-stop, actuator, current, voltage, temperature, and fault fields.
- [x] Keep the eight sensor telemetry names stable and parse both Protocol v1 and
  the earlier validation firmware's `KLF_IO`/I2C scan format.
- [ ] Decide whether final machine I/O uses a grblHAL plugin, auxiliary commands,
  custom M-codes, or a companion firmware channel.
- [x] Add representative Protocol v2, Protocol v1, and legacy serial records plus
  command-boundary and offscreen UI tests in `test_sensor_bench.py`.

### Hardware-test mode

- [x] Add the Teensy Hardware Test backend.
- [x] Map validation outputs `OUT 0/1/2` to the three clamp outputs.
- [x] Map validation outputs `OUT 3/4` to actuator forward/reverse.
- [x] Send `PINMAP`, `I2C`, and `STATUS` on validation-mode connection.
- [x] Add a dedicated, standalone dark diagnostics HMI (`run_sensor_bench.py`)
  instead of reusing machine-operation tabs.
- [ ] Add momentary actuator controls with off-before-direction sequencing.
- [x] Parse legacy `KLF_IO` and Protocol v1 direct/MCP inputs while displaying
  raw level separately from adjustable interpreted state.
- [x] Add visible `PINMAP`, `I2C`, `STATUS`, all-outputs-off, guarded clamp
  controls, host keepalive, firmware watchdog, and maximum-on timeout.
- [x] Map clamp-test outputs D31-D33 to JP10 AUX0-AUX2 TTL/SSR signal rows and
  document why the AUX screw-terminal sink outputs are not used.
- [ ] Bench-test logic with field loads disconnected.
- [ ] Test one protected input and one low-energy output channel at a time.
- [ ] Validate power-up, USB disconnect, firmware crash, and reboot safe states.

**Stage 4 gate:** the versioned protocol and validation firmware pass bench tests
before motion, valves, or the actuator are connected.

## Stage 5 — grblHAL motion, machine I/O, pneumatics, and current monitoring

### grblHAL motion integration

- [x] Add a prototype grblHAL backend.
- [x] Prototype `$H` homing and `G20 G90` absolute X moves.
- [x] Keep grblHAL operational UI locked while protocol support is incomplete.
- [ ] Select and archive the exact grblHAL Teensy build, board map, plugins, and
  settings used by the machine.
- [ ] Implement command queueing and wait for `ok`/`error` before sending the next
  queued command.
- [ ] Parse `ALARM` and `<...>` reports including `MPos`, `WPos`, state, limits,
  feed, and overrides.
- [ ] Establish machine coordinates, positive direction, home direction, travel,
  steps per inch, acceleration, and conservative feed limits.
- [ ] Validate hard limits, soft limits, feed hold, cycle start, reset, alarm
  recovery, and USB loss with the motor mechanically disconnected first.
- [ ] Add collision-envelope tests for carriage, fence, blade zone, actuator, and
  service/load positions.

### Pneumatics and automatic actuator

- [ ] Finalize clamp and actuator output commands in the selected firmware path.
- [ ] Add sensors that prove required clamp/fence positions rather than relying
  only on elapsed time.
- [ ] Add actuator end limits or position feedback appropriate to the mechanism.
- [ ] Require saw-up confirmation before carriage motion or clamp release.
- [ ] Require valid board, guard, pressure, E-stop, and actuator states before an
  automatic cut request.
- [ ] Validate the complete sequence with air pressure reduced and the blade/motor
  disabled before powered cutting.

### INA228 software rollout

- [ ] Read INA228 data in the Teensy/firmware layer and transmit normalized units.
- [ ] Add telemetry parsing while preserving legacy Mega ACS712 fields.
- [ ] Display and log passive voltage/current/power/temperature data first.
- [ ] Calibrate against trusted meters across idle, moving, acceleration, and
  controlled-load conditions.
- [ ] Add warning thresholds only after passive data is stable.
- [ ] Add firmware-side protective response independent of the HMI where
  appropriate.
- [ ] Consider stall detection or adaptive feed only after false-positive,
  response-time, and failure-mode testing.

**Stage 5 gate:** motion and machine I/O work independently, then together, with
real feedback and passive current telemetry proven before automatic adaptation.

## Stage 6 — Full validation, documentation, release, and expansion readiness

### Validation matrix

- [x] Preserve and run Legacy/manual-mode simulator coverage.
- [x] Preserve and run automatic clamp/saw simulator coverage.
- [x] Preserve updater integrity tests.
- [ ] Run the application against the physical Legacy Mega baseline.
- [ ] Run every Teensy Hardware Test input/output against the reviewed pin map.
- [ ] Run grblHAL homing and motion tests at reduced energy/speed.
- [ ] Verify actuator forward and reverse can never energize together through
  software, firmware, wiring, relay/driver behavior, reboot, or communication
  loss.
- [ ] Fault-inject unplugged USB, controller reboot, stale heartbeat, stuck sensor,
  open guard, E-stop, motor alarm, overcurrent, missing board, low pressure, and
  saw-position timeout.
- [ ] Verify every fault removes or inhibits the correct energy and requires the
  correct recovery sequence.
- [ ] Run dry cycles, reduced-energy cycles, and supervised production cycles in
  that order.

### Release and future expansion

- [ ] Document wiring, connectors, labels, fuses, settings, firmware flashing,
  calibration, operation, maintenance, and troubleshooting.
- [ ] Photograph the completed electronics and terminal blocks and link them to
  the pin-map/BOM revisions.
- [ ] Record firmware, HMI, wiring, and hardware revision compatibility in every
  release.
- [ ] Build, checksum, tag, and publish the validated release.
- [ ] Back up source, firmware, configuration, pin map, BOM, and release assets to
  GitHub.
- [ ] Keep spare sensor channels electrically protected and disabled in software
  until assigned and tested.
- [ ] Maintain a future-sensor backlog without changing the validated core
  protocol fields.

**Stage 6 gate:** production release only after the documented hardware revision
passes the complete safety and fault-injection matrix.

## Immediate next information needed for Stage 3

- [x] Exact Teensy model: PJRC Teensy 4.1.
- [x] Exact breakout/carrier board: Brookwood Design / The Grbl Project
  T41U5XBB V2.20.
- [x] Clear component-side photos of the populated Teensy/breakout assembly and
  the current prototype layout.
- [ ] Back-side photos and close-ups of all remaining unidentified module IC and
  MOSFET markings.
- [ ] List of hardware already owned or ordered.
- [ ] Existing motor driver, motor, encoder, and supply specifications.
- [ ] Existing sensor types and operating voltages.
- [ ] Planned actuator and pneumatic valve voltage/current specifications.
- [ ] Which electrical branch(es) the INA228 should measure and their maximum
  expected voltage/current.
- [x] Primary current-monitor hardware selected: Adafruit INA228 product 5832.
- [x] Adafruit INA228 product 5832 physically located and photographed.
