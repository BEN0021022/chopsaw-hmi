# Chop Saw HMI

PyQt6 operator interface for the chop-saw carriage, cut-list workflow, machine
I/O, simulation, current monitoring, and packaged Windows releases.

## Current Teensy build (2026-11-10)

Prepared app-side update (2026-11-11): small geometry/material policies and one
automation coordinator, measured-geometry settings, operator-required pause/review
UI and bounded detector-zone cleanup. Not deployed; firmware remains 0.19. New
automatic cycles require geometry commissioning. No generic no-clamp override:
0.19 cannot execute an inhibited-main-clamp cycle. See
[automation supervision](docs/AUTOMATION_SUPERVISION.md) for scope and next steps.

Full Auto now opens an offline-capable **Machine layout & commissioning**
workbench: measured/live layout, isolated coordinator scenarios, next-cut-list
lookahead, passive cycle diagnostics and an exportable session checklist. The
older virtual-fixture animation is retained on its own page; native actuation
is not enabled there. See [garage preparation](docs/GARAGE_COMMISSIONING.md).
This is an app-only update; deployed firmware remains 0.19.0.

Current **0.19.0 / CARRIAGE_V13 / UNLOADED_V4** removes Manual's Controls
frame, leaving Home. One Home gesture confirms the established driver setup and
searches the full supported range (20594 pulses, approximately 162 inches), with
finite failed-sensor/watchdog/guard stops retained. Individual pneumatic controls
remain. Manual Cycle and native Start Auto now use controller-owned clamp →
trigger → DOWN/UP → trigger release → brake wait → clamp release sequencing.
**Saw mains must stay physically unplugged.** Guard is currently a Teensy input,
not an independent shutdown path; this is integrated commissioning, not powered
production authorization. Stop/fault retains clamp and releases trigger; recover
clamp explicitly only after UP/brake interval. See [integrated procedure](docs/INTEGRATED_DRY_RUN.md).
0.18.0 was flashed/read back and individual mechanisms were operator-confirmed
working. 0.19 flashed/read back on COM4 on 2026-11-10 with isolation confirmed:
no faults, outputs OFF, disarmed/unconfigured, Home unknown, zero queued motion.
Matching Manual app reopened connected, without setup/arming. Physical combined
acceptance remains pending.

Prior build **0.18.0 / CARRIAGE_V12 / UNLOADED_V3** simplified Manual
to one session-enable button (loads/acknowledges settings automatically), then
direct controls and repeated hold-to-test trigger on Flood/D19. Two-second pulse
and per-action rearm are removed; guard/UP/alarm/watchdog/fault checks remain.
Flashed/read back on COM4. No simultaneous held-trigger/travel or carriage motion.
Saw mains MUST remain physically unplugged. Auto dry lists never press the
trigger. See [trigger procedure](docs/TRIGGER_TEST.md). Physical acceptance pending;
prior 0.16.0 hard-trigger-locked source/HEX are preserved for rollback.
Prior 0.17.0 flashed/read back on COM4 on 2026-11-10 with isolation confirmed; outputs
OFF, no faults, disarmed, no queued motion. Matching Manual app reopened.

The main app now has a **Teensy Carriage** controller mode and native CARRIAGE
tab. Select COM4 (or the actual Teensy port) and connect. Connection sends only
identity/status requests; it never configures, arms or moves the driver.

Previous app/firmware was **0.16.0 / CARRIAGE_V10**, compiled/tested offline, then
flashed/read back on COM4 on 2026-11-09 with operator isolation confirmed.
Startup disarmed, outputs OFF, position unknown, no queued motion. Physical
unloaded acceptance remains pending; **0.15.0** rollback is preserved.
The new build adds Manual unloaded clamp/saw controls and a separate AUTO
**Run unloaded cut-list test**: real detector acquisition, truing, feed/stroke
per item and FAST return. Manually trip/hold the real board detector until truing
starts. Blade trigger D19 is hard locked OFF. Saw mains stay physically unplugged;
no stock. Normal stroke retains clamp; unloaded Stop/fault releases it and
requests UP. Physical acceptance is pending. Follow [the dry-run procedure](docs/TONIGHT_DRY_RUN.md).
AUTO now exposes cut-list planning, live sensor status, bounded jogs and
FAST-profile load moves. Cycle Start/Resume stay disabled; Cut Complete is removed.
See [Auto tab commissioning](docs/AUTO_TAB_COMMISSIONING.md).
This adds bounded motion profiles and board-edge acquisition with a separate
truing move; new physical acceptance remains pending. See
[motion profiles](docs/MOTION_PROFILES.md) and [board-edge plan](docs/BOARD_EDGE_COMMISSIONING.md).
Matching stable 0.11.0 source remains at checkpoint `cab3a16` for rollback.
0.14.0 adds editable pulse rates/acceleration and MEGA V2.5 defaults;
see [speed tuning](docs/SPEED_TUNING.md). 0.13.0 is preserved at `8602038`.
Controller source:
`firmware/chopsaw_controller/chopsaw_controller.ino`. The separate Sensor Bench
0.6.0 sketch is preserved for diagnostics. The active controller keeps those
input/interlock functions and adds the main-app manual-carriage contract. This is
custom firmware; stock grblHAL is not running on the board.

- Verified hardware map: X STEP D2, X DIR D3, X enable remapped to **Axis Y En/D40**.
- Recovered scale: **127.12 pulses/inch**, full stepping. A=toward saw;
  B=away from saw toward Home. Enabled LOW; healthy driver alarm HIGH.
- Main-app jogs: 0.01-2 inches per click, rounded to whole pulses; 254 pulses
  maximum per click, 40 pulses/s. Repeated jogs stay armed; no session travel
  allowance. Start small. One jog at a time; no queued motion.
- Live Home/board-edge/door/saw-up/saw-down/driver-alarm feedback, commanded
  displacement and homed position after successful Home. Commanded travel is
  not an encoder reading; unhomed machine position stays unknown.
- No Home-sensor trip/release ritual is needed after restart; the actual Home
  limit must be clear for manual jogs. Homing can release an active sensor;
  referenced position is unknown until a Home cycle completes.
- Fault acknowledgment never arms. Stop/disarm, disconnect, stale telemetry,
  controller reboot and interlocks revoke permission. Motor release explicitly
  disables the driver and requires setup confirmation again, without walking
  down to trip the Home sensor.
- Bounded homing is implemented in the CARRIAGE tab: default 2-inch search,
  release/backoff/slow latch/pull-off, recovered 160.5-inch sensor reference.
  User confirmed Home success. Referenced absolute inch targets and load
  presets are now implemented, with firmware soft limits; their physical
  acceptance is pending. Profiles are editable in SETTINGS. Production automatic
  cutting remains blocked; native Manual/AUTO unloaded controls require matching
  identity, acknowledged timings and fresh feedback. Offline simulator retained.
- The MIGRATION tab shows the master checklist; Refresh reloads current status.
- Blade/current controls remain unavailable; INA/MCP disconnected. Isolate valve
  power/air for initial carriage-only checks, then follow unloaded acceptance
  before powering pneumatics. Deployment verification used reads only; no
  setup, arming, valve or motion commands were sent by the agent.

The last MEGA HMI remains in sibling `ChopSawHMI` at
`legacy-mega-last-working-2026-11-06`; recovered MEGA firmware is also preserved
under `archive/legacy-mega-v2.5`. Live MEGA selection is retired.

See [absolute positioning](docs/ABSOLUTE_POSITIONING.md),
[homing test instructions](docs/HOMING_COMMISSIONING.md),
[remaining effort estimate](docs/MIGRATION_EFFORT_ESTIMATE.md),
[feature migration](docs/APP_FEATURE_MIGRATION.md),
[controller protocol](docs/CONTROLLER_PROTOCOL.md), and
[six-stage roadmap](TEENSY_APP_MIGRATION_CHECKLIST.md).
This software is not an independent emergency-stop, guarding, or hazardous-energy
control system.

## Setup

The current validated development environment is Python 3.13 on Windows.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Run from source

```powershell
python main.py
```

Select `SIMULATOR - virtual machine` to exercise the application without
connecting machine hardware.

## Separate sensor bench

Use the separate commissioning dashboard for input and isolated output tests:

```powershell
python run_sensor_bench.py
```

Use `python run_sensor_bench.py --demo` to preview and test the dark dashboard
without hardware. Wiring, firmware, and validation details are in
`docs/SENSOR_BENCH_GUIDE.md`.

## Regression tests

The UI tests use isolated temporary settings and the offscreen Qt platform.

```powershell
python test_controller_backends.py
python test_teensy_carriage.py
python test_safety_boundaries.py
python test_sensor_bench.py
python test_bench_interlocks.py
python test_updater.py
python test_manual_mode.py
python test_sim_cycle.py
```

The firmware interlock test compiles and runs the actual C++ policy and sketch
command handler with mocked hardware. It needs g++/clang++, or the optional
portable Zig compiler described in `docs/SENSOR_BENCH_GUIDE.md`.

## Build a Windows executable

Build without publishing:

```powershell
python build.py --no-bump --no-publish
```

Publishing requires an authenticated GitHub CLI. Review the version, release
notes, Git status, and hardware compatibility before creating a release.

## Controller modes

- **Teensy Carriage:** active custom 0.15.0 firmware; guarded carriage motion, editable rates and partial AUTO controls.
- **Legacy Arduino Mega:** archived, internal to the offline simulator only.
- **Teensy Hardware Test:** separate diagnostics protocol; old operational tabs locked.
- **Teensy grblHAL:** retained prototype only; operational controls locked. It
  cannot be selected to operate the currently flashed custom controller.
