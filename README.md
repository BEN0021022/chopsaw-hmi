# Chop Saw HMI

PyQt6 operator interface for the chop-saw carriage, cut-list workflow, machine
I/O, simulation, current monitoring, and packaged Windows releases.

## Current Teensy build (2026-11-08)

The main app now has a **Teensy Carriage** controller mode and native CARRIAGE
tab. Select COM4 (or the actual Teensy port) and connect. Connection sends only
identity/status requests; it never configures, arms or moves the driver.

Active flashed firmware and reopened app are **0.13.0**, verified on COM4.
This adds bounded motion profiles and board-edge acquisition with a separate
truing move; new physical acceptance remains pending. See
[motion profiles](docs/MOTION_PROFILES.md) and [board-edge plan](docs/BOARD_EDGE_COMMISSIONING.md).
Matching stable 0.11.0 source remains at checkpoint `cab3a16` for rollback.
Prepared 0.14.0 adds editable pulse rates/acceleration and MEGA V2.5 defaults;
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
  acceptance is pending. Profiles and automatic cutting remain unavailable. The old operational tabs stay blocked
  on real hardware. Cut-list editing and the offline simulator are retained.
- The MIGRATION tab shows the master checklist; Refresh reloads current status.
- Main-app pneumatic/blade/current controls are unavailable. Keep saw unplugged,
  valve 12V disconnected, air isolated, INA/MCP disconnected during carriage tests.

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

- **Teensy Carriage:** active custom 0.11.0 firmware; native guarded carriage jogs.
- **Legacy Arduino Mega:** archived, internal to the offline simulator only.
- **Teensy Hardware Test:** separate diagnostics protocol; old operational tabs locked.
- **Teensy grblHAL:** retained prototype only; operational controls locked. It
  cannot be selected to operate the currently flashed custom controller.
