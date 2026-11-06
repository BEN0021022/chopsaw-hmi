# Preliminary Power Architecture

Status: planning only - do not use this document as a finished wiring diagram.

## Safe configuration for the current bench stage

```text
Laptop USB (normal cable for USB-only bench testing)
   |
   +----> Teensy 4.1 USB connector
              |
              +----> T41U5XBB logic rail

12 V supply: OFF / disconnected
Buck converter output: disconnected from T41U5XBB
Field loads and MOSFET loads: disconnected
```

This matches the successful communications test and prevents an external supply
from backfeeding the laptop USB port.

## Planned power domains

```text
AC mains
   |
   +-- fused machine power / safety contactor --> motor and other high-energy loads
   |
   +-- protected DC supply branch(es)
          |
          +-- 12 V field/relay branch --> T41U5XBB +12 V input when required
          |
          +-- 12 V --> buck converter --> regulated 5.00 V logic branch
                                      --> T41U5XBB +5 V
                                      --> compatible sensors/modules as budgeted

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

- Fuse the 12 V feed and each material load branch based on verified wire and
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

## Next no-load electrical checks

1. With both ends disconnected, verify that the dedicated USB cable has no VBUS
   continuity while D+, D-, and ground remain continuous; label it DATA ONLY.
2. Confirm the relay-voltage selector position and map its three pins.
3. Power only the buck from a current-limited 12 V source; adjust and verify
   5.00 V output and polarity.
4. Do not connect MOSFET loads. Identify each module and bench-check its inactive
   state before deciding which signals may drive it.
5. Repeat the Teensy USB diagnostics first in the known USB-only state, then in
   the externally powered state using only the verified data-only cable.

## Reference

- [Official T41U5XBB V2.20 schematic](https://github.com/phil-barrett/grblHAL-teensy-4.x/blob/master/T41U5XBB-V2.20%20schematic.pdf)
