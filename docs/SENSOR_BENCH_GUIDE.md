# Sensor Bench Guide

The Sensor Bench is a separate commissioning tool for bringing Teensy-connected
sensors online and proving three guarded pneumatic MOSFET trigger channels. It
exposes no carriage motion, general relay, motor-enable, g-code, or automatic
cycle commands.

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
- Pneumatic output indicators reflect firmware-confirmed state, not an
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
Only D31-D33 are outputs, and they are reserved for guarded pneumatic trigger
tests. Enable, carriage motion, automatic saw cycles, g-code, and grbl commands
are rejected.

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

## Pneumatic MOSFET trigger wiring

Use the separate JP10 header marked `5V TTL/SSR Relay`, not the AUX screw
terminals. Each header row has a `Sig` hole and a `Gnd` hole.

| Commissioning load | Firmware output | Trigger connection | Return connection | Required OFF state |
|---|---|---|---|
| Saw cylinder valve | D31 / `OUT 0` | JP10 AUX0 `Sig` | JP10 AUX0 `Gnd` | Saw fully up |
| Main clamp valve, left of blade | D32 / `OUT 1` | JP10 AUX1 `Sig` | JP10 AUX1 `Gnd` | Clamp released/retracted |
| Spare pneumatic channel | D33 / `OUT 2` | JP10 AUX2 `Sig` | JP10 AUX2 `Gnd` | Disconnected until assigned |

On the dual-MOSFET module, connect JP10 `Sig` to J1 `TRIG/PWM` and JP10 `Gnd`
to J1 `GND`. J1 has two duplicate holes in each row: the upper pair is
`TRIG/PWM` and the lower pair is `GND`. Use one upper hole and one lower hole;
the two holes in the same vertical column make the cleanest two-wire harness.
The photographed Q1/Q2 devices are marked `D4184`, consistent with AOD4184A.

## First output test

1. Isolate the air supply and disconnect all solenoid loads.
2. Power only the reviewed logic and MOSFET-module supply arrangement.
3. Confirm all module outputs are OFF before opening the HMI.
4. Connect the HMI and confirm firmware `0.3.0` / Protocol 2 is reported.
5. Check the commissioning confirmation and click **ARM OUTPUT TEST**.
6. Hold one output button while measuring only that module's indicator/output.
7. Release it and confirm immediate OFF. Repeat one channel at a time.
8. Click **ALL OFF**, disconnect USB, and confirm every output remains OFF.

The HMI sends a keepalive every 500 ms while armed. Firmware disarms after
1.5 seconds without it and also shuts down any output held on for more than
5 seconds. These commissioning protections do not replace a hardwired E-stop,
pneumatic dump valve, coil fuse, or correctly oriented flyback diode. Before
connecting a solenoid, record its coil voltage and current and verify the
required suppression at the coil/module output. The current AirTAC 4V210-08
valve is labeled 12 VDC, 3.0 W (approximately 0.25 A). Port A is connected to
the front fitting on the small cylinder; preserve this note until the cylinder
and safe OFF direction are unambiguously identified in the final pneumatic map.

## First low-pressure cylinder test

1. Verify a branch fuse is installed and the valve supply measures 12 VDC.
2. Secure the cylinder and attached mechanism; clear the entire travel and all
   pinch zones.
3. Put the manual pneumatic dump within reach and regulate pressure low.
4. Before arming, confirm `OUT 0 = 0` leaves the saw up and `OUT 1 = 0` leaves
   the main clamp released. Correct plumbing only while fully depressurized.
5. Test one output at a time with the momentary button. Do not run an automatic
   saw/clamp sequence from this application.
