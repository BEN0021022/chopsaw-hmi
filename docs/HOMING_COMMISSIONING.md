# Homing commissioning - controller 0.10.0

Implemented 2026-11-08. User subsequently reported the Home cycle succeeded;
repeatability and physical reference acceptance remain pending. Manual motion was reported
passed by the user on 0.9.0. The current custom firmware uses X_APP:CARRIAGE_V4,
HOMING:BOUNDED_V1, HOME_MAX:20594, HOME_REF:160.5 and scale 127.12 pulses/inch.

## First physical test

1. Keep saw mains unplugged, valve supply disconnected, air isolated and INA/MCP
   disconnected. Place carriage within two inches of Home using manual jogs;
   allow up to 1.35 inches of clearance away from the sensor for backoff.
2. Driver green ON, red OFF. Door closed, saw UP only. Confirm isolation/driver
   checks and Confirm driver setup. Do not ARM manual control for homing; if
   already armed for manual jogs, DISARM first.
3. Leave Maximum initial search at its default 2.00 inches. Click HOME CARRIAGE.
   This is the explicit motion command: no automatic start on connect or flash.
4. Watch SEEK -> RELEASE -> BACKOFF -> LATCH -> PULL_RELEASE -> PULL_OFF -> DONE.
   STOP / DISARM remains visible even when the content is scrolled.
5. Success disarms, leaves driver holding, reports referenced position and does
   not start any next move. Test repeatability before enabling absolute moves.

The search field can be increased up to 162 inches only with the full selected
path clear. Initial seek is 40 pulses/s (~0.315 in/s); slow latch is 10 pulses/s.
A full-length seek is therefore slow. Speeds/profiles are a later acceptance step.

## Sequence and bounds

- If Home is clear, seek B/DIR HIGH toward Home up to the selected raw pulse
  count. Pause pulse output immediately on assertion; require 20ms stable input.
- If already on Home, start with release instead of driving farther into it.
- Release A/DIR LOW until clear, up to 127 pulses (~1 inch), then back off
  another 32 pulses (~0.252 inch). Re-approach B slowly, at most 127 pulses.
- On the stable slow latch, establish the recovered legacy **160.5-inch sensor
  reference**. Release again, then pull off an additional 13 pulses (~0.102 inch).
- Final position is 160.5 + HOME_OFFSET / 127.12. Because it pulls clear, the
  finished position is slightly below 160.5, not exactly 160.5. This preserves
  the old sensor reference instead of silently shifting blade-length coordinates.
- Each seek/release is pulse-bounded and time-bounded. Overall maximum 10 minutes;
  a default two-inch test normally completes much sooner. Input settling at a
  pulse limit is allowed; no extra pulses are emitted beyond that limit.

## Position and faults

POS_STEPS remains commanded displacement since boot. POS_KNOWN becomes 1 only
after successful homing and pull-off; HOME_OFFSET is signed commanded steps
from the latched sensor reference. The main app displays the resulting homed
machine position and updates its homed/position signals. It is not encoder
telemetry. Calibration comes from recovered MEGA V2.5.

Home faults report HOME_FAILED plus HOME_ERROR: NOT_FOUND, LATCH_NOT_FOUND,
STUCK_ACTIVE, RETRIGGERED or TIMEOUT. Global driver alarm, door, missing/conflicting
saw position and heartbeat checks remain active throughout. STOP/disconnect cancels.
An interrupted or failed home leaves position unknown; a later fault, reboot or
motor release invalidates referenced position. ACK does not home or arm.

Manual motion retains no restart Home-trip ritual. Setup can be confirmed while
already on the sensor so actual homing can release it; ordinary manual ARM still
requires Home clear. There is no automatic homing on reboot/reconnect.

## Software validation

83 interlock policy + 87 archived-bench + 112 manual-controller + 209 homing
policy/real-sketch integration checks passed. New Qt tests cover bounded Home
requests, start on active sensor, expected sensor assertions during heartbeat,
exclusive motion, completion/invalidation and shared main-app position signals.
Layout inspected at 1280x900; dark scroll area and persistent STOP controls.
Arduino compile passed; flashed/read back 0.10.0 on COM4, disarmed, Home IDLE,
unknown position and zero queued steps. No HOME/arm/jog command sent by the agent.

Physical homing, reference repeatability, endpoint placement and collision limits
still require the operator's test. Absolute length moves and controller-side soft limits were subsequently
implemented in 0.11.0; see ABSOLUTE_POSITIONING.md for their acceptance test.
