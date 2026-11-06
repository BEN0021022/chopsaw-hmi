# Chop Saw HMI

PyQt6 operator interface for the chop-saw carriage, cut-list workflow, machine
I/O, simulation, current monitoring, and packaged Windows releases.

## Safety status

The Arduino Mega hardware path was retired on 2026-11-06. Its last verified
source is preserved in the sibling `ChopSawHMI` repository at tag
`legacy-mega-last-working-2026-11-06`; it is not selectable as a live controller
in this Teensy build. Teensy Hardware Test is diagnostics-only. Teensy grblHAL contains prototype
motion commands but remains locked from operational UI controls until response
parsing, alarms, limits, position feedback, and hardware validation are complete.

This application is not a replacement for hardwired emergency-stop, contactor,
driver-enable, pressure-dump, guarding, or mutually exclusive actuator circuitry.
Safety-critical outputs must fail safe independently of the PC and serial link.

See `TEENSY_APP_MIGRATION_CHECKLIST.md` for the active six-stage roadmap.

Stage 3 hardware planning is tracked in:

- `docs/HARDWARE_INVENTORY.md`
- `docs/HARDWARE_BOM.md`
- `docs/POWER_ARCHITECTURE.md`
- `docs/TEENSY_PIN_MAP.md`

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

## Read-only sensor bench

Bring up Teensy inputs and I2C devices without exposing machine outputs:

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
python test_safety_boundaries.py
python test_sensor_bench.py
python test_updater.py
python test_manual_mode.py
python test_sim_cycle.py
```

## Build a Windows executable

Build without publishing:

```powershell
python build.py --no-bump --no-publish
```

Publishing requires an authenticated GitHub CLI. Review the version, release
notes, Git status, and hardware compatibility before creating a release.

## Controller modes

- **Legacy Arduino Mega:** archived only; retained internally for the offline simulator.
- **Teensy Hardware Test:** output and diagnostics protocol for bench bring-up;
  operational tabs remain disabled.
- **Teensy grblHAL:** prototype `$H` and absolute X-motion commands only;
  operational tabs remain disabled until the protocol is completed and tested.
