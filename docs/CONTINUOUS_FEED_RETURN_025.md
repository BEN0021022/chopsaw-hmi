# Continuous acquisition and operator cut during return — 0.25

Prepared 2026-11-16; firmware **0.25.0 / CARRIAGE_V18**. Existing 0.24 and earlier
protocols remain supported by the app; the new behavior needs this firmware.
Scope remains saw-mains-unplugged commissioning, not proof of grip or powered-cut
acceptance. Second clamp stays disabled unless separately commissioned/enabled.

## One continuous Gentle acquisition/truing move

Auto uses `XACQUIRE <search-pulses> <sensor-milli> <trim-milli>`. It reserves
physical travel for the sensor distance plus trim/kerf before starting. Motion
stays in stored Gentle from contact/search through truing. The first raw sensor
edge captures the existing machine coordinate while pulses continue. Twenty
milliseconds of stable detection qualifies that edge without pausing the motor;
the truing target is raw-edge position minus sensor distance minus kerf.

The controller retargets the same pulse schedule/ramp, preserving current speed
and acceleration, and decelerates only at the final truing target. It does not
disarm/re-enable, wait for a PC command or reset position at the sensor. Bounce
returns to the bounded search; an unqualified edge beyond that bound fails rather
than extending search indefinitely. No detection, invalid target, soft limit,
Stop, guard/alarm or watchdog stops motion. All pneumatic outputs remain OFF.

Telemetry retains the qualified raw edge and truing target. The material adapter
accounts for travel that occurred during qualification/telemetry latency. At the
final target the app reviews detector/model agreement, next-cut capacity and the
holding plan before requesting any stroke. Diagnostic `XEDGE` is unchanged and
still stops on detection; old firmware uses its earlier stop/rearm sequence.

## Operator cut during a Fast early return

The button lights before return and becomes pressable during the authorized
return. One press starts the clamp-inhibited operator stroke immediately; it
does not wait for Home/Load. Carriage return and stroke may finish in either
order. Cut-list advancement/new-board continuation waits for **both** to finish.

This is a dedicated return-only path, not a generic simultaneous-motion override:

- `XRETURN <load-milli> <minimum-cut-clearance-milli>` requires a homed/configured
  carriage, clear detector, released clamps, saw UP, healthy guard/alarm and a
  target strictly toward Home. The starting pusher position must be beyond the
  host's measured blade/pusher keepout. It uses stored Fast and binds permission
  to this accepted move ID, start, minimum and target coordinates.
- `DRETURN <timing-config-id> <next-request-id> <return-move-id>` consumes that
  permission once, only during the positive-direction return. Actual position,
  direction, clear detector, current config/request and raw guard/UP/alarm are
  checked again on the controller. Both clamps remain OFF for this stroke.
- Only this token-bound, away-from-blade move permits saw travel while stepping.
  Generic forward/reverse motion, clamp changes and repeated cut requests are
  blocked. Normal carriage motion still requires saw UP.
- Reaching Load disarms carriage motion without stopping an unfinished stroke.
  Conversely, an early DONE does not stop/reverse/restart the unfinished return.
- Stop/Cancel, guard opening, driver alarm, conflicting endpoints, detector
  blockage, lost heartbeat, saw travel timeout or motion failure stops both
  activities and revokes permission. No click/replay is retained after failure.
- If the operator waits until the carriage has returned, the existing stationary
  operator-cut path remains available. Resume/Pause retains explicit sequence
  ownership; routine Pause finishes the active stroke/return before advancing,
  while Cancel/STOP interrupts immediately.

New capabilities: `FEED:CONTINUOUS_ACQUIRE_V1` and
`PARALLEL_RETURN:UNPLUGGED_OPERATOR_V1`. X readback adds ACQUIRE_CONTINUOUS,
RETURN_PERMIT, RETURN_USED, RETURN_START, RETURN_MIN and RETURN_AT_LOAD. The app
rejects missing/contradictory return telemetry and never grants the concurrency
path to old firmware. Clamp timing/protocol and saved speed defaults are unchanged.

Validation uses the actual firmware sketch with simulated GPIO/time, including
continued pulses during edge qualification, precise target, bounce, no valves
while acquiring, overlapping saw/return pulses, wrong/repeated tokens, retained
clamp exclusion and cross-stop faults. Qt end-to-end tests cover immediate button
acceptance during return, late stationary approval, once-only history, waiting
for both activities, acquisition, multi-board, pause/resume and legacy features.
Physical operator acceptance is still required after flashing.

Regression note: two full-suite attempts on Windows CPython 3.13.5 terminated
inside the interpreter with `Executing a cache`, at the input-validity generator
in `safe_link`. Isolated cases passed. That fixed three-input predicate now uses
explicit equivalent comparisons, removing the generator allocation from this
frequent callback. This is a localized mitigation; the native crash's root cause
has not been established. Original failing logs are retained in the deployment
archive alongside the subsequent regression result.
