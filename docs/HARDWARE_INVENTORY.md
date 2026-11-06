# Hardware Inventory

Last updated: 2026-11-06

This is the working inventory for the Chop Saw HMI electronics. A photographed
item is recorded as owned, but its electrical ratings remain unverified until a
part number, datasheet, or legible component marking is available.

## Confirmed owned hardware

| Item | Identification | Qty | Status | Notes |
|---|---|---:|---|---|
| Controller | PJRC Teensy 4.1, i.MX RT1062 | 1 | Owned; USB bench-tested | USB serial enumerated and validation firmware responded. |
| Breakout board | Brookwood Design / The Grbl Project T41U5XBB V2.20 | 1 | Owned; visually confirmed | Five-axis grblHAL breakout with opto-isolated machine inputs, relay drivers, 3.3 V digital inputs, I2C, UART, and spindle control. |
| Primary DC supply | Dell laptop AC adapter, 180 W | 1 | Owned; powering current bench stack | Output label reported as 19.5 VDC, 9.23 A. This is the source rail only; never connect it directly to 12 V valves or 5 V logic. |
| DC-DC converters | Adjustable step-down/buck modules, one with display | 2 | Owned; exact models unknown | One branch is adjusted to 5.00 V for the breakout and one to 12.0 V for sensors/valves. Verify both outputs and polarity before every wiring change. |
| Current sensor | UMLIFE ACS712 analog current-sensor module; Amazon selection reported as 20 A | 1 | Owned; exact IC marking still unverified | Retain as a bench/spare sensor. It is not the planned machine current monitor and its 5 V analog output must never be connected directly to a Teensy pin. |
| Current/power monitor | Adafruit INA228 breakout, product 5832, onboard 15 mOhm shunt | 1 | Owned; detected at `0x40` | Planned machine current monitor. Board silkscreen confirms 0-85 VDC bus, +/-10 A maximum, 3-5 V logic, and default `0x40` address. A0/A1 and VBUS jumpers appear open; measured-current path remains unconnected. Power logic from 3.3 V for this installation. |
| I/O module | Waveshare MCP23017 I/O Expansion Board, 16 digital I/O | 1 | Owned; detected at `0x27` | Connected to the 3.3 V I2C bus. Sensor-bench firmware configures all channels as inputs with 3.3 V pull-ups. Digital I/O only--raw 5/12/24 V field signals are not permitted. |
| Laser presence sensor | Banner Q4XTBLAF300-Q8, 25-300 mm, bipolar NPN/PNP | 1 photographed | Owned; exact quantity to confirm | Power from fused 10-30 VDC. Planned board-edge input uses white NPN output to Limit Y `Sig`, blue to input `Gnd`, black PNP and gray remote input insulated. |
| MOSFET switch module | Seloky SY074 dual-MOSFET trigger switch module; Amazon ASIN B0DZP1D2S8 | 4 | Owned; three trigger channels bench-tested | Top-side image shows two parallel TO-252 devices marked `D4184`, consistent with the AOD4184A family. One active-high switched channel per board. Seller states 5-36 V load and 3.3-20 V trigger. No onboard flyback diode is documented. |
| Pneumatic directional valve | AirTAC 4V210-08, single-solenoid 5/2 spring return | 1 confirmed | Owned; electrically and pneumatically tested | Coil label: 12 VDC, 3.0 W, 10.8-13.2 V, 100% ED. DIN plug contains an LED/resistor and apparent suppression diode. P=supply, A/B=cylinder, R/S=exhaust. Port A is currently noted as connected to the front fitting on the small cylinder. |
| Saw pneumatic cylinder | Exact model pending | 1 | Installed on saw and plumbed as of 2026-11-06 | Must verify restrained travel, flow controls, saw-up/saw-down feedback, and that valve OFF returns the saw to the safe up position. |
| Main board-clamp cylinder | Exact model pending | 1 | Installed left of saw blade and plumbed as of 2026-11-06 | Must verify released/clamped feedback and that valve OFF releases or otherwise enters the approved safe state. |
| Mechanical carrier | Custom 3D-printed mounting plate | 1 | Owned | Current layout is a useful prototype; final clearances, wire ducts, strain relief, and guarded high-energy wiring remain to be planned. |

## Confirmed controller observations

- USB device: VID `16C0`, PID `0483`, serial `19629650`.
- Validation firmware board identifier: `T41U5XBB`.
- Shared I2C scan detected the MCP23017 at `0x27` and INA228 at `0x40`.
- Breakout screw terminals are 3.5 mm pitch. Use correctly sized ferrules on
  stranded wire; 22 AWG / 0.34 mm2 is the current signal-wire candidate.

## Still needed for a complete BOM

- Buck-converter model, rated continuous output current, and thermal margin.
- Buck-converter model and rated continuous output current.
- ACS712 IC marking/current range if the spare module will be used for testing.
- INA228 measured-branch voltage/current data, range choice, fuse, wire size, and final terminal orientation.
- MCP23017 final conditioned, non-safety channel assignments.
- Final valve-branch fuse arrangement and confirmation of the DIN suppression circuit.
- Stepper/servo motor, driver, encoder, and motor-power-supply specifications.
- E-stop components, safety contactor/relay, motor-enable chain, and pneumatic
  dump-valve details.
- Limit, saw-up/down, guard, fence, clamp, pressure, and board-presence sensors.
- Pneumatic valve and automatic-actuator voltage/current specifications.
- Fuses, disconnects, distribution blocks, connectors, shielded cable, ferrules,
  labels, enclosure, DIN rail, and grounding hardware.

## Photo requests for the next hardware session

Take close, square photos of both sides of each remaining unidentified module.
Include IC and MOSFET markings, terminal labels, jumpers, and vendor labels.
Also capture the relay-voltage selector and every connected power-supply label.

## References

- [T41U5XBB product page](https://www.grbl.org/grblhal-breakout-board)
- [Official T41U5XBB resources](https://www.grbl.org/t41u5xbb-information)
- [Official T41U5XBB V2.20 schematic](https://github.com/phil-barrett/grblHAL-teensy-4.x/blob/master/T41U5XBB-V2.20%20schematic.pdf)
- [Adafruit INA228 product 5832](https://www.adafruit.com/product/5832)
- [Adafruit INA228 wiring and pinout guide](https://learn.adafruit.com/adafruit-ina228-i2c-power-monitor/pinouts)
- [Waveshare MCP23017 I/O Expansion Board](https://www.waveshare.com/mcp23017-io-expansion-board.htm)
- [Seloky SY074 Amazon listing](https://www.amazon.com/dp/B0DZP1D2S8)
- [Common dual-AOD4184 module technical reference](https://protosupplies.com/product/high-power-dual-mosfet-switch-module/)
- [AOSMD AOD4184A manufacturer page and marking resources](https://www.aosmd.com/products/mosfets/medium-voltage-mosfets-40v-400v/aod4184a)
