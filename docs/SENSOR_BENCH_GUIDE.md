# Sensor Bench Guide

The Sensor Bench is a separate commissioning tool for bringing Teensy-connected
sensors online and proving three clamp MOSFET trigger channels. It exposes no
motion, saw, general relay, enable, or actuator commands.

## Run the application

From the repository root:

```powershell
python run_sensor_bench.py
```

To exercise the complete dashboard without hardware:

```powershell
python run_sensor_bench.py --demo
```

Select the Teensy COM port, click **Connect**, and then **Probe Hardware**. The
app automatically prefers USB VID `0x16C0`, used by the connected Teensy.

## What the dashboard proves

- Teensy health means current, non-stale protocol telemetry is arriving.
- MCP23017 health means address `0x27` acknowledged and its GPIO registers were
  read successfully.
- INA228 health means address `0x40` acknowledged and the expected Texas
  Instruments manufacturer and INA228 device IDs were read successfully.
- Every direct sensor shows both its raw electrical level and its interpreted
  ON/OFF state. Polarity remains adjustable until each installed sensor is
  physically validated.
- MCP23017 PA0-PA7 and PB0-PB7 are configured as input-only channels with 3.3 V
  pull-ups. They are not approved for raw 5 V, 12 V, or 24 V field signals.
- Clamp 1-3 output indicators reflect firmware-confirmed state, not an
  optimistic HMI assumption.

## Firmware

The sketch is `firmware/chopsaw_sensor_bench/chopsaw_sensor_bench.ino`. It uses
the T41U5XBB I2C header through Teensy `Wire2` (D24/SCL and D25/SDA). It has no
external library dependencies.

Compile:

```powershell
arduino-cli compile --fqbn teensy:avr:teensy41 firmware/chopsaw_sensor_bench
```

Upload, replacing `COM3` if Windows assigns a different port:

```powershell
arduino-cli upload -p COM3 --fqbn teensy:avr:teensy41 firmware/chopsaw_sensor_bench
```

The firmware configures the documented sensor pins and MCP channels as inputs.
Only D31-D33 are outputs, and they are reserved for guarded clamp trigger tests.
Enable, motion, actuator, saw, g-code, and grbl commands are rejected.

## Direct sensor map

| Firmware name | Breakout point | Teensy pin |
|---|---|---:|
| `HOME` | Limit X | D20 |
| `BOARD_EDGE` | Limit Y | D21 |
| `FENCE_DOOR` | Door | D29 |
| `CL57T_ALM` | Halt | D14 |
| `SAW_UP` | ST0 | D36 |
| `SAW_DOWN` | ST1 | D30 |
| `FENCE_CLOSED` | ST2 | D34 |
| `OUTFEED` | ST3 | D35 |

## Banner Q4X board-edge test

Use the sensor's NPN output with the protected Limit Y input:

- Brown: fused +12 V sensor supply
- Blue: sensor-supply 0 V and Limit Y `Gnd`
- White: Limit Y `Sig`
- Black PNP output: disconnected and individually insulated
- Gray remote input: disconnected and individually insulated

Do not connect +12 V to any Teensy, MCP23017, I2C, or breakout logic pin.

## Clamp MOSFET trigger wiring

Use the separate JP10 header marked `5V TTL/SSR Relay`, not the AUX screw
terminals. Each header row has a `Sig` hole and a `Gnd` hole.

| Clamp | Firmware output | Trigger connection | Return connection |
|---|---|---|---|
| Clamp 1 | D31 / `OUT 0` | JP10 AUX0 `Sig` | JP10 AUX0 `Gnd` |
| Clamp 2 | D32 / `OUT 1` | JP10 AUX1 `Sig` | JP10 AUX1 `Gnd` |
| Clamp 3 | D33 / `OUT 2` | JP10 AUX2 `Sig` | JP10 AUX2 `Gnd` |

On the dual-MOSFET module, connect JP10 `Sig` to J1 `TRIG/PWM` and JP10 `Gnd`
to J1 `GND`. J1 has two duplicate holes in each row: the upper pair is
`TRIG/PWM` and the lower pair is `GND`. Use one upper hole and one lower hole;
the two holes in the same vertical column make the cleanest two-wire harness.
The photographed Q1/Q2 devices are marked `D4184`, consistent with AOD4184A.

## First output test

1. Isolate the air supply and disconnect all solenoid loads.
2. Power only the reviewed logic and MOSFET-module supply arrangement.
3. Confirm all module outputs are OFF before opening the HMI.
4. Connect the HMI and confirm firmware `0.2.0` / Protocol 2 is reported.
5. Check the isolation confirmation and click **ARM OUTPUT TEST**.
6. Hold one clamp button while measuring only that module's indicator/output.
7. Release it and confirm immediate OFF. Repeat one channel at a time.
8. Click **ALL OFF**, disconnect USB, and confirm every output remains OFF.

The HMI sends a keepalive every 500 ms while armed. Firmware disarms after
1.5 seconds without it and also shuts down any output held on for more than
5 seconds. These commissioning protections do not replace a hardwired E-stop,
pneumatic dump valve, coil fuse, or correctly oriented flyback diode. Before
connecting a solenoid, record its coil voltage and current and install the
required suppression at the coil/module output.
