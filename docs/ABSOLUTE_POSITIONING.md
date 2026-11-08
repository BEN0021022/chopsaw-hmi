# Absolute positioning and load presets - 0.11.0

Implemented 2026-11-08, after the user reported Home success. Software/native
acceptance completed; new absolute/load hardware acceptance remains pending.

## Operator check

Keep saw mains unplugged, valve 12V disconnected, air isolated and INA/MCP
quarantined. Firmware updates clear referenced position, so Home again first.
Confirm driver/setup checks, complete HOME CARRIAGE, then ARM MANUAL CONTROL.
The absolute target initially defaults to the current pulled-off position.

For the first check, select a target about 0.1 inch below the displayed homed
position and press GO TO POSITION. It should move A/toward the saw. Use the
Home/load preset and MOVE TO LOAD POSITION to return B/toward Home, stopping at
the pull-off point rather than on the sensor. Test STOP before longer moves.

The old presets are retained: 10ft stock -> 135in, 8ft -> 111in, 6ft -> 87in,
4ft -> 63in. Home/load uses the actual current Home pull-off upper limit, not
160.5in on the sensor. Every preset uses the same guarded absolute-move path.

## Limits and coordinates

- Recovered scale 127.12 pulses/inch. Sensor datum 160.5in at slow Home latch.
- Firmware tracks integer HOME_OFFSET from that datum. Position is commanded
  pulse count with CL57T alarm supervision, not a streamed encoder measurement.
- Lower software boundary is 0in, inherited from the old HMI's target range.
  This is not independent proof of the physical collision-free lower endpoint;
  physical envelope/reference acceptance remains on the checklist.
- Upper boundary is captured at the final successful Home pull-off position.
  Referenced jogs obey these same limits. No software request can intentionally
  drive back onto the Home sensor; the physical input remains an independent
  controller stop condition for normal motion.
- Targets round to whole motor pulses. At this scale one pulse is ~0.00787in.
  A requested zero selects the first representable nonnegative position (~0.006in),
  instead of crossing below zero due to rounding. The readout shows actual
  counted position, so it can differ slightly from the requested decimal target.
- Both request-time and per-pulse guards run on the controller. A rejected
  out-of-range request emits X_SOFT_LIMIT; an unexpected per-pulse violation
  latches SOFT_LIMIT, cancels movement and invalidates position.
- A fault, reboot, motor release or failed/interrupted Home invalidates position.
  RESET cannot establish a reference. Absolute/load controls remain unavailable
  until a successful Home cycle establishes a valid coordinate.

## Motion behavior

Absolute moves can span the referenced range, unlike the two-inch manual jog cap.
They currently use the same conservative 40 pulses/s (~0.315in/s). Long moves
are slow until acceleration/profile acceptance. Confirm the entire path is clear.
One active move only; replacement commands are rejected. No automatic resume.
STOP/disarm cancels remaining steps. A normal counted stop retains the held
reference; protection faults invalidate it. Firmware heartbeat and all door,
saw-position, driver-alarm and Home protections remain active throughout.

Protocol: XMOVE <nonnegative integer milliinches>, for example XMOVE 135000.
Requires CARRIAGE_V5 / ABSOLUTE:REFERENCED_V1, referenced position and armed mode.
Telemetry adds SOFT_MIN_OFFSET, SOFT_MAX_OFFSET, SOFT_MAX_MILLI, TARGET_OFFSET,
MAX_MOVE:20594 and MOVE_KIND (IDLE/JOG/ABSOLUTE). MAX_JOG remains 254.

Validation: 113 new actual-sketch/conversion checks passed, including round trips,
all stock presets, full referenced travel, rounding/edge rejection, per-pulse
limit enforcement, queue rejection, every stop/fault path and no motion before
Home. Existing manual and Home suites and main-app Qt integration pass. New app
tests cover presets, acknowledgment, no optimistic position change, long moves,
Home/fault gating and shared main-app command routing. Arduino compile passed.
0.11.0 flashed/read back on COM4 disarmed, unconfigured, unknown position and no
pending move. No physical motion command was issued by the agent.
