# Hardware Bill of Materials

Status: working purchasing list. Do not order voltage- or current-dependent
parts until the associated load specifications are recorded.

## Owned

| Qty | Item | Exact identification | Verification still needed |
|---:|---|---|---|
| 1 | Controller | PJRC Teensy 4.1 | Record firmware image/version used for each test |
| 1 | Breakout | T41U5XBB V2.20 | Leave JP105 unmodified; externally powered USB communications require the verified data-only cable |
| 1 | Adjustable buck converter with display | Unknown | Model, input/output limits, continuous current, ripple |
| 1 | Analog current-sensor module | UMLIFE ACS712; Amazon selection reported as 20 A | Confirm the actual IC marking; retained as a bench/spare sensor |
| 1 | Digital I/O expander | Waveshare MCP23017 I/O Expansion Board, verified at `0x27` | Allocate only conditioned, non-safety I/O |
| 1 | Digital current/power monitor | Adafruit INA228 breakout, product 5832, 15 mOhm onboard shunt | Owned and visually confirmed; verify the measured branch stays within the board's 0-85 VDC and +/-10 A markings, then select range, fuse, and wire size |
| Confirm qty | Laser presence sensor | Banner Q4XTBLAF300-Q8, 10-30 VDC, 25-300 mm, NPN and PNP outputs | Use white NPN output with protected breakout input; do not route black PNP field voltage to Teensy/MCP inputs |
| 4 | Dual-MOSFET trigger modules | Seloky SY074, Amazon ASIN B0DZP1D2S8; top-side image shows two parallel `D4184` TO-252 devices, consistent with AOD4184A | Bench-verify active-high 5 V trigger and safe boot; seller ratings are not yet accepted as design limits |
| 1 | 3D-printed prototype mounting plate | Custom | Final enclosure and wiring clearances |

## Ordered

No items have been positively identified as ordered but not yet received.

## Needed before powered machine integration

| Item | Selection depends on | Safety/quality requirement |
|---|---|---|
| Regulated DC supply or supplies | Final 12/24 V loads and total current | Listed supply, protected input, adequate derating |
| Branch fuses and holders | Verified load and wire ampacity | One documented fuse schedule |
| Main disconnect and safety contactor/relay | Machine energy sources | Hardwired removal of hazardous energy |
| E-stop and reset devices | Required safety architecture | Positive-opening/latching behavior as appropriate |
| Pneumatic dump valve | Valve voltage, flow, and machine risk | Removes stored pneumatic energy independently of software |
| Terminal/distribution blocks | Final voltage domains and enclosure | Finger-safe and clearly labeled |
| Shielded signal cable | Sensor types and routing distance | Drain/shield termination documented at one intended point |
| Hook-up wire | Circuit current and terminal capacity | 22 AWG / 0.34 mm2 candidate for low-current signals only |
| Ferrules and labels | Final wire gauges and terminal insertion depth | Correct die, barrel length, and pull-test procedure |
| Enclosure, DIN rail, duct, glands, and strain relief | Final component layout | Separation of high-energy and low-level signal wiring |
| Flyback/transient suppression | Actual coils, valves, and relays | Located at the inductive load when practical |
| Protected sensor interfaces | Sensor output voltages/types | No raw field voltage applied to Teensy pins |

## Optional / future

| Item | Purpose | Constraint |
|---|---|---|
| Additional INA228 channels or an external-shunt implementation | Additional high-side voltage/current/power telemetry | Add only after the measured branches and current ranges are defined |
| Additional isolated inputs | Future position, guard, pressure, and process sensors | Preserve at least 25 percent spare protected I/O |
| Additional protected outputs | Future valves and auxiliary actuators | Include per-channel safe state and suppression |
| Panel USB extension with ferrite | Serviceable HMI/controller communications | Keep away from motor and switched-load wiring |
| CAN or isolated serial expansion | Remote future I/O | Adopt only after grblHAL pin/resource conflict review |

## Do not order yet

- Replacement or external current shunts until the measured branch, normal
  current, stall current, and worst-case fault current are known. The Adafruit
  INA228 already includes a 15 mOhm shunt for its documented ranges.
- Pneumatic valve drivers until coil voltage and current are known.
- Actuator reversing hardware until the actuator voltage, stall current, limit
  scheme, and required electrical direction interlock are known.
- Replacement MOSFET modules until the existing modules are positively
  identified and tested.

See `HARDWARE_INVENTORY.md`, `POWER_ARCHITECTURE.md`, and `TEENSY_PIN_MAP.md`
for the evidence and unresolved design decisions behind this list.
