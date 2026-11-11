# Unloaded cut-list test - updated 2026-11-10

**Current matching build: 0.17.0 / CARRIAGE_V11 / UNLOADED_V2.** It preserves
the Auto trigger-OFF sequence below and adds only a separate explicitly armed
[unpowered Manual trigger test](TRIGGER_TEST.md). The 0.16 deployment record below
is historical; physical unloaded acceptance remains pending.

**Software prepared: firmware 0.16.0 / CARRIAGE_V10 and matching main app.**
Compiled/tested offline, then flashed/read back on COM4 on 2026-11-09 with
operator isolation confirmed. Startup disarmed/unconfigured, all outputs OFF,
position unknown, zero queued pulses, blade lock 1. No arming/motion commanded
by the agent. Physical acceptance pending; 0.15.0 source/HEX rollback preserved.

## Confirmed scope

- No stock and no cutting. Saw mains physically unplugged throughout.
- Blade-trigger Flood/D19 stays OFF throughout this Auto test. Only the separate
  explicitly armed Manual test can actuate it; legacy raw commands stay blocked.
- Main clamp AUX1/D32: ON clamps, OFF releases (operator-confirmed).
- Saw travel AUX2/D33: OFF returns UP (operator-confirmed).
- Operator manually trips the **real Limit Y board detector** during acquisition.
  No fake reference, sensor override or production-completion shortcut is used.
- INA228/MCP remain disconnected. Fit/verify suppression and branch fuses before
  energizing valves. Accept the unloaded mechanisms before running the list.

## Prepared behavior

MANUAL provides acknowledged clamp/release, saw lower/return and one unloaded
saw cycle. Configure timings, explicitly arm unloaded pneumatics, then Clamp.
A stroke requires the clamp command to complete settling. This is **commanded
clamp state**, not measured grip. A normal stroke leaves the clamp ON; Release
waits for confirmed UP and the configured release clearance.

AUTO has a separate **Run unloaded cut-list test** control. Production Start
Cycle/Resume remain unavailable. The unloaded runner snapshots the cut list,
kerf, sensor offset and trim; it does not consume or mark production cuts done.

Sequence:

1. Acquire an edge through the existing bounded real-detector search.
2. Accept the captured truing target, choose stored Normal profile and move.
3. Disarm carriage, settle board, clamp, wait clamp settling, cycle DOWN/UP using
   the real endpoint switches, settle UP, release clamp and wait clearance.
4. Feed each cut length plus kerf using referenced soft limits; repeat the
   unloaded clamp/stroke/release sequence for each item.
5. Return to selected Load using stored FAST; finish disarmed.

There is one truing stroke plus one stroke per cut-list item. No blade trigger,
automatic retry, early carriage return or resumption after a fault.

## At the machine

1. App closed, driver power OFF, valve power disconnected, air isolated and
   saw unplugged: load prepared 0.17.0 and open the matching app. Verify identity,
   pin map, outputs OFF and no queued pulses.
2. Check door, Home, board detector and both saw endpoint pills. Verify valve
   suppression/polarity and fuses. Check unloaded OFF/UP and clamp behavior with
   regulated air and flow controls, one mechanism at a time.
3. Confirm carriage preparation, Setup verified enable/alarm levels, power the
   driver when ready and Home. Check short jog/Stop. Restore/edit stored Normal
   and FAST rates conservatively; reboot resets their RAM values. The operator
   preferred below 4000 pps after a following error there.
4. In SETTINGS / Cylinder Timing, choose main-clamp and saw-travel delays.
   In MANUAL or AUTO confirm unloaded/suppression/air preparation and click
   **Load dry-run timings** while disarmed. Wait for controller readback.
   Delays: 0-5000 ms. DOWN/UP travel limits: 100-5000 ms. Save retains values
   on the PC; Load transfers them. Edits require another explicit Load.
5. First accept MANUAL Clamp, Unloaded Saw Cycle, Return UP, Release and Stop.
   Keep the carriage clear for subsequent automatic motion.
6. Add a short list in AUTO and select Load. Detector starts clear; carriage
   homed/disarmed; saw UP; clamp OFF. Click **Run unloaded cut-list test**.
   This explicitly authorizes its automatic moves and unloaded strokes.
7. At **SEARCH**, trip and hold the real board detector. Keep it active through
   capture until the truing move starts; then release it. Search is bounded by
   the CARRIAGE search-distance setting (initially two inches).
8. Watch truing, each list move/stroke and final Load return. Record directions,
   clearances, endpoints, times and fault/Stop results before increasing scope.

## Unloaded stop and fault behavior

Stop/fault turns saw valve OFF (requests UP), **releases the clamp**, locks blade
trigger OFF and cancels the sequence. Holding torque is retained. Stop waits for
UP or faults after five seconds. Recovery never arms or resumes; recover the
physical condition, acknowledge, re-confirm preparation and Home if reference
was invalidated. This release policy is specific to **no-stock tests**; it does
not authorize real stock or describe a safe power/air-loss result.

Firmware enforces exclusion with carriage pulses, real endpoints, door/alarm
faults, 1500 ms heartbeat, 60 s maximum clamp ON, 15 s maximum saw valve ON and
configured travel deadlines. The app validates identity, fresh readbacks,
timing hash/configuration and request acknowledgments. Missing or contradictory
feedback blocks advancement. Timed clamp settling is not grip feedback.
Independent guarding and hazardous-energy controls remain necessary.

## Offline verification and artifacts

- Eight actual-firmware host suites and motion-record replay into Qt.
- Actual sketch to main-app integration: Home, Manual actions, real-input edge
  capture, truing, two list items, FAST return, blade lock, stop/stale/config/
  readback guards. No carriage pulses while clamped.
- Existing carriage, keypad, health, timing, boundary and simulator regressions.
- Teensy 4.1 compile and isolated upload completed. Read-only verification;
  no setup, arming, valve or motion commands sent by the agent.
- Prepared build: `tmp/commissioning/0.16.0`; rollback: `tmp/commissioning/0.15.0`.
  Manifest records matching source revision and hashes. Local artifacts are
  not a GitHub backup or published release.

Physical results remain unchecked in the [master checklist](../TEENSY_APP_MIGRATION_CHECKLIST.md).
