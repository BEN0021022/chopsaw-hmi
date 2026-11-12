# Chop Saw HMI

PyQt6 operator interface for the chop-saw carriage, cut-list workflow, machine
I/O, simulation, current monitoring, and packaged Windows releases.

## Current Teensy build (2026-11-11)

**0.21.0 / CARRIAGE_V15** simplifies operation to **Connect ? Home ? use the
controls**. Manual carriage entry accepts a physical keyboard or touch keypad.
Clamp, saw travel, held trigger and Manual Cycle handle their mode setup
internally. Auto starts from its Start Auto button. Session checklists,
confirmations, stock registration and separate arming are removed from the
normal workflow. Saved valid machine dimensions persist across startup.

Real feedback/interlocks, existing motion limits, Stop and the automatic
material/holding coordinator remain. Saw mains must remain physically
unplugged for this build. See [direct controls and deployment](docs/DIRECT_CONTROLS_021.md).

The 0.20 multi-board and forward-trim corrections are retained: assess one
next cut per board; advance detector distance plus kerf for truing; clear the
acquisition zone when required; return and wait for Start next board while
retaining the next cut. See [truing correction](docs/MULTIBOARD_TRUING_020.md).

Full Auto provides the machine layout, isolated scenarios and passive cycle
diagnostics. Native confirmed cuts append `cut_history.csv` beside the app
for later metrics; unplugged tests are labeled `dry_run`. See
[cut history](docs/CUT_HISTORY.md) and the
[migration checklist](TEENSY_APP_MIGRATION_CHECKLIST.md).

The board uses custom firmware, not stock grblHAL. Connecting sends only
identity/status requests; it never starts motion or energizes a valve.
Prior source/HEX archives remain available for rollback.

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
