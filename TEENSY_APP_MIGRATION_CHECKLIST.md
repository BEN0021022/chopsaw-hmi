# Teensy app and firmware migration checklist

Updated 2026-11-09. Active project: `C:/Users/bensc/Projects/ChopSawHMI-Teensy`.
Active firmware: custom **0.15.0** in `firmware/chopsaw_controller`, flashed
and read back on COM4 on 2026-11-08 after operator confirmed app closed/driver OFF.
Homing and motion profiles are operator-confirmed working. Restored AUTO controls
and board-edge geometry still need their specific physical tests.
Rollback sources: `e51f14f` (pre-AUTO, firmware 0.14.0) and `cab3a16` (0.11.0).
See [speed tuning](docs/SPEED_TUNING.md) and [edge plan](docs/BOARD_EDGE_COMMISSIONING.md).
Main app mode: **Teensy Carriage**. The breakout is a grblHAL-compatible board;
the currently flashed firmware is custom, not stock grblHAL.

`[x]` means implemented or observed as explicitly described. Software tests do
not establish physical machine safety or production-cutting readiness.
See [feature mapping](docs/APP_FEATURE_MIGRATION.md) for each old app feature.
Return sequence: [next bench session](docs/NEXT_BENCH_SESSION.md).
Record outstanding physical responses in the [fault acceptance matrix](docs/TEENSY_FAULT_ACCEPTANCE_MATRIX.md).
Current build **0.15.0** has editable pulse rate/acceleration and recovered
MEGA defaults; see [speed tuning](docs/SPEED_TUNING.md). Actual board rate-edit
readback passed without enabling or moving; matching app reopened disarmed.

## End-of-day checkpoint - 2026-11-08

- [x] Carriage motion and bounded homing: operator-confirmed working.
- [x] Editable pulse rate/acceleration and shared profile readback: implemented,
      tested and flashed. Operator reports smooth motion at 3000 pps / 1500 pps?.
- [x] Record seven-flash following fault around 4000 pps; operator elected to
      stay below 4000. ENA release did not clear it; reset investigation deferred.
      No automatic reset or retry added.
- [x] Operator accepts inherited software limits for current testing, based on
      the prior MEGA setup. App/controller target and per-pulse guards remain.
- [x] MANUAL Home/setup/arm/stop and SETTINGS profile editing use shared native
      state and acknowledgments. Retired MEGA controls remain unavailable.
- [x] AUTO restored: bounded jogs, FAST load presets, cut-list Add/import/edit/
      update/clear and fresh sensor pills. Cut Complete removed.
- [x] Cycle Start, Resume and live automatic cutting remain blocked as requested.
      Clamp feedback stays UNKNOWN; disconnected current display is hidden.
- [x] Deploy/read back 0.15.0 / CARRIAGE_V9 / LOAD:FAST_V1, restore saved profiles
      without enabling, reopen AUTO with fresh compatible telemetry and no queued motion.
- [x] Firmware/native, main-app/boundary and simulator regressions pass; layouts
      inspected at 1280x900. Local Git checkpoints and rollback artifacts saved.
- [x] In-app MIGRATION tab displays this checklist; Refresh reloads it.

## UI housekeeping - 2026-11-09 (offline)

- [x] Simplify MANUAL Controls to Home and Motor Power Enabled. Remove PID,
      Near Calibration, duplicate target/jog/calibration fields and Manual motor
      parameters, including their unused handlers and saved-field bindings.
      Native preparation, stop and fault controls remain available.
- [x] Retain the existing Manual keypad and guarded target-entry route at the
      operator's request. Shared speed profiles remain in SETTINGS.
- [x] Motor Power checkbox uses native guarded arm/release and enable-output
      readback; releasing clears Home as before. Simulator now honors enable/
      release, cancels the target and requires a new motion request on re-enable.
- [x] Offline native integration/boundary and complete simulator cycle tests
      pass. Manual layouts inspected with simulated data. No controller accessed
      or firmware flashed; driver-managed closed loop is unchanged.
- [x] AUTO Cut Length has an optional left-side keypad overlay. Tapping the
      field selects its existing value; digits/decimal/Back/Clear edit that same
      field. Add Cut to List remains accessible and keeps the keypad open for
      repeated entries. Close keypad hides it; the checkbox preference persists.
      Physical typing remains available with the keypad on or off. Invalid/empty
      entries cannot add a stale value. Tab changes hide the overlay.
- [x] Successful Add Cut to List returns focus to Cut Length and selects its
      value so the next keypad/keyboard entry replaces it without another tap.
- [x] Exercise repeated touch/keyboard entries, validation, close/toggle, resize,
      preference restore and zero serial writes using fake serial while armed.
      Inspect native and simulator layouts; full simulator cycle regressions pass.
- [x] Move Blade Kerf and Board Sensor Distance to SETTINGS / Cutting and Sensors,
      retaining defaults, saved preference keys and simulation bindings. AUTO
      now has a focused Cut Entry card with a full-width 64px minimum-height
      length field, larger text and Add button. Keypad workflow remains intact;
      layouts fit at 1280x900 in native mode.
- [x] AUTO Live Status has a steady green/red/gray health border and readable
      reason. Native health checks compatible identity, fresh controller/safety/
      sensor records, configured digital inputs and current carriage interlocks.
      Deferred clamp/current/MCP feedback does not prevent green; valid OFF
      readings are not faults. Health remains separate from Home/arm readiness.
- [x] Small telemetry dot breathes on a five-second cycle (1.5s fade up, 2s lit,
      1.5s fade down) gated by fresh validated controller/simulator records.
      Stale data stops animation; required-record loss turns the border red even
      if X data continues. Healthy text is System healthy in both modes; SIM MODE
      and the tooltip retain the simulator scope.
- [x] Read-only health policy/Qt tests cover faults, missing/stale data, reconnect
      startup, future required sensors and heartbeat expiry. Existing main-app,
      keypad/boundary and simulator regressions pass; native layout fits 1280x900.
- [x] Central SETTINGS / Cylinder Timing frame with independent main clamp,
      saw-travel and trigger timings, board settle, and planned outfeed/fence
      entries. Settings scrolls for expansion; Full Auto timing controls and
      ambiguous old widget/handler names are removed. Saved values migrate by
      their original meanings. See [cylinder timing](docs/CYLINDER_TIMING.md).
- [x] Simulator snapshots timings per cut, waits for each clamp's engage and
      release phases, applies saw/trigger waits, and cancels pending actions on
      Stop/disconnect. Tests cover independent timings, migration, persistence,
      cancellation, phase bypass prevention and native automatic-cut lockout.
- [ ] Native automatic pneumatic sequence, timing transfer, feedback watchdogs,
      measured clamp eligibility and fault retention/release remain uncommissioned.
      Planned confirmation/travel limits are saved only; they do not change
      Sensor Bench/manual firmware guards. No firmware change or flash in this pass.
- [x] MANUAL / Manual Machine Controls UI: main clamp/release, saw lower/return,
      trigger press/release, combined manual saw cycle and Stop. Simulator uses
      shared timing snapshots, keeps the clamp after a normal cut, requires
      clamp settling before saw activation, and excludes carriage motion while
      clamped/saw-active. Manual cuts never advance the Auto cut list.
- [x] Test independent manual functions, combined cut, retained clamp, timing,
      Stop/disconnect/stale-data cancellation, native source-level lockout and
      regression of the existing simulated Auto cycle. Left Manual column scrolls.
- [ ] Enable these controls on real Teensy hardware only after a controller-owned
      combined pneumatic protocol, interlocks/feedback and fault/clamp-retention
      policy are implemented and physically accepted. Current manual-test firmware
      permits one pneumatic output at a time and cannot hold a clamp while cycling
      saw/trigger. Main-app native actuator controls remain disabled.

## Next session - remaining work

- [ ] Rehome after the latest flash, then physically test restored AUTO jogs,
      FAST load presets, STOP and live sensor pills. See [Auto plan](docs/AUTO_TAB_COMMISSIONING.md).
- [ ] Accept board-edge detection, captured offset/truing geometry and stock handling.
- [ ] Acquire/install/verify 1N4007 coil suppression, polarity and branch fuses;
      accept individual pneumatic outputs with saw mains unplugged.
- [ ] Define clamp retention/fault behavior, then integrate pneumatic/saw sequencing
      and automatic cut-list completion/recovery. Cycle Start stays unavailable meanwhile.
- [ ] Finish remaining physical fault tests, release documentation and GitHub backup.

Absolute/load moves use the referenced range, not the two-inch jog allowance.
Commissioning starts at 40 pulses/s; editable profiles determine jog/ordinary
absolute speeds, and Load selects stored FAST. Checklist refresh never moves hardware.

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
- [x] Map the same controller-owned state/guards into MANUAL: Home/search limit,
      setup/consent, arm/stop/release/ACK, referenced targets and bounded +/-2in jogs.
- [x] Map SETTINGS profile fields and selected-profile Apply into native XPROFILE
      requests. Wait for parameter ACK; synchronize readbacks between tabs,
      preserve unapplied drafts and keep simulator settings separate.
- [x] Main-app inch jogs rounded at 127.12 pulses/inch, 0.01-2 in per click,
      254 pulses per click. Initial commissioning speed was 40 pulses/s; current
      jogs use the selected editable profile. No queued jogs or autorepeat.
- [x] Replace the old 254-pulse per-arm diagnostic allowance with repeatable
      manual jogs in 0.9.0. Each move is bounded; completion stays armed.
      Stop, faults and watchdog still cancel/disarm. New manual identity rejects
      old budget-based firmware; UI waits for enable-settling feedback.
- [x] Remove restart Home-trip ritual from manual mode as requested; actual
      Home input must still be clear and remains a stop input. Absolute position
      requires a completed Home cycle; a clear input alone establishes nothing.
- [x] Signed commanded displacement and move acknowledgment IDs from the controller.
      Referenced position requires successful Home; no streamed encoder position
      or fabricated reference is claimed.
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
- [x] User reported the automatic Home cycle succeeded on 0.10.0.
- [ ] Record Home repeatability and physical blade-reference acceptance.
- [x] Establish homed coordinates after slow latch/pull-off; invalidate on
      interrupted home, faults, reboot and motor release. Unknown before Home.
- [x] Add referenced absolute inch targets and load presets (Home/load,
      135/111/87/63 in). Require successful Home and explicit motion arm.
- [x] Enforce firmware soft limits at request time and per pulse for referenced
      moves and jogs; upper limit is actual Home pull-off position. Reject
      invalid targets, stop/cancel safely, never queue a replacement move.
- [x] Flash/read back 0.11.0 (CARRIAGE_V5 / REFERENCED_V1) on COM4; unknown
      reference and zero queued motion after restart. No motion commanded by agent.
- [ ] Physically accept short absolute out-and-back, load moves, lower travel
      limit and recovered 160.5-inch physical blade reference before production use.
- [x] Prepare 0.12.0 controlled acceleration and bounded profiles; RAM-only,
      disarmed-only selection and acknowledged app feedback. Legacy editable
      speed fields cannot override them. Native ramp and main-app tests pass.
- [x] Flash/read back 0.13.0 and reopen compatible main app on CARRIAGE with fresh
      telemetry, no local fault and no arm/motion commanded by agent.
- [x] Operator confirmed Home/profiles working, with smooth motion at
      3000 pps / 1500 pps?. A following fault occurred around 4000 pps.
- [x] Deploy partial AUTO in 0.15.0: native jog/load, planning and sensor feedback.
- [ ] Physically test the restored AUTO jog/load paths after the latest flash.
- [x] Prepare 0.13.0 bounded edge acquisition, capture expiry/token checks and
      guarded separate truing move; native, Qt and actual-protocol replay tests pass.
- [ ] Physically accept board-edge geometry, truing proposal and stock handling.

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
- [x] Implement bounded board-edge detection, captured offset/truing proposal
      and existing load positions in prepared source.
- [ ] Accept those positions physically and complete safe stock return/loading policy.
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

The [original effort estimate](docs/MIGRATION_EFFORT_ESTIMATE.md) predates the
latest completed migrations. Unchecked items above are the current remaining work.
