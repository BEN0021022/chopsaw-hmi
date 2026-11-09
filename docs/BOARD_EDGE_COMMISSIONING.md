# Board-edge search and truing - prepared 0.13.0

Prepared and tested offline on 2026-11-08, then flashed/read back as 0.13.0 on
COM4. The matching app is reopened; physical acceptance is pending. The app
requires CARRIAGE_V7 and the matching controller before it permits motion.

## What the new path does

1. Complete Home, confirm isolation/driver setup, then explicitly arm carriage
   motion. The Banner NPN sensor must initially be clear on Limit Y/D21.
2. Select a maximum search distance. Default is two inches. The entire selected
   search must fit the homed software limits. Start near the expected edge; do
   not increase the search until the path and stock handling are accepted.
3. FIND BOARD EDGE travels A/toward the saw at a fixed 40 pulses/s, independent
   of the selected motion profile. Detection immediately pauses pulses. A
   stable 20ms assertion captures the current homed coordinate.
4. Detection stops and disarms, retaining motor holding torque. It does not
   energize a valve, cut, re-zero the carriage or automatically advance.
5. Inspect the captured edge, offset and proposed truing position. Rearm and
   explicitly choose MOVE TO CAPTURED TRUING POSITION for that separate move.
   This uses the selected motion profile and normal absolute-move guards.

Recovered default geometry is:

`proposed truing position = detected carriage position - 10.800 in + 0.250 in`

The 10.8-inch sensor offset and 0.25-inch overlap come from the old software.
They require physical acceptance on the rebuilt machine. They are neither
measured blade clearance nor proof of a safe collision envelope. A proposal
outside the homed software range is displayed as invalid and cannot be used.

The old `N` calibration rewrote carriage coordinates at the board sensor.
That behavior is deliberately deferred; the new acquisition preserves Home as
the sole position reference. Board-edge acquisition is not stock-length
measurement or confirmation of clamping. Air and blade actions remain unavailable.

## Capture lifetime and failure behavior

- A capture is identified by the accepted motion's MOVE_ID. XTRUING must name
  that capture. No new capture or stale token can silently substitute a target.
- Clearing the edge sensor, another accepted move, a new Home, STOP, release,
  fault or reboot invalidates the proposal. Editing offset fields applies to
  the next search; the result always displays the geometry actually captured.
- A sensor active before starting is rejected without motion. No automatic
  backoff or interpretation of an already-covered sensor is attempted.
- Missing detection fails after the exact pulse budget plus a 45ms final-input
  settling allowance. Bouncing/obstructed progress is additionally bounded by
  search pulses × 25ms + two seconds. EDGE_FAILED cancels, disarms and invalidates
  position; correct the cause, acknowledge and rehome.
- Door, saw-UP/conflicting endpoints, Home limit, driver alarm, heartbeat loss
  and per-pulse soft limits remain active throughout. Nothing resumes automatically.

## Physical acceptance still required

Keep saw mains unplugged, valve power disconnected and air isolated for these
carriage-only tests. Accept short absolute motion before adding a board search.
Check sensor clear/active behavior while stationary, short bounded detection,
STOP, missing-edge failure, the proposed geometry and explicit separate truing
move. Validate stock support and the whole path first. Record the operator's
observations in the migration checklist; passing mock tests is not this acceptance.

Software evidence includes the real C++ sketch with mocked hardware, Qt app
command boundaries, and replay of actual sketch-generated serial records into
the real panel. Frozen Sensor Bench and legacy simulator tests remain separate.
