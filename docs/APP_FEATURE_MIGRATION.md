# Main app feature migration: MEGA to Teensy

Updated 2026-11-08. The active implementation is **custom controller 0.7.0**,
not stock grblHAL. The main app's **Teensy Carriage** mode owns one serial
connection, parses controller records on the Qt thread and applies a command
allowlist at the serial-write boundary. Sensor Bench remains a separate tool;
close it before opening the main app on the same COM port.

## Feature mapping

| Feature | Old MEGA path | Current Teensy path | Status / next acceptance |
|---|---|---|---|
| Connect / identity | Implicit serial protocol | HELLO, PINMAP, STATUS; exact machine identity and calibration match | Implemented; connect is reads only |
| Manual carriage jog | M inches / HMI absolute target | XJOG direction pulses, 127.12 pulses/inch | Native CARRIAGE tab, 0.01-2 in per click, 254 pulses/arm, 40 pulses/s; operator acceptance pending |
| Direction | Old DIR conventions | A/DIR LOW toward saw; B/HIGH toward Home | Physically user-confirmed |
| Enable / holding | E / X | ARM sets verified LOW; XDISABLE stops and sets HIGH | Verified hardware via Axis Y En/D40; original X En unused |
| Stop / cancel | M0 | OFF, XARM 0; heartbeat fallback | Implemented, native and app tests; physical stop/fault acceptance pending |
| Driver setup / arming | Implicit enabled startup | Explicit Home-input verification, setup ACK and arm ACK | No auto-enable/auto-arm on connect, reset or reconnect |
| Position display | Encoder POS plus step estimate | POS_STEPS / 127.12; signed pulse-count displacement since boot | Clearly marked unreferenced; never used as blade distance |
| Closed-loop error | MEGA encoder/PID fields | CL57T closes loop; ALM on Halt/D14 | Alarm trips motion; real 7-flash fault traced to loose encoder wire and resolved |
| Home | H, positive seek, home coordinate 160.5 in | Reserved controller state machine | NOT implemented; next carriage feature |
| Absolute length / load positions | S inches | Reserved, requires successful homing and position validity | NOT implemented; do not send MEGA S or prototype G-code |
| Soft limits | Legacy target clamping | Requires homed coordinate and measured/confirmed envelope | Pending with homing |
| Profiles / speed / acceleration | Z, A speed,accel | Fixed conservative 40 pulses/s for commissioning | Planner/acceleration and profile migration pending |
| Board detection / truing | J / N, board-edge offset | Limit Y/D21 telemetry available | Geometry, offsets and bounded controller-side sequence pending |
| Door | Ad hoc/old hardware | Door/D29 active LOW, controller interlock | User confirmed input; firmware/app cancellation tested |
| Saw endpoints | Old SSEN | UP Limit Z/D22; DOWN Fd/Hld/D16 | User-confirmed inputs, controller interlocks |
| Main left clamp | C/D/L/U (legacy command collision) | OUT 1 / AUX1 TTL D32 | Bench LED proven; main app unavailable until diode/coil acceptance and clamp fault policy |
| Saw travel cylinder | Old saw cycle command | OUT 0 / AUX2 TTL D33 | OFF=UP confirmed; suppression and isolated pneumatic dry run pending |
| Blade trigger cylinder | Original trigger/brake mechanism | OUT 2 / Flood TTL D19 | Main app unavailable; validate OFF release/brake, no blade-powered test yet |
| Cut-list editing/import | Python UI | Same retained Python feature | Available; simulator regression passes |
| Automatic cut-list workflow | Old MEGA state strings + timed callbacks | New controller events / acknowledgments required | Locked on live Teensy; simulate only |
| Early return | Carriage return during cutting | Reassess collision/clamp/blade policy first | Locked on live hardware |
| Current monitoring | ACS712 fields | INA228 future work | Deferred; INA/MCP quarantined/disconnected |
| MEGA PID toggle | K0/K1 | Driver-managed closed loop | Retired on live Teensy; no duplicate HMI PID loop |
| Diagnostics / settings | Raw legacy console | Live raw records in SETTINGS; bounded command boundary | Legacy motion/output writes rejected in Carriage mode |

## Operator flow for the first main-app carriage acceptance

1. Keep saw mains unplugged, valve supply disconnected and air isolated. Keep
   suspect INA/MCP disconnected. Launch `python main.py`, select Teensy Carriage,
   choose the Teensy COM port and connect. Verify firmware 0.7.0 telemetry.
2. Verify actual Home sensor transitions after reboot. Door closed, saw UP only,
   driver green ON/red OFF, alarm raw HIGH. Confirm isolation/driver checks.
3. Confirm driver setup. Wait for controller acknowledgment, then ARM CARRIAGE.
   No motion occurs on either action.
4. Start at 0.1 in. A moves toward saw; B toward Home. Pulses are rounded to the
   nearest full step. View displacement and remaining move/arm budget.
5. Verify STOP, door opening, alarm and communications-loss responses in
   controlled tests. No cancellation may resume automatically. ACK does not arm.
6. Release motor holding torque only when ready for a free carriage. This clears
   input/setup verification. Position is always labeled commanded displacement.

## Next controller/app slice

Implement a bounded Home seek/release/slow-latch sequence in the known B
home direction, with travel/time limits, sensor-stuck checks and cancellation.
Recover legacy 160.5-inch home reference but verify physical reference before
using it as blade distance. Only then add homed position validity, soft limits,
absolute inch moves, load positions and acceleration/profiles. Alarm or driver
release must invalidate position and require rehoming before absolute moves.

After suppression is installed, validate individual air outputs with blade
unplugged, define clamp retention/release on faults, then migrate the cut-list
state machine to explicit controller completion/fault events. Hardware-only
acceptance is not replaced by the automated tests.
