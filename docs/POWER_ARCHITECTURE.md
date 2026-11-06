# Preliminary Power Architecture

Status: commissioning draft - do not use this document as a finished wiring diagram.

## Safe configuration for the current bench stage

```text
Dell 19.5 VDC / 9.23 A source
   +--> 5.00 V buck --> externally powered T41U5XBB and Teensy logic
   +--> 12.0 V buck --> fused sensor/valve branches and MOSFET VIN

Laptop USB --> verified data-only power blocker/cable --> Teensy communications
```

This matches the successful communications test and prevents an external supply
from backfeeding the laptop USB port.

## Planned power domains

```text
AC mains
   |
   +-- fused machine power / safety contactor --> motor and other high-energy loads
   |
   +-- Dell 180 W adapter: 19.5 VDC, 9.23 A source rail
          |
          +-- 5.00 V buck --> T41U5XBB logic input
          |
          +-- 12.0 V buck --> sensors and individually protected valve branches
          |
Laptop USB --> dedicated data-only cable (VBUS conductor removed) --> Teensy communications
```

The final system may use different field voltages after the valves, actuator,
sensors, motor driver, and safety components are identified. The hardwired
E-stop, contactor/driver disable, and pneumatic energy dump must not depend on
the PC, HMI, USB link, or application software.

## T41U5XBB V2.20 power findings

- The official V2.20 schematic says the board may be powered from USB or an
  external 5 V input.
- The selected solution for simultaneous external 5 V power and USB
  communications is a dedicated USB cable with its 5 V/VBUS conductor physically
  removed. USB data and ground remain connected; the cable must be labeled and
  verified with a continuity meter before use.
- Leave `JP105` unmodified. Never use an ordinary powered USB cable while the
  buck's 5 V output is connected to the breakout.
- Set the buck output to `5.00 V` with no breakout attached, verify it with a
  trusted multimeter, then re-check under a small test load.
- The board's +12 V input supports the relay and 0-10 V spindle sections; it does
  not replace the 5 V logic supply.
- The relay-voltage selector routes either 5 V or 12 V to the relay-driver common.
  Its position must match the connected coil voltage.
- The schematic states that no more than 150 mA should be supplied off-board from
  the T41U5XBB 5 V rail. External module loads need a documented power budget.
- I2C signaling is 3.3 V. Any I2C sensor or level translator must be checked for
  3.3 V-compatible logic and pull-ups before connection.

The official file is named for V2.20, although its internal drawing title still
contains a V2.07 label. The selected data-only USB cable avoids modifying JP105.

## Required protections and decisions

- Fuse the 5 V and 12 V feeds and each material load branch based on verified wire and
  device ratings.
- Add reverse-polarity and transient protection where it is not already present.
- Confirm whether each MOSFET module switches the high or low side and whether it
  includes a flyback path. Inductive valves and relays require proper suppression.
- Establish one documented DC reference/grounding scheme while preserving the
  breakout's intended opto-isolation boundaries.
- Route motor, saw, valve, and actuator wiring separately from USB, I2C, encoder,
  limit, and current-monitor signal wiring.
- Add strain relief, terminal labels, guarded power distribution, and a service
  disconnect in the final enclosure.

## Current commissioning checks

1. Keep the verified USB power blocker/data-only connection permanently labeled;
   never substitute an ordinary powered USB cable while external 5 V is present.
2. Measure both buck outputs before every reconnection: 5.00 V for logic and
   12.0 V for sensors/valves.
3. Confirm the 12 V valve feed is fused before its distribution split and that
   the fuse rating protects the smallest downstream conductor and connector.
4. Confirm each MOSFET output is OFF at boot, USB disconnect, HMI disconnect,
   watchdog timeout, and firmware reset.
5. Verify the saw returns up and the main clamp releases when their valve coils
   are de-energized before permitting higher pressure or combined sequencing.

## Reference

- [Official T41U5XBB V2.20 schematic](https://github.com/phil-barrett/grblHAL-teensy-4.x/blob/master/T41U5XBB-V2.20%20schematic.pdf)
