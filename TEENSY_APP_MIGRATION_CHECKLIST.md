# Teensy app and firmware migration checklist

Updated 2026-11-11. Active project: `C:/Users/bensc/Projects/ChopSawHMI-Teensy`.
Current deployed source/build: custom **0.22.0 / CARRIAGE_V16**, flashed/read back
on COM4, 2026-11-11. Integrated saw-unplugged
Manual/Auto cycles and one-click full-range Home. Physical acceptance pending.
0.18.0 was flashed/read back on 2026-11-10; individual mechanisms passed.
Prior 0.16.0 was flashed/read back on COM4 on 2026-11-09 after isolation confirmation;
startup disarmed, unconfigured, outputs OFF, position unknown, no queued motion.
Physical unloaded acceptance pending. Deployed 0.15.0 rollback preserved.
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

## Auto acquisition correction - app patch 0.22.1

- [x] Reproduce physical-board search failure at 254 pulses, EDGE_FAILED/NOT_FOUND.
- [x] Separate Auto travel-derived acquisition bound from two-inch bench setting.
- [x] Reserve sensor/kerf advance, pusher projection and blade keepout/soft limits.
- [x] Show controller cause: not found, timeout, driver, guard or stale feedback.
- [x] Regression: real detection after eight inches and complete bounded no-detect
      stop; different start positions; no subsequent truing/valve command on failure.
- [ ] Reopen corrected app for operator retest (firmware remains 0.22.0).
- [ ] Physical acquisition/truing acceptance with real stock/detector.

See [acquisition fix](docs/ACQUISITION_FIX_0221.md).

## Auto profiles / last-cut operator flow - 0.22

- [x] Stored Gentle profile for acquisition and first truing; Normal for later
      feeds, Fast for Load/early return, Gentle for bounded scrap clearing.
- [x] Keep carriage forward if another cut fits; early return only for last
      usable positioned cut with clear, consistent board detector.
- [x] Amber Auto operator button/dashboard; explicit one-shot unclamped dry-run
      stroke with main clamp inhibited; no sensor-triggered resume or timeout.
- [x] Continue next board with pending list index retained and fresh acquisition.
- [x] Active-cut highlight/scroll follows controller DONE without consuming list.
- [x] Real-sketch/Qt regression, host suites and Teensy 4.1 compile.
- [x] Flash/read back matching 0.22 on COM4, restore captured motion profiles;
      matching app opened on Auto, outputs OFF, no queued action, Home unknown.
- [ ] Operator physical acceptance of profile / early-return / pending-cut flow.

See [0.22 workflow](docs/OPERATOR_RETURN_022.md). This supersedes the older
executor restriction that prevented any operator-controlled unclamped dry stroke.

## Direct operation ? 0.21 (supersedes earlier UI preparation steps)

- [x] One-gesture Home, carriage Enter/jog/load, individual actuators and Start Auto.
- [x] Remove normal Manual/Auto consent, arm, enable and registration clicks.
- [x] Restore physical-keyboard and touch-keypad target entry.
- [x] Reuse valid saved machine dimensions without verification checkboxes.
- [x] Remove Full Auto workbench checklist page and hide migration checklist tab.
- [x] Keep controller acknowledgments, feedback, real interlocks, Stop, soft limits,
      collision/holding policies and held-trigger release.
- [x] Actual-sketch/Qt tests and Teensy 4.1 compile.
- [x] Flash/read back matching 0.21 on COM4 and restore captured motion profiles.
      Startup idle, outputs OFF, Home unknown. Matching app reopened on Manual;
      no Home, arm, motion or valve command sent to physical hardware.
- [ ] Operator physical acceptance of simplified Manual/Auto dry-run workflow.

See [direct controls](docs/DIRECT_CONTROLS_021.md). Older commissioning steps below
are historical; their removed UI confirmations are not required in this build.

## Multi-board / forward-trim correction - 2026-11-11

- [x] Replace whole-queue capacity rejection with one next-cut fit assessment.
- [x] Correct forward truing sign; Auto advances detector offset plus kerf.
- [x] End-of-board cleanup/return, disarmed wait and explicit Start next board,
      retained next-cut index and immutable batch list/kerf snapshot.
- [x] No forced material-origin reset to conceal an incorrect truing advance.
- [x] Actual-sketch regressions: reported five-cut/two-board list, intermediate
      cleanup, no sensor-triggered resume, long waiting interval, oversized first cut.
- [x] Host interlock/edge/protocol suites and Teensy 4.1 compile.
- [x] Flash/read back 0.20 on COM4, 2026-11-11. OFF/disarmed/unconfigured,
      unknown position, no faults/queued motion. Restore/verify captured profiles
      (Gentle 600/600, Normal 2000/1500, Fast 3500/2000) without arming or movement.
- [x] Save operator-supplied 16.75-inch physical rear extent, retain 160-inch
      cleanup allowance; old truing/automatic-cleanup verification cleared.
- [ ] Physically verify 10.8 + 0.12 = 10.92 inch truing advance, then combined dry runs.

See [current correction procedure](docs/MULTIBOARD_TRUING_020.md).

## Unpowered trigger addition - 2026-11-10

Latest integrated 0.19 update supersedes earlier trigger-OFF/release-on-fault
entries below. [Current procedure](docs/INTEGRATED_DRY_RUN.md).

- [x] Operator confirms trigger, saw travel and clamp individual tests passed.
- [x] Remove Manual Controls frame, retain one Home button; acknowledged driver
      setup + full 20594-pulse search. Keep finite failed-sensor and fault stops.
- [x] Controller-owned DCUT: clamp/settle, trigger/spinup, real DOWN/UP, trigger
      release/brake wait, clamp release. Load 15 timing values with hash/ACK.
- [x] Start Auto uses same full cycle between real-detector/truing/feed/FAST moves.
- [x] Stop/fault retains engaged clamp, releases trigger; explicit UP/brake-delayed
      recovery release. Cancel during preparation cannot restart the sequence.
- [x] Actual firmware/Qt/one-click Home/combined Manual and two-cut Auto tests.
- [x] Flash/read back 0.19 on COM4, 2026-11-10, isolation confirmed. Startup
      disarmed, outputs OFF, Home unknown, no faults/queued motion. Matching
      Manual app reopened; agent sent no setup, arm or actuation.
- [ ] Physically accept integrated sequence, new Home/Auto and recovery behavior.
- [ ] Independent safeguarding and powered-cut/grip/brake acceptance remain open.

0.18 simplifies the earlier 0.17 controls below:

- [x] One **Enable unpowered manual controls** gesture loads/ACKs timings and
      enables the session; no repeated checkboxes or per-action trigger arm.
- [x] Hold trigger to press, release/tab/focus loss to stop; no two-second cap
      or ten-second unused permission expiry. Firmware hold lease remains
      350 ms; late hold cannot repress. Repeated deliberate tests need no rearm.
- [x] Preserve Stop, guard/endpoint/alarm/watchdog, clamp/travel fault limits;
      keep Auto trigger blocked in firmware as well as the app.
- [x] Actual-sketch and Qt mouse/hold/release/one-click tests; Teensy compile.
- [ ] Flash/read back 0.18 after renewed physical isolation confirmation.
- [ ] Physical acceptance of simplified controls and mechanical release.

- [x] Add separate Manual consent and explicit one-press trigger arm on Flood/D19.
- [x] Firmware maximum 2 s press, unused-arm expiry 10 s, watchdog/interlock
      release, no auto-rearm; raw OUT 2 ON still rejected.
- [x] Block saw travel, clamp changes and carriage motion during trigger test;
      keep Auto dry-list trigger OFF. Validate acknowledged lock/output state.
- [x] Actual-sketch and Qt tests plus Teensy compile. Preserve 0.16.0 rollback.
- [x] Flash/read back 0.17.0 on COM4 with operator isolation confirmed on
      2026-11-10. Outputs OFF, trigger locked, no queued motion, no faults;
      only identity/status reads sent. Matching Manual app reopened disarmed.
- [ ] Physical unpowered trigger/release/guard/timeout acceptance, including
      mechanical return of printed trigger assembly. See [procedure](docs/TRIGGER_TEST.md).

The earlier 0.16 trigger-lock entries below document that prior checkpoint;
0.17 changes only the separate Manual test, not Auto or powered-cut permissions.
Record outstanding physical responses in the [fault acceptance matrix](docs/TEENSY_FAULT_ACCEPTANCE_MATRIX.md).

## Automation supervision foundation - 2026-11-11 (not deployed)

- [x] Full Auto read-only layout/scenario workbench available disconnected; retain
      legacy virtual-fixture animation with its existing capability gates.
- [x] Spatial main-pad/pusher/keepout/detector visualization, separate live unknown
      states and 11 isolated scenarios evaluated through the actual coordinator.
- [x] Whole-list lookahead from an explicitly already-trued stock state; stop at
      first unsupported cut and predict minimum detector-zone cleanup.
- [x] Passive native phase/decision diagnostics, acknowledged wait vs travel-limit
      labels, interrupted feedback handling and bounded JSON session export.
- [x] Append-only cut-history CSV next to executable; background writes, confirmed
      counter events, frozen cut targets/original stock estimates, explicit unknowns,
      dry-run classification, board IDs and visible write-failure warning.
- [x] Session checklist, measured geometry worksheet and current garage procedure;
      alternative-holding recovery design documents the remaining executor gap.
- [x] Pure scenario/diagnostic tests, no-write Qt workbench tests and actual-sketch
      phase/readback/export assertions; existing app regressions passed.
- [ ] Monitor one intermittent offscreen Qt6Core process termination; four
      diagnostic reruns passed, cause unconfirmed. See garage verification record.
- [ ] Restart source app to inspect the prepared workbench; no firmware update required.
- [ ] Record actual geometry and physical acceptance; checklist marks never grant
      permission or imply that a modeled clamp has confirmed grip.

- [x] Pure main-clamp eligibility, cut holding, sensor clearance and next-action
      functions under one geometry/material coordinator. No hardware writes in policies.
- [x] Explicit measured/unknown material and geometry, projected pusher envelope,
      blade keepout, push-only remnant tracking and stale-plan revisions.
- [x] App source guards, pre-arm Auto pause, amber Manual Cycle review with no
      generic bypass, one-time geometry settings and material registration.
- [x] Commissioned bounded Gentle sensor-clearance move/clear verification before
      FAST return; no blind zero push, extra retries or assumed empty outfeed.
- [x] Pure policies and actual-sketch/Qt coordinator/pause/cleanup integration tests;
      existing firmware/UI/simulator regressions. No board access or flash.
- [ ] Measure/commission actual footprints, pusher envelope, keepout and native
      sensor/truing datum; physically accept coordinator behavior with saw unplugged.
- [ ] Define approved alternative securing method and implement selected-clamp /
      approved-fixture firmware execution before no-main-clamp Manual recovery.
      Operator decision: keep recovery paused until the second clamp is installed
      and mapped; no interim no-clamp bypass.
- [ ] Install/map/commission outfeed device and its holding role (not assumed from cylinder delivery).
- [ ] Independent safeguarding / grip / blade-stop and powered-production acceptance.

See [architecture and limitations](docs/AUTOMATION_SUPERVISION.md).
Use [current garage commissioning](docs/GARAGE_COMMISSIONING.md) for today's
test order; earlier deployment sections below are historical checkpoints.
Deployed baseline **0.15.0** has editable pulse rate/acceleration and recovered
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
- [x] Prepare 0.16.0 unloaded native timing transfer/readback, held-clamp/saw
      sequencing and endpoint watchdogs. Clamp grip/eligibility feedback remains
      deferred. Production cutting remains blocked; physical acceptance pending.
- [x] MANUAL / Manual Machine Controls UI: main clamp/release, saw lower/return,
      trigger press/release, combined manual saw cycle and Stop. Simulator uses
      shared timing snapshots, keeps the clamp after a normal cut, requires
      clamp settling before saw activation, and excludes carriage motion while
      clamped/saw-active. Manual cuts never advance the Auto cut list.
- [x] Test independent manual functions, combined cut, retained clamp, timing,
      Stop/disconnect/stale-data cancellation, native source-level lockout and
      regression of the existing simulated Auto cycle. Left Manual column scrolls.
- [x] Add native Manual clamp/release, lower/return and unloaded saw cycle, gated
      by matching 0.16.0 identity, timing ACK, fresh feedback and explicit consent.
      Blade trigger remains locked OFF. Normal stroke retains clamp; unloaded
      Stop/fault releases it. Separate production retention policy still needed.
- [ ] Flash/read back and physically accept the new unloaded Manual controls.

## Next session - remaining work

Read [tonight's unloaded procedure](docs/TONIGHT_DRY_RUN.md). On 2026-11-09
the operator confirmed main clamp ON holds/OFF releases; testing has no stock,
saw mains unplugged and blade-trigger output disabled. The 0.15.0 baseline
artifact/source hashes were verified. The combined **0.16.0 app/firmware is now
prepared and compiled**, with eight host suites, 55 motion-record replays and
actual-sketch/Qt two-item cut-list integration passing. No hardware accessed.

- [x] Implement controller-owned unloaded sequence and hard-lock Flood/D19 OFF.
- [x] Transfer bounded timing snapshot with configuration token/hash and phase/
      request acknowledgments; reject stale/conflicting readbacks.
- [x] Add separate AUTO unloaded cut-list runner: real manually tripped Limit Y
      detection, captured truing, held clamp/saw DOWN/UP, feed lengths+kerf and
      stored FAST Load return. Production list progress is preserved.
- [x] Check no carriage pulses while clamped, stop/stale/no-retry boundaries,
      real endpoint timeouts and simulator regression; compile Teensy 4.1 HEX.
- [x] Flash/read back 0.16.0 on COM4 with operator isolation confirmed; unloaded
      state OFF, blade lock 1, all outputs OFF, no queued pulses; verification reads only.
- [ ] Perform physical unloaded acceptance tonight.

- [x] Correct health display so ALREADY_ARMED is not mistaken for a feedback fault;
      arming remains separate from healthy telemetry.

- [ ] Rehome after the latest flash, then physically test restored AUTO jogs,
      FAST load presets, STOP and live sensor pills. See [Auto plan](docs/AUTO_TAB_COMMISSIONING.md).
- [ ] Accept board-edge detection, captured offset/truing geometry and stock handling.
- [ ] Acquire/install/verify 1N4007 coil suppression, polarity and branch fuses;
      accept individual pneumatic outputs with saw mains unplugged.
- [x] Define unloaded-only fault behavior: saw OFF/UP, clamp OFF/released, blade
      locked OFF; cancel sequence, no automatic retry or resumption.
- [ ] Define production grip/coverage/retention and cutting recovery. Production
      Cycle Start remains unavailable; use the separate unloaded-test control.
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
- [x] Prepare main-app unloaded pneumatic mode with controller-owned phases,
      output/completion acknowledgments and mutually exclusive carriage control.
- [ ] Accept its individual and combined physical behavior after suppression checks.
- [x] Implement bounded board-edge detection, captured offset/truing proposal
      and existing load positions in prepared source.
- [ ] Accept those positions physically and complete safe stock return/loading policy.
- [x] Prepare unloaded cut-list sequencing with motion/mechanism acknowledgments,
      door/UP checks and timeouts. Clamp state is commanded, not verified grip.
- [ ] Add production stock eligibility/grip policy before live cut-list cutting.
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
