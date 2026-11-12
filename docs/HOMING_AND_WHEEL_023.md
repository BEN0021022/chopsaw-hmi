# Homing settings and wheel protection — 0.23

Prepared offline, 2026-11-12. The wheel/UI update works immediately after an
app restart. Adjustable controller homing requires the accompanying **0.23.0 /
CARRIAGE_V17** firmware; existing 0.22 firmware remains supported for all prior
features and retains its fixed Home speed until flashed.

## Settings

**Settings → Homing approach — Teensy** provides approach speed (pulses/second),
acceleration (pulses/second squared), Save/apply and controller readback. Defaults
are 40 pulses/s and 200 pulses/s². These are separate from Gentle/Normal/Fast.
Saved preferences persist on the PC. Saving while disconnected moves nothing;
when idle on supported firmware, Save/apply transfers settings and waits for
readback. A normal Home gesture also loads saved values before issuing Home.
Unacknowledged settings never start a Home move. Connecting never applies a
profile, arms the motor or homes automatically. Editing an unsaved draft does
not change the saved settings or overwrite live controller readback.

The configurable rate/acceleration govern the Home **approach/seek**. Release,
backoff and pull-off remain capped at 40 pulses/s and the final slow latch at
10 pulses/s, preserving sensor repeatability. Each phase restarts its ramp;
raw sensor detection immediately pauses pulses. Direction setup, enable settling,
search bounds, interlocks, watchdog, failed-sensor stops, 160.5-inch datum and
127.12-pulse/in calibration remain. Phase deadlines account for acceleration;
the existing overall ten-minute Home limit remains.

Controller command: `XHOMEPROFILE <rate> <acceleration>`, configuration only,
accepted stationary/disarmed. Bounds match motion tuning: 1–20000 pulses/s,
1–50000 pulses/s². Invalid or active-motion requests are rejected. Homing tuning
is RAM on the Teensy; the PC reloads saved preferences on the next explicit Home.
New fields `HOME_RATE_PPS` and `HOME_ACCEL_PPS2` acknowledge configuration.

On 0.22, the app displays a fixed-speed/firmware-update notice. It does not send
unsupported commands or claim that saved rates are active. The earlier Auto,
Semi-Auto and pause/resume functionality remains compatible.

## Wheel policy

An application-wide event filter protects spin boxes (including integer,
decimal and date/time editors), combo boxes, sliders/dials and mode tab bars.
Wheel input cannot change their values, whether focused, unfocused, nested or
created later in a dialog. Sensor Bench installs the same policy.

Wheel input over a protected control scrolls its enclosing panel instead.
Ordinary scrollbars and open dropdown lists still scroll; choosing an item
requires a click/keyboard action. Typing, keyboard arrows, touch keypad input,
spin buttons and intentional tab clicks remain available. The filter is removed
before QApplication teardown.

## Validation and deployment

The actual-sketch/Qt tests check saved settings → profile ACK → exactly one Home,
idle Apply without motion, unchanged motion profiles, 0.22 compatibility, and
lost ACK cancelling Home. C++ tests exercise ramped high-speed approach, slow
latch/release, acceleration-aware deadlines, invalid values, and mid-motion
configuration rejection, alongside the existing Home/interlock regressions.
Qt wheel tests check focused/unfocused/nested/new controls, popup scrolling,
panel navigation and deliberate keyboard edits.

The Teensy 4.1 firmware is compiled under `tmp/commissioning/0.23.0/firmware`.
Source, hashes and validation records are preserved alongside it. Physical
flashing and homing acceptance are pending until the board is connected with
driver/valve power off, air isolated and saw unplugged. No physical motion is
initiated by the agent for validation.
