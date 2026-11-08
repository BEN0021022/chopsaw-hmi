# Sensor Bench Guide

## Recovered calibration update (2026-11-08)

The MEGA V2.5 firmware was recovered: **127.12 pulses/inch at full stepping**.
Use that historical machine value, as requested by the user, instead of the
earlier 127.1 estimate. See [calibration provenance](MOTION_CALIBRATION_PROVENANCE.md).
No new ruler measurement is required for this source-recovery step. Historical
notes below retain the earlier estimate and sequence of commissioning checks.

The Sensor Bench is a separate commissioning tool for bringing Teensy-connected
sensors online and proving three guarded pneumatic MOSFET trigger channels. It
keeps pneumatic tests separate from the bounded X stepper commissioning
window described below. It exposes no general jogging, g-code, or automatic
cycle commands.

## X bounded jog test build: 0.6.0

X enable uses **Axis Y En/D40**; STEP/DIR remain on Axis X. Original X En
is disconnected after it stayed 4.85V unloaded at both commanded levels.
User confirmed replacement output voltage tests pass and LOW enables holding.
Healthy driver alarm raw is HIGH (1).

The X Stepper Test window offers 1 pulse, ~0.1 inch/13 pulses (default),
~0.5 inch/64 pulses, and ~1 inch/127 pulses. Distances use provisional
127.1 pulses/inch; they are estimates. Each arm allows 254 pulses total (~2
inches), at up to 40 pulses/s. Start at the smallest jog to confirm real travel.
Firmware checks inputs/serial throughout; OFF or an interlock cancels remaining
pulses. No queued jogs or autorepeat. ENA is retained on stop. See
[X commissioning](X_STEPPER_COMMISSIONING.md) for setup and limitations.

Requires X_TEST:BOUNDED_JOG_V1 and X_MAP:STEP2_DIR3_EN40. Driver power is OFF
for flashing. Saw mains unplugged, valve power disconnected, air isolated.
Reboot clears Home verification and driver setup; revalidate before arm.
Prior 0.4.x notes below describe retained pneumatic/interlock behavior.

## Current logic-only interlock build: 0.4.1

Prepared on 2026-11-08. Valve 12V power must remain disconnected, air isolated,
and saw mains unplugged. Firmware 0.4.0 was flashed and its version, output map,
interlock identity, disarmed outputs, and initial not-ready status were verified
on COM4 on 2026-11-08. Manual physical interlock acceptance remains pending.

Build 0.4.1 is compiled, tested, flashed, and identified on COM4: it moves Saw Up from
Cyc/St/D17 to Limit Z/D22 after a reported Cyc/St input fault. Leave Cyc/St
disconnected. Connect switch COM to Lim Z Gnd and NO to Lim Z Sig, with NC
unused and no external positive voltage. Arming also requires the matching
`INPUT_MAP:DOOR29_UP22_DOWN16`; old 0.4.0 is input telemetry only in this HMI.
The new map and disarmed/OFF state were verified after flashing; physical
Saw Up switch acceptance on Limit Z was subsequently confirmed by the user.

- Arming requires a closed door and fully-UP feedback, each asserted for 20ms,
  no down confirmation, no pending return, and no latched fault.
- Door opening revokes permission on the next controller safety check without
  assertion debounce. Conflicting endpoints or unexpected loss of UP during
  an idle/clamp/trigger test disarm and latch a fault.
- Only one manual output may be ON at a time. A new output test starts at UP.
  DOWN may pass through neither endpoint while the travel output is held.
- Missing DOWN or missing return-UP faults after a provisional five seconds;
  every output is limited to five seconds ON. These limits need physical
  calibration later and are not an automatic cycle time.
- Heartbeat expiry after 1.5 seconds latches a fault. Late commands cannot
  revive an expired permit. Repeated ON commands cannot extend the ON timer.
- ALL OFF always remains available but does not acknowledge a fault. Close the
  door and confirm UP, then use ACKNOWLEDGE FAULT and a separate ARM action.
  Neither reset, reconnect, nor door closure energizes an output.
- The dashboard requires the matching output map, `INTERLOCKS:DOOR_POSITION_V1`,
  `COMMISSIONING:LOGIC_ONLY`, and fresh BENCH_SAFETY telemetry. Old firmware can
  still supply sensor telemetry but cannot enable new output-test controls.
- I2C health reads/scans are suspended while armed or awaiting return to avoid
  adding peripheral bus work to those local checks.

These checks are not safety-rated, do not establish clamp retention on a fault,
and do not authorize blade-powered cutting. All outputs OFF is the logic-test
response; its physical effects still need validation before loaded tests.

Firmware policy and complete serial command handling are exercised on the host
with mocked GPIO/Serial/I2C by `python test_bench_interlocks.py`. This requires a
C++ compiler; alternatively install the optional portable compiler with
`python -m pip install --target tmp/native-compiler ziglang==0.14.1`.

Output-map update (2026-11-08), firmware 0.3.2: OUT 0 is Saw Cylinder on AUX2/D33,
OUT 1 remains Main Clamp on AUX1/D32, and OUT 2 is Blade Trigger Air Valve on
Flood/D19. AUX0/D31 is retired after an unsuccessful output-voltage test. AUX1
and AUX2 passed user indicator tests; Flood has not yet been validated. Mist
remains spare. The HMI requires `OUTPUT_MAP:AUX2_AUX1_FLOOD` before output arming
is available; older firmware may still show input telemetry.

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

Recovery update (2026-11-07), firmware 0.3.1: Saw Up now uses Cyc/St D17 and
Saw Down uses Fd/Hld D16. Each switch uses COM to its terminal-pair Gnd and NO
to Sig, with Active-low checked: released HIGH/OFF, depressed LOW/ON. ST0/ST1
remain disconnected pending buffer/socket investigation. Their previous
polarity settings are not applied to the new saw inputs. Door remains D29.
MCP23017 and INA228 are intentionally disconnected; missing-device health
indicators are expected and do not prevent direct input telemetry.

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
Only D33, D32, and D19 are outputs, and they are reserved for guarded pneumatic trigger
tests. Enable, carriage motion, automatic saw cycles, g-code, and grbl commands
are rejected.

## Direct sensor map

| Firmware name | Breakout point | Teensy pin |
|---|---|---:|
| `HOME` | Limit X | D20 |
| `BOARD_EDGE` | Limit Y | D21 |
| `FENCE_DOOR` | Door | D29 |
| `CL57T_ALM` | Halt | D14 |
| `SAW_UP` | Limit Z | D22 |
| `SAW_DOWN` | Fd/Hld | D16 |
| `FENCE_CLOSED` | ST2 | D34 |
| `OUTFEED` | ST3 | D35 |

## Door and saw-position switches

For the door, saw-up, and saw-down dry-contact switches, follow
[the switch wiring and validation plan](SAW_AND_DOOR_SWITCH_PLAN.md). Expected
polarity is Active-low checked for Door, Limit Z, and Fd/Hld. Verify on the actual
board. Firmware 0.4.0 adds the logic-only controller checks described above;
physical interlock and output-response validation is still required.

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
|---|---|---|---|---|
| Saw cylinder valve | D33 / `OUT 0` | JP10 AUX2 `Sig` | JP10 AUX2 `Gnd` | Saw fully up |
| Main clamp valve, left of blade | D32 / `OUT 1` | JP10 AUX1 `Sig` | JP10 AUX1 `Gnd` | Clamp released/retracted |
| Blade-trigger pneumatic valve | D19 / `OUT 2` | JP10 Flood `Sig` | JP10 Flood `Gnd` | Factory trigger released |

On the dual-MOSFET module, connect JP10 `Sig` to J1 `TRIG/PWM` and JP10 `Gnd`
to J1 `GND`. J1 has two duplicate holes in each row: the upper pair is
`TRIG/PWM` and the lower pair is `GND`. Use one upper hole and one lower hole;
the two holes in the same vertical column make the cleanest two-wire harness.
The photographed Q1/Q2 devices are marked `D4184`, consistent with AOD4184A.

## First output test

Keep the saw's mains plug physically disconnected throughout all current
commissioning tests. Initially disconnect the MOSFET 12V load feed and test
only indicators/logic. For the trigger valve, verify the new valve's coil
voltage, current, fuse, and suppression before connecting load power. The
cylinder must release the original trigger on command OFF; loss of air or
electrical power must not hold the trigger pressed. Validate those responses
with the saw unplugged. The 0.4.0 build remains restricted to logic-only tests
until suppression and physical output/fault responses have been verified.

1. Isolate the air supply and disconnect all solenoid loads.
2. Power only the reviewed logic and MOSFET-module supply arrangement.
3. Confirm all module outputs are OFF before opening the HMI.
4. Connect the HMI and verify firmware `0.4.1`, both pin maps, and controller checks.
5. Close the door, confirm Saw UP only, check the logic-only confirmation, and click **ARM OUTPUT TEST**.
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

Future stage: do not perform this while coil suppression is missing or under
the current logic-only confirmation. Validate physical OFF/fault effects and
independent protections before transitioning from logic-only commissioning.

1. Verify a branch fuse is installed and the valve supply measures 12 VDC.
2. Secure the cylinder and attached mechanism; clear the entire travel and all
   pinch zones.
3. Put the manual pneumatic dump within reach and regulate pressure low.
4. Before arming, confirm `OUT 0 = 0` leaves the saw up and `OUT 1 = 0` leaves
   the main clamp released. Correct plumbing only while fully depressurized.
5. Test one output at a time with the momentary button. Do not run an automatic
   saw/clamp sequence from this application.
