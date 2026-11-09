# Editable carriage rates - 0.14.0

Prepared 2026-11-08 after the operator reported 0.13.0 testing good, including
its fastest profile, and prioritized restoring MEGA-like cycle times. This
report does not complete the physical fault matrix or board-geometry acceptance.
Stable pre-tuning source is `8602038` (0.13.0).

0.14.0 is now flashed/read back on COM4, and the matching app is open with
fresh compatible telemetry, disarmed/unconfigured and no queued motion. A real
board edit to 1700/2200 was acknowledged without enabling or generating pulses;
Fast was restored to 2500/1500 and Commissioning selected before app reopening.
Physical acceptance of higher rates remains for the operator.

## Operator controls

On CARRIAGE, disarm, select Gentle/Normal/Fast, enter pulse rate and acceleration,
then click **Apply rate/profile (disarmed)**. Wait for the controller profile
readback, then arm and request a move. No new firmware is needed for subsequent
rate adjustments. Applying a profile neither enables the driver nor moves it.
Each editable profile has its own settings. Selecting it later restores its
controller-side RAM values. Commissioning remains fixed at 40 pulses/s.

Editable software ranges are **1-20,000 pulses/s** and **1-50,000 pulses/s²**,
matching the old HMI's adjustment ranges. These are software bounds, not
accepted mechanical operating limits. Values reset to defaults on controller
reboot; the app does not silently push old Windows settings back into hardware.
The setup/arm, Home reference and travel bounds remain in force.

Defaults are recovered from preserved MEGA V2.5 `initProfiles()`:

| Profile | Pulses/s | Acceleration, pulses/s² | Maximum equivalent in/s |
| --- | ---: | ---: | ---: |
| Commissioning | 40 | constant rate | 0.315 |
| Gentle | 150 | 200 | 1.180 |
| Normal | 1000 | 500 | 7.867 |
| Fast | 2500 | 1500 | 19.666 |

The prior HMI source defaults differed: Gentle 600/600, Normal 2500/900, Fast
3500/2500. Its saved Windows settings currently read 20,000/50,000 for all
three. That is not evidence that those rates were physically achieved on MEGA,
and they are not automatically restored. The operator can explicitly enter
the desired settings in the new native controls.

## Rates, ramp distance and feedback

The **SETTINGS** tab now exposes these same native profile values. Select the
profile to apply, edit its rate/acceleration and explicitly Apply while disarmed.
The active profile changes only on controller acknowledgment. Periodic telemetry
does not erase an unapplied edit; a readback label distinguishes controller values
from drafts. Changes made on CARRIAGE also appear in SETTINGS. Live Teensy RAM
values do not overwrite archived simulator profile settings in Windows.

**MANUAL** shares CARRIAGE's isolation/setup, arm, stop/release/ACK and bounded
Home state. Its Home search limit is synchronized with CARRIAGE; Home runs while
disarmed. Referenced Go and bounded +/-2-inch jogs reuse the native write guards.
Retired MEGA power/PID/calibration controls are hidden in live Teensy mode.
This tab integration changes the Python app only; firmware remains 0.14.0.

`inches/second = pulses/second / 127.12` at the confirmed full-step setting.
Acceleration is in pulses/s². The carriage ramps up and down within each move;
a short move may never reach the requested rate. At the recovered Fast settings,
about 32.8 inches total acceleration/deceleration travel is needed to reach
2500 pulses/s. A two-inch jog will therefore look slower than a longer absolute
move even at the same setting. No jog/search distance limit was enlarged.

The panel reports generated pulse count, peak pulse frequency and largest
scheduler delay for the last/current jog or absolute move. These are controller
timing measurements, not encoder speed or proof of physical following accuracy.
JOG_TIME_US spans first-to-last pulse and excludes the initial wait before the
first edge. Home and board-edge search retain their independent slow rates.

At higher rates, telemetry is skipped while armed if USB lacks room for a
complete record. This avoids waiting in normal telemetry writes when a host
stops reading. The existing heartbeat/freshness stop policies remain active.
The scheduler rebases each deadline on the actual rising edge, never catches
up with a pulse burst, and includes the five-microsecond HIGH time inside the
requested rising-edge period. It is a cooperative loop; actual rates/jitter on
the connected hardware remain to be observed.

## Electrical reference and validation limits

The [manufacturer's CL57T V4.0 manual](https://www.omc-stepperonline.com/download/CL57T_V4.0.pdf)
specifies up to 500kHz pulse input, at least 1µs HIGH/LOW and 2µs direction
setup. The photographed S1 selector/5-24V selector/ALM-BRK-COM arrangement
matches that manual's hardware family. The requested 20kHz software maximum,
5µs HIGH and at least 10µs direction setup fit those input timings. That
electrical comparison does not establish motor torque, travel safety or a
usable carriage speed. Keep the existing 200ms enable settling interval.

Native tests exercise exact pulse counts and timing caps with microsecond
resolution at the editable maximum, custom-profile parsing/bounds, disarmed-only
edits, reset defaults, cancellation, USB congestion and timer wrap. Actual
custom-profile serial output is replayed into the real Qt panel. Physical rate,
motion, stopping and following-alarm observations remain operator acceptance.
