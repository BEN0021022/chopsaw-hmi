# X-axis bounded jog commissioning

Current main-app manual control uses controller **0.9.0**: repeatable bounded
jogs, up to 254 pulses per click, without a cumulative per-arm allowance. See
[main-app feature map](APP_FEATURE_MIGRATION.md) and [protocol](CONTROLLER_PROTOCOL.md).
The earlier bench commissioning sequence below retains its historical budgets.

## Recovered calibration update (2026-11-08)

The MEGA V2.5 firmware was recovered: **127.12 pulses/inch at full stepping**.
Use that historical machine value, as requested by the user, instead of the
earlier 127.1 estimate. See [calibration provenance](MOTION_CALIBRATION_PROVENANCE.md).
No new ruler measurement is required for this source-recovery step. Historical
notes below retain the earlier estimate and sequence of commissioning checks.

Updated 2026-11-08. Current source firmware 0.6.0, X_TEST:BOUNDED_JOG_V1,
X_MAP:STEP2_DIR3_EN40. This is a bounded
diagnostic, not production motion control, homing, or an automatic saw cycle.
The motor is coupled to the carriage. User confirmed clear travel in both
directions, 5V input selector, ENA and ALM wiring, and SW1-SW4 all ON (200 pulses
per revolution per the driver's table). The 127.1 steps/inch estimate is not
calibrated; old software's 127.0 default is not accepted as measured calibration.

Flashed and identified on COM4 on 2026-11-08. Readback confirmed STEP=0,
DIR=0, ENA=1, disarmed, unconfigured, zero step budget, and pneumatic outputs OFF.
The 0.5.1 startup preloads GPIO output latches before changing pin direction;
this corrects the ENA LOW readback found during the 0.5.0 check. Native tests
passed 83 policy and 40 command-integration checks; HMI tests and Teensy build
passed. Physical buffer voltage checks and motion acceptance remain pending.
No physical STEP commands were sent during preparation.

## Enable-path recovery update

User confirmed DIR voltage switches, Home verification passes, and driver
SW6/SW7 are OFF with green power ON, red alarm OFF, ALARM_RAW=1. Original Axis X
En remained 4.85V at both commanded states, including with the driver physically
disconnected and unpowered. This isolates a fault/mismatch to that breakout
path but does not prove which component failed. Leave Axis X En disconnected.
Build 0.5.2 remaps logical X enable to spare Axis Y En/D40; STEP/DIR stay on X.
126 native checks (83 policy + 43 integration), HMI tests, and Teensy compile
passed. Flashed/read back on COM4, new map identified, STEP/DIR LOW, ENA HIGH,
all outputs disarmed and zero budget. User subsequently confirmed D40 LOW/HIGH and X DIR voltage tests pass,
and ENA=0 gives motor holding torque. The enabled level is LOW (0).
No physical step test has yet been confirmed.
The dashboard requires the matching X_MAP. Reboot clears Home verification.

## Connections and isolation

| Breakout point (Axis X unless stated) | Driver |
|---|---|
| Stp (D2) | PUL+ |
| Dir (D3) | DIR+ |
| **Axis Y En (D40)** | ENA+ (after unloaded voltage validation) |
| Gnd | PUL-, DIR-, ENA- |
| Halt Sig (D14) | ALM |
| Axis/Halt Gnd | COM- |

Confirm actual wiring against these assignments. Keep the saw mains unplugged,
valve 12V feed disconnected, air isolated, and INA/MCP disconnected. Driver
power is OFF during flashing and output-pin measurements. Do not unplug motor
or encoder wiring under power. Use a fused driver supply in its rated range
(photographed CL57T: 18-50VDC) with an accessible power disconnect.

## Phase 1: signal checks, driver power OFF

Boot holds STEP LOW, DIR LOW, ENA HIGH. HIGH is an electrical level, not a
verified disabled state. No steps occur at boot, reconnect, ARM, or setup.

Open **X Stepper Test**, confirm driver power OFF, and measure at the breakout's
Axis X Stp/Dir and Axis Y En screw terminals with black probe on common axis Gnd:

| State | Axis X Stp | Axis X Dir | Axis Y En |
|---|---:|---:|---:|
| Boot / DIR 0, ENA 1 | near 0V | near 0V | near 5V |
| DIR 1, ENA 0 | near 0V | near 5V | near 0V |

The GPIO report is not proof that a damaged 5V buffer works; use the meter.
XLEVEL changes DIR/ENA only and invalidates prior driver setup. STEP stays LOW.
Never use a meter's current or continuity mode on powered signal pins.

## Phase 2: inputs and driver state, no STEP commands

1. Activate and release the actual Limit X sensor with logic powered and no
   axis movement: raw LOW then HIGH, stable for at least 20ms each. Firmware
   requires this before configuration. A jumper alone does not validate the
   installed sensor or its placement.
2. Confirm SW6 OFF (closed loop) and SW7 OFF (PUL/DIR), motor/encoder connections,
   rated motor-current setting, supply polarity, and signal wiring while off.
3. Leave STEP LOW. Power the driver with the carriage clear. Check the green
   power indicator and red alarm indicator; do not proceed with an alarm.
4. Establish which ENA level gives holding torque without commanding steps.
   If a level change is needed, power down before using XLEVEL, then repower.
   Do not put fingers into the transmission or attempt to stall a powered motor.
5. Record the ALM raw level with the driver powered and healthy, then select
   that level and the verified enabling ENA level in the test window. The
   polarity must not be inferred from an unpowered or disconnected driver.
6. With door closed, Saw UP only, Home inactive, and clear travel confirmed,
   confirm driver setup. Configuration is volatile and lost on firmware reboot.

## Confirmed physical motion (2026-11-08)

User reported a seven-flash position-following alarm, found a loose encoder
wire, secured it, then confirmed carriage motion works. Physical directions:

- A / XSTEP -1 / XJOG -1: DIR LOW, toward the saw.
- B / XSTEP 1 / XJOG 1: DIR HIGH, away from saw toward the Home sensor.

These directions are user-confirmed. Actual travel per pulse is unmeasured;
127.1 pulses/inch remains provisional. Automatic homing and absolute position
are not established. Next measure a 127-pulse jog against a fixed reference.

## Phase 3: operator-commanded bounded jogs (0.6.0)

The user confirmed 0.5.2 single-pulse testing made audible clicks, but visible
travel was too small to establish direction or calibration. Clear travel in both
directions was reconfirmed. Version 0.6.0 adds X_TEST:BOUNDED_JOG_V1 and retains
X_MAP:STEP2_DIR3_EN40. Previous single-step builds cannot arm this HMI's jogs.

- Select 1 pulse, ~0.1 inch (13 pulses), ~0.5 inch (64), or ~1 inch (127).
  Labels use the provisional 127.1 pulses/inch estimate, not measured position.
- Default is ~0.1 inch. Establish actual direction and travel with this first,
  then progress to larger increments only with confirmed clearance.
- Each arm permits 254 pulses TOTAL across both directions (~2 inches total).
  A two-inch test is two separate one-inch clicks. This is not a position limit.
- Jogs emit at most 40 pulses/second (one nominal inch takes about 3.2 seconds).
  Only one pulse is serviced per loop; delays never create catch-up bursts.
- A click queues one bounded jog, never continuous motion or autorepeat. While
  moving, increment and direction buttons disable; firmware rejects extra moves.
- There is at least 200ms after ARM and between completed moves. Each jog has
  at least 10us direction setup and each pulse has 5us HIGH width.
- Serial parsing and safety checks run throughout the jog. Door open, loss of
  saw UP, contradictory endpoints, Home activation, alarm change, or heartbeat
  timeout cancels remaining pulses and latches a fault. OFF/disarm/dialog close
  also cancels; remaining pulses never resume automatically.
- Stop retains ENA/holding torque and does not disconnect motor power. These
  commissioning checks are not safety-rated machine protections. Heartbeat
  timeout is 1.5s; use an accessible independent driver disconnect.
- Pneumatic and stepper modes remain mutually exclusive. Keep saw unplugged,
  valve power disconnected and air isolated throughout these carriage tests.
- Reboot clears Home verification and driver profile. Repeat actual Limit X
  trigger/release and confirm enabled LOW/healthy alarm HIGH, with healthy LEDs.

## Test protocol

```
XLEVEL <DIR 0|1> <ENA 0|1>     # driver OFF signal test; never emits STEP
XCONFIG <enabled ENA 0|1> <healthy ALM 0|1>
XARM 1                       # 254-pulse total budget; no STEP on ARM
XSTEP -1                     # one pulse, DIR LOW
XSTEP 1                      # one pulse, DIR HIGH
XJOG -1 13                   # bounded jog; DIR LOW, 13 pulses
XJOG 1 64                    # DIR HIGH, 64 pulses
XJOG 1 127                   # DIR HIGH, 127 pulses
XARM 0                       # cancel/disarm; retains ENA
OFF                          # cancel/disarm all modes
```

Only directions -1/1 and jog counts 13/64/127 are accepted. Excess-budget
requests are rejected. General pulse counts, rates, g-code, automatic homing,
and continuous jog remain unsupported. Telemetry includes REMAINING (current
jog) and BUDGET (total remaining pulses this arm).

Native verification covers 83 interlock policy checks and 87 command/scheduler
checks: counts, timing, total-budget exhaustion, queue rejection, OFF and all
fault cancellations, heartbeat loss, malformed requests, no catch-up bursts,
and microsecond rollover. Qt tests cover commands, map gating and moving-state
controls. Physical direction was subsequently confirmed above; hardware travel still
requires operator measurement.

Sources: [CL57T manual](https://www.omc-stepperonline.com/download/CL57T-V41_user_manual.pdf),
[pin map](TEENSY_PIN_MAP.md), [recovery checklist](RECOVERY_COMMISSIONING_CHECKLIST.md).
