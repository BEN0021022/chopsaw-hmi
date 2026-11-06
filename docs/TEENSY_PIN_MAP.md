# Teensy and T41U5XBB Pin Map

Status: preliminary - based on the connected validation firmware and the
T41U5XBB V2.20 board. This is not yet an approved machine-wiring map.

## Confirmed controller identity

- MCU module: PJRC Teensy 4.1
- Breakout: T41U5XBB V2.20
- Firmware-reported board map: `T41U5XBB`
- I2C voltage: 3.3 V only

## Firmware-reported assignments

| Function | Teensy pin | Breakout point | Domain | Current status |
|---|---:|---|---|---|
| X step | D2 | Axis X `Stp` | 5 V-compatible output stage | Reported; no driver connected |
| X direction | D3 | Axis X `Dir` | 5 V-compatible output stage | Reported; polarity unverified |
| X enable | D10 | Axis X `En` | 5 V-compatible output stage | Reported; active level unverified |
| X limit | D20 | Limit X `Sig` | Opto-isolated machine input | Reported; wiring mode unverified |
| Y limit / board edge | D21 | Limit Y `Sig` | Opto-isolated machine input | Selected for Banner Q4X board-edge sensor |
| Probe | D15 | Probe `Sig` | Opto-isolated machine input | Reserved; terminal has a reported soldering issue and is not used by sensor-bench firmware |
| Door | D29 | Door `Sig` | Opto-isolated machine input | Reported |
| Halt / E-stop status | D14 | Halt `Sig` | Opto-isolated status input | Reported; must not be the sole E-stop layer |
| ST0 | D36 | Digital Input ST0 | 3.3 V input group | Reported |
| ST1 | D30 | Digital Input ST1 | 3.3 V input group | Reported |
| ST2 | D34 | Digital Input ST2 | 3.3 V input group | Reported |
| ST3 | D35 | Digital Input ST3 | 3.3 V input group | Reported |
| AUX0 | D31 | AUX0 screw terminal | ULN2003 open-collector low-side sink | Do not use for the active-high MOSFET trigger |
| AUX1 | D32 | AUX1 screw terminal | ULN2003 open-collector low-side sink | Do not use for the active-high MOSFET trigger |
| AUX2 | D33 | AUX2 screw terminal | ULN2003 open-collector low-side sink | Do not use for the active-high MOSFET trigger |
| AUX0 TTL | D31 | JP10 `AUX0` Sig/Gnd row | 5 V non-inverting logic from 74AHCT541 | Planned Clamp 1 MOSFET trigger |
| AUX1 TTL | D32 | JP10 `AUX1` Sig/Gnd row | 5 V non-inverting logic from 74AHCT541 | Planned Clamp 2 MOSFET trigger |
| AUX2 TTL | D33 | JP10 `AUX2` Sig/Gnd row | 5 V non-inverting logic from 74AHCT541 | Planned Clamp 3 MOSFET trigger |
| Flood | D19 | Relay Flood | Open-collector relay driver | Reported; load unassigned |
| Mist | D18 | Relay Mist | Open-collector relay driver | Reported; load unassigned |
| I2C SCL | D24 | I2C `SC`/SCL | 3.3 V | Bench-verified with MCP23017 and INA228 |
| I2C SDA | D25 | I2C `SD`/SDA | 3.3 V | Bench-verified with MCP23017 and INA228 |

## Planned I2C device map

All devices connect in parallel to D24/SCL and D25/SDA and share controller
ground. Power the modules from the breakout's 3.3 V I2C supply unless a reviewed
schematic explicitly establishes another safe logic/power arrangement.

| Device | 7-bit address | Connections | Status |
|---|---:|---|---|
| Adafruit INA228 product 5832 | `0x40` default; A0/A1 open | 3.3 V, GND, SDA/D25, SCL/D24; `ALRT` initially disconnected | Bench-detected at `0x40` on the shared bus |
| Waveshare MCP23017 expander | `0x27` with A0-A2 open | 3.3 V, GND, SDA/D25, SCL/D24; `INTA/INTB` initially disconnected | Bench-detected at `0x27` on the shared bus |

The INA228's power-path terminals are separate from its logic connections. The
planned topology is high-side DC measurement: supply positive to `VIN+`, load
positive from `VIN-`, and `VBUS` tied to `VIN+` using either an explicit wire or
the reviewed board jumper. Do not close the jumper or energize the measured
branch until the branch voltage, expected current, fuse, wire gauge, and terminal
orientation are recorded in `docs/INA228_CURRENT_MONITOR_PLAN.md`.

## JP5 I2C header and MCP23017 harness

The official T41U5XBB V2.20 schematic identifies the unpopulated six-position
header as JP5. With the board oriented exactly as in the component-side photo
and the silkscreen text readable, its holes run from left to right as follows:

| JP5 position | Board silk | Schematic net | Function for this project |
|---:|---|---|---|
| 1, far left | `Hlt` | `PANIC` | Not part of I2C; leave unconnected |
| 2 | `+V` | `+3V3` | I2C-device 3.3 V logic power |
| 3 | `St` | `KPSTR` | Optional keypad/strobe signal; leave unconnected |
| 4 | `SD` | `SDA` | I2C data, Teensy D25 |
| 5 | `SC` | `SCL` | I2C clock, Teensy D24 |
| 6, far right | `G` | `GND` | Logic ground |

The supplied Waveshare six-wire cable is ordered at its MCP23017 connector as
shown in the photographed back-side silkscreen. Verify every conductor with a
continuity meter before connecting it because cable colors are not an electrical
standard.

| Waveshare signal | Observed wire color | Connect to T41 JP5 | Action |
|---|---|---|---|
| `INTB` | Green | None | Leave disconnected and individually insulated |
| `INTA` | Orange | None | Leave disconnected and individually insulated |
| `SCL` | Yellow | Position 5, `SC` | Connect |
| `SDA` | Blue | Position 4, `SD` | Connect |
| `GND` | Black | Position 6, `G` | Connect |
| `VCC` | Red | Position 2, `+V` | Connect; this is 3.3 V, not 5 V |

Do not mate the six conductors straight across by position: the connector orders
are different and a one-to-one six-pin connection would miswire power and ground.
JP5 is an unpopulated 2.54 mm header footprint, not a screw terminal. Use a
soldered header or secured soldered harness and provide strain relief; do not
insert bare strands or ferrules into the plated holes.

### Unpowered continuity checks

1. Remove USB and all external power.
2. Buzz each Waveshare connector position to the matching labeled side pad and
   confirm the observed color table above.
3. After making the harness, buzz each end-to-end connection and confirm that
   JP5 position 2 (`+V`) is not shorted to position 6 (`G`).
4. Leave MCP23017 `INTA`/`INTB` and JP5 `Hlt`/`St` isolated.
5. For the first powered test, leave every MCP23017 PA/PB I/O pin unconnected
   and run the I2C scan; expect the default 7-bit address `0x27`.

## Clamp MOSFET trigger mapping

The board schematic confirms that the AUX screw terminals and JP10 logic header
are two different electrical interfaces. The owned MOSFET modules require an
active-high trigger, so use the separate unpopulated header marked
`5V TTL/SSR Relay`, schematic designator JP10. With the board oriented as in the
component-side photograph, the left hole in each labeled row is `Sig` and the
right hole is `Gnd`.

| Sensor Bench command | Planned use | JP10 connection | Teensy pin | Approval |
|---|---|---|---|---|
| `OUT 0 0/1` | Clamp 1 | JP10 AUX0 `Sig` and adjacent `Gnd` | D31 | Firmware mapped; electrical test pending |
| `OUT 1 0/1` | Clamp 2 | JP10 AUX1 `Sig` and adjacent `Gnd` | D32 | Firmware mapped; electrical test pending |
| `OUT 2 0/1` | Clamp 3 | JP10 AUX2 `Sig` and adjacent `Gnd` | D33 | Trigger LED bench-verified; no load connected; valve test pending |

Do not connect the module `TRIG/PWM` input to an AUX screw-terminal output: that
path is an inverting open-collector sink and does not supply the active-high
trigger this module expects. The JP10 logic grounds are trigger-return grounds;
the MOSFET module load supply and valve wiring use the module power terminals.

The Sensor Bench intentionally exposes only these three clamp-test outputs.
Actuator forward/reverse remain unavailable and still require independent
electrical and firmware direction exclusion.

## Observed validation inputs

The unconnected USB-only board reported these raw names:

`HOME`, `BOARD_EDGE`, `FENCE_DOOR`, `CL57T_ALM`, `SAW_UP`, `SAW_DOWN`,
`FENCE_CLOSED`, and `OUTFEED`.

Their observed raw levels are not interpreted here because the sensors, pull
behavior, active polarity, and fail-safe wiring have not been established.

## Guarded sensor-bench firmware

`firmware/chopsaw_sensor_bench/chopsaw_sensor_bench.ino` is the source-controlled
commissioning firmware. It remaps `BOARD_EDGE` from Probe/D15 to the intact
Limit Y/D21 screw terminal, configures the eight documented direct inputs and
all MCP23017 channels as inputs, and configures only D31-D33 as guarded clamp
test outputs. They latch LOW before output mode, require explicit HMI arming and
a 500 ms keepalive, shut off after 1.5 seconds without keepalive, and have a
5-second maximum continuous-on time. No motion, actuator, saw, or enable output
is available. The companion HMI is launched with `python run_sensor_bench.py`.

## Signals still to allocate and approve

- Carriage home/limits and positive travel direction.
- Board-present/edge, guard/door, fence closed, and clamp confirmation.
- Saw-up and saw-down confirmations.
- Motor-driver alarm, enable, and reset.
- Hardwired E-stop status feedback.
- Pneumatic pressure switch and dump-valve state.
- Actuator forward/reverse commands and both end limits or position feedback.
- Current, voltage, power, and temperature telemetry.
- Protected spare inputs and outputs for future sensors.

No terminal is approved for a machine connection until its voltage, polarity,
boot behavior, disconnected-wire behavior, safe state, source/load, connector,
wire label, and firmware field are recorded.

## References

- Physical T41U5XBB V2.20 silkscreen and the connected validation firmware's
  `PINMAP`, `I2C`, and `STATUS` responses
- [Official T41U5XBB V2.20 schematic](https://github.com/phil-barrett/grblHAL-teensy-4.x/blob/master/T41U5XBB-V2.20%20schematic.pdf)
