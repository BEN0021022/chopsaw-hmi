# Historical commissioning profiles - 0.12.0/0.13.0

Active controller/app **0.14.0** now provides editable rate/acceleration with
MEGA defaults. Use [speed tuning](SPEED_TUNING.md) for current controls, limits
and defaults. The table and acceptance sequence below preserve the initial
commissioning profile history; they are not the active 0.14.0 speed limits.

Prepared offline on 2026-11-08 as 0.12.0, checkpoint `dd333ce`; also included in
0.13.0. That build is now flashed/read back on COM4 with the matching app
reopened. Physical profile acceptance is pending. Keep 0.11.0 checkpoint
`cab3a16` for rollback.

| Profile | Maximum pulses/s | Acceleration, pulses/s² | Approximate maximum in/s |
| --- | ---: | ---: | ---: |
| Commissioning (default) | 40 | Constant rate | 0.315 |
| Gentle | 40 | 40 | 0.315 |
| Normal | 80 | 160 | 0.629 |
| Fast | 127 | 254 | 0.999 |

These are initial commissioning limits, not recovered MEGA production speeds.
Every reboot selects Commissioning. Profile selection is RAM-only, requires
disarmed motion, and neither enables the motor nor starts a move. The app shows
the controller's acknowledged selection, not an assumed successful write.
Legacy editable speed/acceleration fields are disabled in Teensy mode.

Ramped jogs and absolute moves use a symmetric discrete trapezoid, limited by
both distance from the beginning and distance to the end. Short moves may never
reach the selected maximum. Homing retains its independent 40-pulses/s search
and 10-pulses/s latch. The main app keeps the existing stop, telemetry freshness,
driver/door/saw checks, referenced travel limits and heartbeat requirements.
The scheduler emits at most one pulse per service pass and never catches up
with a burst after a delayed loop. STOP cancels without a commanded deceleration
tail; it does not start a return move.

## Acceptance on return

1. Close the app and switch driver power off before loading the matching app and
   controller build. Keep saw mains unplugged, valve power disconnected and air
   isolated.
2. Read back the matching prepared build (currently 0.13.0 / CARRIAGE_V7) and confirm the default Commissioning profile,
   disarmed state and zero queued motion. Reconfirm driver setup and Home.
3. Accept a short absolute out-and-back at Commissioning speed first. Then
   disarm, apply Gentle and confirm its acknowledged rates before arming again.
4. Accept short moves, direction changes, stopping and fault responses for each
   additional profile before increasing distance. A profile passing software
   tests does not establish the physical collision envelope or stopping outcome.

## Software evidence

Native tests exercise the real sketch against mocked GPIO, serial and time.
The profile suite checks all four curves, timing caps, exact pulse counts,
repeat moves, disarmed-only selection, cancellation and delayed-loop behavior.
Main-app tests check profile acknowledgments, legacy profile routing, write
boundaries and rejection of inconsistent rate/profile telemetry. The matching
Teensy 4.1 sketch compiles with Arduino CLI. No hardware motion is sent by these
tests.
