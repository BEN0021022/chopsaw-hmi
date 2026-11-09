# Main app feature migration: MEGA to Teensy

Updated 2026-11-09. The active implementation is **custom controller 0.15.0**,
not stock grblHAL. The main app's **Teensy Carriage** mode owns one serial
connection, parses controller records on the Qt thread and applies a command
allowlist at the serial-write boundary. Sensor Bench remains a separate tool;
close it before opening the main app on the same COM port.

0.13.0 adds profiles and bounded board-edge/truing, tested offline, then flashed
and read back on COM4. The matching app is reopened with fresh compatible
telemetry, disarmed, no queued motion. New physical acceptance remains pending.

0.14.0 is now loaded with editable native pulse-rate/acceleration fields,
MEGA V2.5 default profiles and pulse-timing feedback. Actual parameter edits were
read back without motor enable or pulses; matching app reopened disarmed.
See SPEED_TUNING.md. The operator reported 0.13.0 tests good, including Fast;
that statement does not independently complete the physical fault matrix.

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
| Home | H, positive seek, home coordinate 160.5 in | Shared MANUAL/CARRIAGE XHOME and search limit; seek/release/backoff/slow latch/pull-off | User confirmed Home success; tab integration tested; repeatability/reference acceptance remains |
| Absolute length / load positions | S inches | XMOVE / XLOAD integer milliinches; known position + explicit arm | AUTO/CARRIAGE loads use stored FAST via XLOAD; same target/per-pulse limits; physical tab acceptance pending |
| Soft limits | Legacy target clamping | Firmware target-time and per-pulse bounds | Implemented; physical envelope acceptance pending |
| Profiles / speed / acceleration | Z, A speed,accel | XPROFILE id [rate accel], editable CARRIAGE and SETTINGS controls with acknowledged RAM settings | Active 0.14.0; MEGA defaults, 1-20000 pps / 1-50000 pps² editable ranges; higher-rate physical acceptance pending; see SPEED_TUNING.md |
| Board detection / truing | J / N, board-edge offset | XEDGE pulse bound/offset/overlap; XTRUING capture token | Prepared 0.13.0; detection disarms, separate explicit truing move; Home reference retained; geometry/physical acceptance pending |
| Door | Ad hoc/old hardware | Door/D29 active LOW, controller interlock | User confirmed input; firmware/app cancellation tested |
| Saw endpoints | Old SSEN | UP Limit Z/D22; DOWN Fd/Hld/D16 | User-confirmed inputs, controller interlocks |
| Main left clamp | C/D/L/U (legacy command collision) | OUT 1 / AUX1 TTL D32 | Bench LED proven; main app unavailable until diode/coil acceptance and clamp fault policy |
| Saw travel cylinder | Old saw cycle command | OUT 0 / AUX2 TTL D33 | OFF=UP confirmed; suppression and isolated pneumatic dry run pending |
| Blade trigger cylinder | Original trigger/brake mechanism | OUT 2 / Flood TTL D19 | Main app unavailable; validate OFF release/brake, no blade-powered test yet |
| Cut-list editing/import | Python UI | Same retained Python feature | Available; simulator regression passes |
| Automatic cut-list workflow | Old MEGA state strings + timed callbacks | New controller events / acknowledgments required | Locked on live Teensy; simulate only |
| Early return | Carriage return during cutting | Reassess collision/clamp/blade policy first | Locked on live hardware |
| Current monitoring | ACS712 fields | INA228 future work | Deferred; INA/MCP quarantined/disconnected |
| MEGA PID toggle | K0/K1 | Driver-managed closed loop | Removed from Manual UI in all modes; no duplicate HMI PID loop |
| Diagnostics / settings | Raw legacy console | Live raw records in SETTINGS; bounded command boundary | Legacy motion/output writes rejected in Carriage mode |

## Manual-control behavior

The November 9 UI cleanup retains Home, Motor Power Enabled and the existing
numeric keypad. The retired calibration, duplicate target/jog fields and Manual
speed/acceleration section are removed. Profiles remain in SETTINGS. Native
preparation/stop/fault controls still share CARRIAGE state. Checking Motor Power
uses the existing guarded arm request; unchecking uses XDISABLE and invalidates
Home. The checkbox reflects fresh ENA readback, not measured supply or torque.
Connect and telemetry refresh never enable or move the motor. Simulator enable/
release now stops its motion model and does not replay the cancelled target.
AUTO now also offers a **Keypad** checkbox beside Cut Length. With it enabled,
tapping the length selects the current value and opens a nonmodal keypad over
the left status column. It edits the same spin box; Add Cut to List appends the
length, leaves the keypad open and selects Cut Length for the next entry without
another tap. Back/Clear and Close keypad support touch
entry; closing leaves the preference enabled for the next tap. Disabling the
checkbox or leaving AUTO hides it. The preference persists, but the overlay
starts hidden after reopening. Physical keyboard entry works either way.
Invalid or empty input cannot append the previous length. Entry/list edits do
not send serial commands, even when the native carriage is armed.

Blade Kerf and Board Sensor Distance are now in SETTINGS under **Cutting and
Sensors**, using the same defaults, saved preference keys and consumers as
before. AUTO's **Cut Entry** card holds the enlarged length field, optional
keypad checkbox and Add Cut to List. The sensor/kerf move does not change native
controller geometry or apply any firmware settings automatically.

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
   choose the Teensy COM port and connect. The source requires matching
   0.15.0 telemetry; that firmware and matching app are now loaded.
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
repeatability, physical reference and absolute positioning, then accept the
prepared profiles and board-edge/truing path. Alarm or driver release invalidates
referenced position and requires homing before future absolute moves.
See [remaining effort estimate](MIGRATION_EFFORT_ESTIMATE.md): roughly 12-24
engineering hours plus physical acceptance/hardware time for the core workflow.

After suppression is installed, validate individual air outputs with blade
unplugged, define clamp retention/release on faults, then migrate the cut-list
state machine to explicit controller completion/fault events. Hardware-only
acceptance is not replaced by the automated tests.
