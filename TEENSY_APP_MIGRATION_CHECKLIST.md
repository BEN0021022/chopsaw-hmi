# Teensy app and firmware migration checklist

Updated 2026-11-08. Active project: `C:/Users/bensc/Projects/ChopSawHMI-Teensy`.
Active firmware: custom **0.10.0** in `firmware/chopsaw_controller`.
Main app mode: **Teensy Carriage**. The breakout is a grblHAL-compatible board;
the currently flashed firmware is custom, not stock grblHAL.

`[x]` means implemented or observed as explicitly described. Software tests do
not establish physical machine safety or production-cutting readiness.
See [feature mapping](docs/APP_FEATURE_MIGRATION.md) for each old app feature.

## Stage 1 - Preserve the baseline and establish the Teensy workspace

- [x] Move active development out of OneDrive into Projects/ChopSawHMI-Teensy.
- [x] Preserve the MEGA-compatible HMI in sibling ChopSawHMI, commit 97255b8,
      tag legacy-mega-last-working-2026-11-06. MEGA is retired from live selection.
- [x] Recover the actual MEGA V2.5 firmware and preserve it byte-for-byte under
      archive/legacy-mega-v2.5, with original path and SHA-256.
- [x] Recover 127.12 pulses/inch at full stepping; corroborate in V2.6 migration
      notes. Keep calibration provenance separate from the HMI's old 127.0 default.
- [x] Retain the offline simulator, cut-list editing/import and legacy command
      translation for simulation only. Existing simulated cutting cycle passes.
- [x] Preserve the integrated app/firmware software milestone in a local Git checkpoint.
- [ ] Back up that checkpoint to GitHub and create a reviewed release when ready.
      A local checkpoint is not a published release or remote backup.

## Stage 2 - Capability boundaries and controller-owned interlocks

- [x] Add backend capabilities; unsupported live operations cannot silently fall
      back to MEGA commands. Diagnostics and grblHAL prototype stay operationally locked.
- [x] Add the Teensy Carriage backend and native main-app tab on one COM connection.
- [x] Require exact firmware protocol, board, input/output/motion maps and calibration
      before main-app motion. Connect is reads only; no configure/enable/arm on connect.
- [x] Guard every main-app serial write in Carriage mode; reject legacy motion,
      PID, clamp/saw, G-code, raw output and voltage-test commands.
- [x] Require explicit isolation/driver confirmation, inactive Home input,
      setup acknowledgment and arm acknowledgment before a jog can be requested.
- [x] Controller-side door, saw-UP/conflicting endpoints, Home and driver alarm checks;
      first fault latched, cancellation of pending pulses, no automatic resume.
- [x] Firmware 1.5s heartbeat timeout, app stale-telemetry/reboot/identity-change handling,
      stop before disconnect/close, explicit fault ACK separate from arm.
- [x] Count/queue/budget/timing/cancellation/rollover tests against real C++ sketch
      code with mock hardware; Qt tests cover app write boundaries and stale ACKs.
- [ ] Physically accept controlled stop, door, alarm, limit, USB-loss and PC-loss
      responses on the complete carriage setup. Firmware/UI tests are not that acceptance.
- [ ] Confirm independent guarding, E-stop/hazardous-energy isolation and mechanical
      outcomes on electrical/air loss. These are not provided by the PC software.

## Stage 3 - Verified hardware and wiring recovery

- [x] Identify Teensy 4.1 + T41U5XBB V2.20; replace damaged Teensy.
- [x] External regulated 5V and USB power blocker validated by user; logic rail readings good.
- [x] Door D29, saw UP Limit Z/D22, saw DOWN Fd/Hld/D16 work. Retire Cyc/St/D17 path.
- [x] Board-edge Banner sensor on Limit Y/D21 and Home input on Limit X/D20 tested.
- [x] AUX2 TTL/D33 saw travel, AUX1 TTL/D32 main clamp, Flood TTL/D19 blade trigger
      MOSFET indicator tests pass. AUX0/D31 is retired pending fault investigation.
- [x] X STEP/D2 and DIR/D3 validated. X En path stays 4.85V unloaded at both states;
      leave it unused. Remap X enable to Axis Y En/D40; voltage switching verified.
- [x] Driver 5V selector, SW1-SW4 all ON, SW6/SW7 OFF confirmed; enabled LOW,
      healthy ALM HIGH on Halt/D14. ALM common ground verified.
- [x] Seven-flash following fault traced to a loose encoder connection; secured wire
      and user confirmed motion. A toward saw; B toward Home.
- [x] INA228 and suspect MCP23017 quarantined/disconnected. Current sensing deferred.
- [ ] Install/verify coil suppression diodes, polarity, branch fuses, wiring and labels.
- [ ] Review full power/wiring/BOM documents against the recovered physical build;
      some historical inventory notes still describe the old I2C/power arrangement.
- [ ] Diagnose/replace suspect buffer/input paths separately; ST0/ST1 remain deferred.

## Stage 4 - Main-app carriage integration (current slice)

- [x] Preserve Sensor Bench 0.6.0 as a separate tool/firmware entry point.
- [x] Create custom controller 0.7.0 with CARRIAGE_V1 / BOUNDED_JOG_V2 contract.
- [x] Native CARRIAGE screen: live Home, board edge, door, saw endpoints, driver
      alarm, configuration, arm, stop/disarm, fault ACK and explicit motor release.
- [x] Main-app inch jogs rounded at 127.12 pulses/inch, 0.01-2 in per click,
      254 pulses per click, fixed 40 pulses/s. No queued jogs or autorepeat.
- [x] Replace the old 254-pulse per-arm diagnostic allowance with repeatable
      manual jogs in 0.9.0. Each move is bounded; completion stays armed.
      Stop, faults and watchdog still cancel/disarm. New manual identity rejects
      old budget-based firmware; UI waits for enable-settling feedback.
- [x] Remove restart Home-trip ritual from manual mode as requested; actual
      Home input must still be clear and remains a stop input. Absolute position
      stays unknown until real homing is implemented and accepted.
- [x] Signed commanded displacement and move acknowledgment IDs from the controller.
      Absolute position remains unknown; no encoder/absolute claim is fabricated.
- [x] Backend, main-app integration, safety-boundary, Sensor Bench, native firmware,
      and existing simulator/manual-cycle regression tests pass. Teensy build passes.
- [x] Flash and identify controller 0.7.0 on COM4, correct D40 map and calibration;
      disarmed, zero budget/remaining, STEP/DIR LOW, ENA HIGH. No motion sent by agent.
- [x] Flash/read back 0.9.0 on COM4: CARRIAGE_V3 / MANUAL_JOG_V1, MAX_JOG=254,
      RATE_PPS=40; disarmed/unconfigured, no queued pulses, ENA HIGH.
- [x] User reports manual motion testing passed and all looks good on 0.9.0.
      This does not independently confirm the complete physical fault matrix.
- [x] Implement bounded homing in 0.10.0: B seek, release/backoff, slow latch,
      pull-off, sensor-stuck/travel/time bounds and cancellation; 209 homing
      policy/real-sketch checks and main-app tests pass. Flash/readback verified.
- [ ] Operator physical Home acceptance and repeatability (default 2-inch search).
- [x] Establish homed coordinates after slow latch/pull-off; invalidate on
      interrupted home, faults, reboot and motor release. Unknown before Home.
- [ ] Verify recovered 160.5-inch physical reference; add soft limits and
      absolute cut-length/load-position commands after homing acceptance.
- [ ] Add controlled acceleration and migrate NORMAL/GENTLE/FAST profiles with limits.
      Legacy profile values must not silently override the commissioning speed.

## Stage 5 - Blade-disconnected dry runs and operating workflow

- [ ] With suppression fitted, validate each valve coil independently with air isolated.
- [ ] With saw mains physically unplugged, validate saw cylinder OFF=UP and ON=DOWN,
      endpoint timeouts and flow-controlled travel. Keep within valve pressure ratings.
- [ ] Validate main clamp actuation and define verified clamp status/retention behavior;
      decide safe fault and air-loss behavior before automatic combined cycles.
- [ ] Validate small trigger cylinder fully releases original switch on OFF; preserve
      factory brake function. No blade-powered acceptance is implied by dry runs.
- [ ] Add main-app pneumatic mode and controller output/completion acknowledgments
      after individual hardware acceptance. Do not reuse colliding MEGA C commands.
- [ ] Migrate board-edge detection, offset/truing and safe return/load positions.
- [ ] Migrate cut-list sequencing to explicit motion and mechanism completion events;
      door/UP/clamp permissions and timeouts at each transition. No blind timed advance.
- [ ] Validate carriage/stock/blade/clamp collision envelope; reconsider early return.
- [ ] Dry run one complete cycle, then multiple boards, with blade power disconnected.

## Stage 6 - Production acceptance, release and future expansion

- [ ] Complete physical fault matrix: guard opening, conflicting/stuck/missing sensors,
      motor alarm, communication loss, controller reboot, electrical and air loss.
- [ ] Establish guarded blade-power enable/disable and verified brake/stop timing;
      review independent safety controls before blade-powered commissioning.
- [ ] Validate homing repeatability, referenced positioning, cuts, kerf/offsets,
      full travel, speed profiles and repeated cycles using recorded acceptance criteria.
- [ ] Finalize wire-by-wire map, BOM, fuses, suppression, power architecture,
      recovery/maintenance instructions and app/firmware compatibility manifest.
- [ ] Create reviewed release, executable, firmware artifact and rollback package;
      verify the main app's updater cannot install an incompatible old controller build.
- [ ] Back up source/configuration/docs and release artifacts to GitHub.
- [ ] Revisit INA228 safely on an isolated test setup; passive telemetry first,
      then accuracy validation, then optional protective behavior. MCP expansion later.
- [ ] Reserve/document future sensor, clamp, actuator and pneumatic expansion without
      changing validated assignments or weakening existing interlocks.

Remaining effort: [12-24 active engineering hours for the core workflow](docs/MIGRATION_EFFORT_ESTIMATE.md), plus physical acceptance and hardware time.
