# Controller protocol

Updated 2026-11-08. Active main-app controller firmware **0.14.0** uses the
existing LF-terminated ASCII BENCH records plus CARRIAGE_V8. 115200 baud,
63-character command maximum. No live MEGA commands or G-code are supported.
The Sensor Bench 0.6.0 sketch remains archived as a separate entry point.

0.13.0 was flashed/read back on COM4 and the matching app reopened after the
operator confirmed app closed and driver power OFF. Startup was disarmed,
unconfigured, unknown position, zero queued motion and profile 0. New physical
acceptance remains pending. Stable 0.11.0 / CARRIAGE_V5 is preserved at `cab3a16`.
Profiles originated in 0.12.0 / CARRIAGE_V6; 0.13.0 adds EDGE_SEARCH:BOUNDED_V1.

Flashed/read-back 0.14.0 changes identity to CARRIAGE_V8, MAX_RATE:20000,
MAX_ACCEL:50000, PROFILES:EDITABLE_V1. It adds optional `XPROFILE id rate accel`
(id 1-3, disarmed only; RAM values), retains `XPROFILE id` selection, and reports
PROFILE_RATE0..3/PROFILE_ACCEL0..3 plus JOG_PULSES/JOG_TIME_US/JOG_PEAK_PPS/JOG_LATE_US.
Readbacks must match the selected profile's stored values. Profile 0 is immutable
40/0. See [speed tuning](SPEED_TUNING.md). Startup and an actual rate edit were
read back disarmed with no generated/queued pulses; the matching app is reopened.

## Identity

Main-app motion requires all of:

```
PROTO:2,BOARD:TEENSY41,MAP:T41U5XBB_V2_20
X_APP:CARRIAGE_V8,X_TEST:MANUAL_JOG_V1,X_MAP:STEP2_DIR3_EN40
INPUT_MAP:DOOR29_UP22_DOWN16,OUTPUT_MAP:AUX2_AUX1_FLOOD
INTERLOCKS:DOOR_POSITION_V1,COMMISSIONING:VALVES_ISOLATED,CAL_SPI:127.12
MAX_JOG:254,BASE_RATE:40,MAX_RATE:20000,MAX_ACCEL:50000,PROFILES:EDITABLE_V1,HOME_CHECK:LEVEL_ONLY
HOMING:BOUNDED_V1,HOME_MAX:20594,HOME_REF:160.5
ABSOLUTE:REFERENCED_V1,MAX_MOVE:20594,EDGE_SEARCH:BOUNDED_V1
```

Active firmware version is 0.14.0. Reads HELLO, PINMAP and STATUS are sent on
connection. Connect, identity matching, RESET and reconnect never arm/enable.
The main app rejects motion if identity differs or motion/safety telemetry
is older than two seconds. Firmware is authoritative if the PC stops responding.

## Main-app commands

| Command | Meaning |
|---|---|
| HELLO / PINMAP / STATUS / PING | Read identity, assignments or telemetry |
| XCONFIG 0 1 | Store verified enabled-LOW and healthy-alarm-HIGH profile in RAM; requires healthy alarm, door closed and saw UP; no trip/release prerequisite; Home may be active for homing |
| XARM 1 | Arm manual Stepper mode, set verified ENA; no STEP emitted; requires fresh ready state |
| XJOG -1 n / XJOG 1 n | Queue one bounded jog, 1-254 pulses per click; A/-1/LOW toward saw, B/+1/HIGH toward Home |
| XHOME n | Explicitly arm/start bounded homing; initial search 1-20594 pulses, main UI default 254 (~2 in); must be disarmed/configured; Home may start active |
| XMOVE n | Absolute target in integer milliinches; requires Home-valid position, explicit arm, clear Home and idle motion; firmware soft limits apply |
| XPROFILE n | Select profile 0-3 while disarmed/idle; RAM-only, no enable or motion; rates below |
| XPROFILE id rate accel | Edit/select profile 1-3 while disarmed/idle; 1-20000 pps, 1-50000 pps²; RAM-only; no enable/motion |
| XEDGE pulses offset trim | Search toward saw at 40 pulses/s; 1-20594 pulses, offset/trim 0-160500 milliinches; requires known Home, armed/settled/idle, sensor initially clear and entire search inside soft limits |
| XTRUING capture | Separate explicit absolute move to captured proposal; requires current valid capture MOVE_ID and edge still active, plus normal armed/idle absolute guards; consumes capture |
| KEEPALIVE | Refresh the 1.5-second controller watchdog while armed |
| OFF / XARM 0 | Cancel all remaining pulses, turn pneumatic outputs OFF, disarm; retains motor holding level |
| XDISABLE | Stop/disarm then ENA HIGH; clears setup; no Home-trip requirement or inferred position |
| RESET | Acknowledge a latched fault only when safe/disarmed; does not arm |

Controller pulse service is nonblocking with no catch-up bursts. Direction setup
at least 10us, STEP HIGH 5us, minimum 200ms after enable. The next pulse deadline
is retained between jogs, preventing rapid clicks from bypassing the timing cap.
Requests during motion are rejected, never queued/reversed.
Completed jogs remain armed, with no cumulative travel allowance. All raw counts are STEP pulses, not encoder
counts. The main app rounds requested inches to nearest pulse at 127.12/inch.

Profile 0 defaults to the proven constant 40 pulses/s. Profiles 1/2/3 default to
maximums 150/1000/2500 pulses/s and accelerations 200/500/1500 pulses/s²,
respectively, recovered from MEGA V2.5; they are editable within the above ranges.
Ramped motion is symmetric and distance limited. Homing and board acquisition
keep their independent fixed rates. See [profile plan](MOTION_PROFILES.md).
Current operator controls and tuning guidance: [speed tuning](SPEED_TUNING.md).

The controller retains diagnostic XLEVEL, XSTEP and pneumatic ARM/OUT commands
for Sensor Bench, but the main app's serial-write boundary rejects them.
Stock grblHAL commands and legacy S/M/H/C/V/K commands are blocked in this mode.

## Telemetry

```
BENCH_X,ARMED:0,CONFIGURED:0,READY:0,HOME_VERIFIED:0,HOME_RAW:1,ALARM_RAW:1,STEP:0,DIR:0,ENA:1,MAX_JOG:254,PROFILE_ID:0,RATE_PPS:40,ACCEL_PPS2:0,PROFILE_RATE0:40,PROFILE_ACCEL0:0,PROFILE_RATE1:150,PROFILE_ACCEL1:200,PROFILE_RATE2:1000,PROFILE_ACCEL2:500,PROFILE_RATE3:2500,PROFILE_ACCEL3:1500,JOG_PULSES:0,JOG_TIME_US:0,JOG_PEAK_PPS:0,JOG_LATE_US:0,JOG_READY:0,REMAINING:0,POS_STEPS:0,POS_KNOWN:0,HOME_OFFSET:0,HOME_REF:160.5,HOME_STATE:IDLE,HOME_ERROR:NONE,SOFT_MIN_OFFSET:-20402,SOFT_MAX_OFFSET:0,SOFT_MAX_MILLI:160500,TARGET_OFFSET:0,MAX_MOVE:20594,MOVE_KIND:IDLE,EDGE_STATE:IDLE,EDGE_ERROR:NONE,EDGE_VALID:0,EDGE_MILLI:0,TRUING_MILLI:0,SENSOR_OFFSET_MILLI:10800,TRIM_MILLI:250,CAL_SPI:127.12,MOVE_ID:0,UP_MS:1234,FAULT:NONE
BENCH_SAFETY,DOOR_CLOSED:1,SAW_POSITION:UP,READY:1,RESET_READY:1,FAULT:NONE,BLOCKER:NONE
BENCH_INPUTS,SEQ:42,HOME:1,BOARD_EDGE:1,FENCE_DOOR:0,CL57T_ALM:1,SAW_UP:0,SAW_DOWN:1,FENCE_CLOSED:0,OUTFEED:1
```

- X, safety and direct inputs publish every 200ms and on relevant commands/faults.
- POS_STEPS is signed commanded displacement since boot: positive toward Home.
  POS_KNOWN becomes 1 only after completed bounded Home and pull-off. Machine
  position is HOME_REF (160.5 inches) + HOME_OFFSET / 127.12; offset zero is
  the slow-latched sensor reference. It becomes unknown on faults/release/reboot.
- MOVE_ID increments only on accepted motion commands, allowing the HMI to
  distinguish acknowledgment from stale pre-command telemetry. A missing move
  acknowledgment after one second causes OFF and a local fault.
- REMAINING is the active move's unsent pulses/search allowance. MAX_JOG is the
  manual increment maximum (254); RATE_PPS is the selected profile's maximum,
  not instantaneous speed. PROFILE_ID/ACCEL_PPS2 are acknowledged settings.
  PROFILE_RATE0..3/PROFILE_ACCEL0..3 report all controller-side profile values.
  JOG_PULSES/JOG_TIME_US/JOG_PEAK_PPS/JOG_LATE_US report pulse-generation count,
  first-to-last edge duration, peak frequency and maximum deadline lateness for
  the last/current jog or absolute move; these are not encoder measurements.
  JOG_READY becomes 1 when armed in Stepper mode and the 200ms
  enable interval has passed. These are not machine-coordinate soft limits.
- The old 0.7.0 aggregate BUDGET field is removed. A completed manual jog does
  not disarm; no movement occurs until the next explicit click. Faults, STOP
  and the firmware heartbeat watchdog still disarm and cancel all remaining pulses.
- A controller uptime decrease revokes main-app consent. Boot clears all setup.
- HOME_CHECK:LEVEL_ONLY means manual setup/arm does not depend on HOME_VERIFIED.
  The historical transition flag may still be reported for diagnostics. Home
  must be clear for manual ARM/jogs. In homing mode assertions/releases are
  expected and handled by the bounded sequence; global safety checks remain active.
  Neither state establishes a homed machine position.
- Inputs are raw levels, active LOW for the assigned switches; driver alarm
  raw HIGH is the physically verified healthy state. This wiring cannot detect
  every broken wire and is not a safety-rated guard or E-stop system.
- INA/MCP health may still be published for diagnostics, but those modules are
  disconnected/quarantined and do not gate carriage operation or supply current data.

## Faults and stop policy

Driver alarm, Home activation while armed, door opening, loss of UP, conflicting
saw positions, invalid control commands and watchdog timeout cancel remaining
pulses and latch the first fault. There is no automatic restart or resume.
Pneumatic and Stepper modes are mutually exclusive. Stop retains ENA; release
motor holding torque is an explicit separate action, not a safety disconnect.
Do not infer a safe mechanical result on power/air loss from these software flags.

Pneumatic testing additionally enforces one output at a time, 5s maximum ON,
and down/return timeouts. RESET never clears an unsafe condition or arms.
Suppression, fusing, guarding and independent hazardous-energy controls remain
hardware requirements. No pneumatic or blade ON is exposed by the main app yet.

## Bounded homing extension

HOME_STATE is IDLE, SEEK, RELEASE, BACKOFF, LATCH, PULL_RELEASE, PULL_OFF,
DONE, FAILED or CANCELLED. Homing publishes ARMED=1 but JOG_READY=0; the app
keeps heartbeat alive during expected Home assertions and blocks manual jogs.
Initial seek and release run at 40 pulses/s; slow latch at 10. A successful
cycle publishes POS_KNOWN=1 then disarms. No automatic next move or rearm.
HOME_ERROR distinguishes NOT_FOUND, LATCH_NOT_FOUND, STUCK_ACTIVE, RETRIGGERED,
TIMEOUT and cancellation. Global faults remain in FAULT; failed homing uses
HOME_FAILED. See [homing commissioning](HOMING_COMMISSIONING.md) for all bounds.

## Referenced positioning extension (0.11.0)

ABSOLUTE:REFERENCED_V1 / CARRIAGE_V5 permits XMOVE integer milliinches.
SOFT_MIN_OFFSET is -20402, SOFT_MAX_OFFSET is captured at Home completion;
SOFT_MAX_MILLI is the corresponding nonnegative upper target. TARGET_OFFSET
tracks the accepted full-step target. MOVE_KIND is IDLE, JOG, ABSOLUTE or EDGE.
MAX_MOVE=20594 allows full-range remaining counts; MAX_JOG=254 applies only to
manual increments. Referenced jogs and single-step diagnostics obey soft limits.
Firmware guards at command acceptance and before each emitted pulse. Normal
out-of-range requests are rejected, never clamped into a different distant move;
zero rounds to the first nonnegative full step. Per-pulse violation latches
SOFT_LIMIT and invalidates position. No absolute move can establish position.

## Board-edge extension (prepared 0.13.0)

EDGE_STATE is IDLE, SEEK, FOUND, FAILED or CANCELLED. During SEEK the record
has MOVE_KIND:EDGE, ARMED:1, JOG_READY:0 and known position. Raw active LOW
pauses immediately; 20ms stable detection captures EDGE_MILLI, calculates
TRUING_MILLI = EDGE_MILLI - SENSOR_OFFSET_MILLI + TRIM_MILLI, and disarms.
EDGE_VALID:1 means the proposal fits the soft limits. Detection never re-zeros,
advances, clamps or cuts. A separate XTRUING command names the capture's MOVE_ID.

Any accepted move, STOP, release, fault, new Home, reboot or cleared edge sensor
expires that capture. A missing edge at the exact pulse budget fails after a
45ms settling allowance; total acquisition time is also bounded by
pulses × 25ms + 2000ms. EDGE_FAILED latches and invalidates the position.
EDGE_ERROR distinguishes NOT_FOUND, TIMEOUT and TARGET_OUT_OF_RANGE. An
out-of-range proposal after successful detection remains disarmed with Home
position retained, but EDGE_VALID:0. See [edge plan](BOARD_EDGE_COMMISSIONING.md).
