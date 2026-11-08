# Main app feature migration: MEGA to Teensy

Updated 2026-11-08. The active implementation is **custom controller 0.11.0**,
not stock grblHAL. The main app's **Teensy Carriage** mode owns one serial
connection, parses controller records on the Qt thread and applies a command
allowlist at the serial-write boundary. Sensor Bench remains a separate tool;
close it before opening the main app on the same COM port.

## Feature mapping

| Feature | Old MEGA path | Current Teensy path | Status / next acceptance |
|---|---|---|---|
| Connect / identity | Implicit serial protocol | HELLO, PINMAP, STATUS; exact machine identity and calibration match | Implemented; connect is reads only |
| Manual carriage jog | M inches / HMI absolute target | XJOG direction pulses, 127.12 pulses/inch | Native CARRIAGE tab, 0.01-2 in per click, 254 pulses maximum per click; repeatable while armed, 40 pulses/s; operator acceptance pending |
| Direction | Old DIR conventions | A/DIR LOW toward saw; B/HIGH toward Home | Physically user-confirmed |
| Enable / holding | E / X | ARM sets verified LOW; XDISABLE stops and sets HIGH | Verified hardware via Axis Y En/D40; original X En unused |
| Stop / cancel | M0 | OFF, XARM 0; heartbeat fallback | Implemented, native and app tests; physical stop/fault acceptance pending |
| Driver setup / arming | Implicit enabled startup | Home input clear, explicit setup ACK and arm ACK; no sensor-trip ritual | No auto-enable/auto-arm on connect, reset or reconnect |
| Position display | Encoder POS plus step estimate | POS_STEPS displacement plus POS_KNOWN/HOME_OFFSET after Home | Homed coordinate only after completed Home; fault/release invalidation |
| Closed-loop error | MEGA encoder/PID fields | CL57T closes loop; ALM on Halt/D14 | Alarm trips motion; real 7-flash fault traced to loose encoder wire and resolved |
| Home | H, positive seek, home coordinate 160.5 in | XHOME selected search limit; seek/release/backoff/slow latch/pull-off | User confirmed Home success; repeatability/reference acceptance remains |
| Absolute length / load positions | S inches | XMOVE integer milliinches; known position + explicit arm | Implemented 0.11.0; native inch target and load presets; physical acceptance pending |
| Soft limits | Legacy target clamping | Firmware target-time and per-pulse bounds | Implemented; physical envelope acceptance pending |
| Profiles / speed / acceleration | Z, A speed,accel | Commissioning default plus disarmed-only Gentle/Normal/Fast selection | Prepared 0.12.0, tested offline; flash and physical acceptance pending; see MOTION_PROFILES.md |
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

## Manual-control behavior

The previous 0.7.0 firmware stopped after 254 total pulses per arm. That was a
commissioning allowance, not a timer. Version 0.9.0 removes that cumulative
allowance from the main app: every click is independently bounded to 254 pulses
(~2 inches), but jogs can be repeated while armed and interlocks remain healthy.
No continuous movement, autorepeat, queued moves or automatic rearming is added.
The current manual mode also removes the restart Home-trip requirement; it
checks the real Home input level instead. An active limit still blocks motion,
and no homed coordinate is inferred from a clear input.

## Operator flow for the first main-app carriage acceptance

1. Keep saw mains unplugged, valve supply disconnected and air isolated. Keep
   suspect INA/MCP disconnected. Launch `python main.py`, select Teensy Carriage,
   choose the Teensy COM port and connect. Verify firmware 0.11.0 telemetry.
2. Check Home sensor is inactive (no trip/release sequence is required). Door closed, saw UP only,
   driver green ON/red OFF, alarm raw HIGH. Confirm isolation/driver checks.
3. Confirm driver setup. Wait for controller acknowledgment, then ARM MANUAL CONTROL.
   No motion occurs on either action.
4. Start at 0.1 in. A moves toward saw; B toward Home. Pulses are rounded to the
   nearest full step. View displacement and remaining pulses in that move. There is no cumulative
   travel allowance; completed jogs remain armed until an explicit stop or fault.
5. Verify STOP, door opening, alarm and communications-loss responses in
   controlled tests. No cancellation may resume automatically. ACK does not arm.
6. Release motor holding torque only when ready for a free carriage. This clears
   setup confirmation; a Home-sensor trip is not required. Position is always labeled commanded displacement.

## Next controller/app slice

User confirmed bounded Home success. Absolute targets, soft limits and load
presets are implemented in 0.11.0; follow [absolute positioning](ABSOLUTE_POSITIONING.md)
for the first short out-and-back test. The recovered 160.5-inch reference is at the slow
sensor latch; final pull-off is included in the displayed position. Accept
repeatability, physical reference and absolute positioning, then add acceleration/profiles. Alarm or driver release invalidates
referenced position and requires homing before future absolute moves.
See [remaining effort estimate](MIGRATION_EFFORT_ESTIMATE.md): roughly 12-24
engineering hours plus physical acceptance/hardware time for the core workflow.

After suppression is installed, validate individual air outputs with blade
unplugged, define clamp retention/release on faults, then migrate the cut-list
state machine to explicit controller completion/fault events. Hardware-only
acceptance is not replaced by the automated tests.
