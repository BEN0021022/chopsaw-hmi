# Controller protocol

Updated 2026-11-08. Current main-app controller firmware **0.9.0** uses the
existing LF-terminated ASCII BENCH records plus CARRIAGE_V3. 115200 baud,
63-character command maximum. No live MEGA commands or G-code are supported.
The Sensor Bench 0.6.0 sketch remains archived as a separate entry point.

## Identity

Main-app motion requires all of:

```
PROTO:2,BOARD:TEENSY41,MAP:T41U5XBB_V2_20
X_APP:CARRIAGE_V3,X_TEST:MANUAL_JOG_V1,X_MAP:STEP2_DIR3_EN40
INPUT_MAP:DOOR29_UP22_DOWN16,OUTPUT_MAP:AUX2_AUX1_FLOOD
INTERLOCKS:DOOR_POSITION_V1,COMMISSIONING:VALVES_ISOLATED,CAL_SPI:127.12,MAX_JOG:254,RATE_PPS:40,HOME_CHECK:LEVEL_ONLY
```

Firmware version is currently 0.9.0. Reads HELLO, PINMAP and STATUS are sent on
connection. Connect, identity matching, RESET and reconnect never arm/enable.
The main app rejects motion if identity differs or motion/safety telemetry
is older than two seconds. Firmware is authoritative if the PC stops responding.

## Main-app commands

| Command | Meaning |
|---|---|
| HELLO / PINMAP / STATUS / PING | Read identity, assignments or telemetry |
| XCONFIG 0 1 | Store verified enabled-LOW and healthy-alarm-HIGH profile in RAM; requires Home inactive, healthy alarm, door closed and saw UP; no trip/release prerequisite |
| XARM 1 | Arm manual Stepper mode, set verified ENA; no STEP emitted; requires fresh ready state |
| XJOG -1 n / XJOG 1 n | Queue one bounded jog, 1-254 pulses per click; A/-1/LOW toward saw, B/+1/HIGH toward Home |
| KEEPALIVE | Refresh the 1.5-second controller watchdog while armed |
| OFF / XARM 0 | Cancel all remaining pulses, turn pneumatic outputs OFF, disarm; retains motor holding level |
| XDISABLE | Stop/disarm then ENA HIGH; clears setup; no Home-trip requirement or inferred position |
| RESET | Acknowledge a latched fault only when safe/disarmed; does not arm |

Controller pulse service is nonblocking, at most 40 pulses/s, no catch-up
bursts. Direction setup at least 10us, STEP HIGH 5us, minimum 200ms after enable. The next pulse deadline is retained between jogs
so rapid clicks cannot bypass the 40 pulses/s maximum. Requests during a jog are rejected, never queued/reversed.
Completed jogs remain armed, with no cumulative travel allowance. All raw counts are STEP pulses, not encoder
counts. The main app rounds requested inches to nearest pulse at 127.12/inch.

The controller retains diagnostic XLEVEL, XSTEP and pneumatic ARM/OUT commands
for Sensor Bench, but the main app's serial-write boundary rejects them.
Stock grblHAL commands and legacy S/M/H/C/V/K commands are blocked in this mode.

## Telemetry

```
BENCH_X,ARMED:0,CONFIGURED:0,READY:0,HOME_VERIFIED:0,HOME_RAW:1,ALARM_RAW:1,STEP:0,DIR:0,ENA:1,MAX_JOG:254,RATE_PPS:40,JOG_READY:0,REMAINING:0,POS_STEPS:0,POS_KNOWN:0,CAL_SPI:127.12,MOVE_ID:0,UP_MS:1234,FAULT:NONE
BENCH_SAFETY,DOOR_CLOSED:1,SAW_POSITION:UP,READY:1,RESET_READY:1,FAULT:NONE,BLOCKER:NONE
BENCH_INPUTS,SEQ:42,HOME:1,BOARD_EDGE:1,FENCE_DOOR:0,CL57T_ALM:1,SAW_UP:0,SAW_DOWN:1,FENCE_CLOSED:0,OUTFEED:1
```

- X, safety and direct inputs publish every 200ms and on relevant commands/faults.
- POS_STEPS is signed commanded displacement since boot: positive toward Home.
  POS_KNOWN is always 0 in this version; no homed absolute position is claimed.
- MOVE_ID increments only on accepted motion commands, allowing the HMI to
  distinguish acknowledgment from stale pre-command telemetry. A missing move
  acknowledgment after one second causes OFF and a local fault.
- REMAINING is the active jog's unsent pulses. MAX_JOG is the per-command
  maximum (254); RATE_PPS is 40. JOG_READY becomes 1 when armed and the 200ms
  enable interval has passed. These are not machine-coordinate soft limits.
- The old 0.7.0 aggregate BUDGET field is removed. A completed manual jog does
  not disarm; no movement occurs until the next explicit click. Faults, STOP
  and the firmware heartbeat watchdog still disarm and cancel all remaining pulses.
- A controller uptime decrease revokes main-app consent. Boot clears all setup.
- HOME_CHECK:LEVEL_ONLY means manual setup/arm does not depend on HOME_VERIFIED.
  The historical transition flag may still be reported for diagnostics. A clear
  Home input is required; an asserted input still blocks and trips manual motion.
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
