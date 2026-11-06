# INA228 Current-Monitor Plan

Status: selected and visually confirmed hardware; measured branch and final
energized wiring are not yet approved.

## Selected module

- Adafruit INA228 breakout, product 5832; front and back visually confirmed.
- INA228 20-bit I2C current, voltage, and power monitor.
- Onboard 15 mOhm shunt. Adafruit's PCB schematic identifies R1 as a 2 W,
  15 mOhm part; use `0.015` ohm in firmware unless physical/electrical evidence
  for this exact board establishes otherwise.
- Maximum bus/common-mode voltage: 85 VDC. Not for AC measurement.
- Adafruit-documented current ranges: up to approximately 10 A in the
  high-current range or 2.75 A in the more-sensitive range.
- Default 7-bit I2C address: `0x40`; photographed A0/A1 jumpers are open.

The photographed back silkscreen confirms 0-85 VDC bus, +/-10 A maximum,
I2C address `0x40`, and 3-5 V logic power. The VBUS jumper appears open and
must be verified electrically before high-side wiring.

## Logic-side connection

| INA228 pin | T41U5XBB connection | Notes |
|---|---|---|
| `VIN` (logic power) | I2C header `3.3V` | Use 3.3 V so its I2C pull-ups remain Teensy-safe |
| `GND` | I2C header `Gnd` | Logic reference only; preserve the documented machine grounding scheme |
| `SCL` | I2C header `SC`, Teensy D24 | Shared I2C clock |
| `SDA` | I2C header `SD`, Teensy D25 | Shared I2C data |
| `ALRT` | Disconnected for first scan | Assign a protected/free input only after alert behavior is designed |

The INA228 at `0x40` and the expected MCP23017 at `0x27` may share the bus.
Confirm both addresses with the validation scanner before enabling either
device in production firmware.

## Provisional measured-power connection

Use high-side measurement for the selected low-voltage DC load:

```text
DC supply positive ---- fuse ---- INA228 VIN+ / VBUS
                                  INA228 VIN- ---- load positive
DC supply negative ------------------------------ load negative
```

The board's rear VBUS jumper can connect VBUS to VIN+ for high-side use. Leave
it open until the board orientation and continuity have been verified. An
explicit removable wire is preferable for the first current-limited bench test.

## Decisions required before load wiring

- Select the measured branch. The leading candidate is the DC input feeding the
  CL57T, not either chopped motor-phase conductor.
- Record the supply voltage and polarity.
- Measure or obtain normal, acceleration, peak, stall, and fault current.
- Select the 10 A or 2.75 A measurement range from those values.
- Confirm that the onboard shunt, terminal block, wire, and fuse are suitable
  for the continuous and peak current.
- Decide the firmware sample rate, averaging, warning threshold, trip threshold,
  and trip delay.
- Decide whether `ALRT` is used. Any protective response must occur in Teensy
  firmware/hardwired controls and must not depend on the Windows HMI.

## Firmware integration plan

- First use an I2C scan to confirm the board at `0x40` with no load current.
- Bench-test with Adafruit's `Adafruit_INA228` Arduino library and configure the
  onboard shunt with `setShunt(0.015, selected_max_current)`.
- Select conversion time and averaging after observing noise with the CL57T
  enabled and moving; begin with 16-sample averaging as a conservative test.
- Add normalized firmware telemetry for bus volts, current amps, power watts,
  monitor temperature, and alert/fault status.
- Preserve the HMI's existing `CUR` and `OCT` fields during migration, then add
  versioned voltage/power fields without breaking the legacy backend.
- The current grblHAL Teensy configuration advertises an MCP23017 expander but
  does not provide a turnkey INA228 option. Integrate the Adafruit driver into
  our machine-specific firmware layer or write a small grblHAL plugin; do not
  assume enabling a stock compile flag completes the feature.

## Safety boundary

The INA228 provides telemetry and may support a firmware-controlled diagnostic
trip. It does not replace branch fusing, the CL57T's protection/alarm output,
the hardwired E-stop/disable chain, or correctly sized wiring. Do not use this
breakout to measure the AC saw-motor mains circuit.

## References

- [Adafruit INA228 product 5832](https://www.adafruit.com/product/5832)
- [Adafruit INA228 guide](https://learn.adafruit.com/adafruit-ina228-i2c-power-monitor)
- [Adafruit INA228 pinouts](https://learn.adafruit.com/adafruit-ina228-i2c-power-monitor/pinouts)
- [Texas Instruments INA228](https://www.ti.com/product/INA228)
