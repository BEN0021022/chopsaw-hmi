# Saw position and door switch commissioning plan

Updated: 2026-11-08. Status: wiring assignment and required software behavior;
Door and saw-switch input transitions are user-validated. Logic-only interlock
firmware 0.4.1 remaps Saw Up to Limit Z and is built/simulated/flashed;
manual acceptance of the new input remains pending.

Use the DIYables B0BPGPCN19 SPDT roller-lever dry-contact switches. Each has
COM, NO, and NC contacts. NO means open with the lever released, not with the
machine in a particular state. Identify terminals by markings and a continuity
test; do not infer terminal order from appearance.

## Exact assignments

| Wire labels | Confirmation | Breakout input | MCU pin | Switch COM | Switch NO | Switch NC |
|---|---|---|---:|---|---|---|
| DOOR-C / DOOR-S | Door physically closed and lever depressed | Door screw-terminal pair | D29 | Door Gnd | Door Sig | Unused; insulate |
| SAWUP-C / SAWUP-S | Saw physically fully up and lever depressed | Lim Z screw-terminal pair | D22 | Lim Z Gnd | Lim Z Sig | Unused; insulate |
| SAWDN-C / SAWDN-S | Saw physically fully down and lever depressed | Fd/Hld screw-terminal pair | D16 | Fd/Hld Gnd | Fd/Hld Sig | Unused; insulate |

Use each screw-terminal pair's labeled Gnd and Sig. These switches
need no external +3.3V, +5V, or +12V connection and no voltage dividers.
Use a signal/return pair for each switch with strain relief and protected
terminals. Keep runs separated from motor and solenoid wiring. Saw switches
must sense the actual saw mechanism and must not serve as mechanical stops.

## Expected logic: verify before relying on it

Door, Limit Z, and Fd/Hld use optocoupler inputs. The custom bench firmware uses
Limit Z and Fd/Hld only as saw position feedback, not as a Z-axis limit or a
feed-hold button. The schematic's internal
title says V2.07; actual V2.20 hardware readings are the acceptance authority.

Recovery finding, 2026-11-07: ST0 and ST1 measured approximately 3.3V released
and 0V pressed at the header, but no dashboard raw transition was reported.
Their buffer/socket paths remain unverified; damage is not yet established.
Leave ST0/ST1 disconnected and defer that investigation. Firmware 0.3.1 moves
the saw switches to the adjacent opto inputs. MCP23017 and INA228 remain fully
disconnected during recovery. Door switch operation was confirmed by the user.

Recovery update, 2026-11-08: Cyc/St/D17 later stopped responding. User reported
voltage unloaded but collapse with a short test-switch harness even when the
switch was open. Cause remains undiagnosed; leave Cyc/St disconnected. Build
0.4.1 reads Saw Up on Limit Z/D22. No positive supply wire is needed. The HMI
requires INPUT_MAP:DOOR29_UP22_DOWN16 before permitting output-test arming.
Build 0.4.1 was flashed and its new input identity and D22/LIMIT_Z mapping
verified on COM4; outputs remained OFF and disarmed. Physical switch acceptance
on Limit Z remains pending.

| Input | Lever released or wire disconnected | Lever depressed / COM-NO closed | Sensor Bench Active-low |
|---|---|---|---|
| FENCE_DOOR / D29 | Expected raw HIGH: door unconfirmed, inhibit | Expected raw LOW: door closed | Checked |
| SAW_UP / D22 | Expected raw HIGH: up unconfirmed | Expected raw LOW: up confirmed | Checked |
| SAW_DOWN / D16 | Expected raw HIGH: down unconfirmed | Expected raw LOW: down confirmed | Checked |

Saw input polarity is saved by its new pin assignment so old ST settings do
not override the opto default. Existing saved settings can still be changed. Verify both
positions of every switch and unplug each wire in turn. Display ON means that
particular physical condition is confirmed, not that the entire machine is safe.

## Position interpretation

| Up confirmed | Down confirmed | Interpretation / required behavior |
|---|---|---|
| Yes | No | Fully up; eligible starting position once other conditions pass |
| No | Yes | Fully down; do not start another downstroke |
| No | No | Between endpoints or unknown; normal only during an expected, timed stroke |
| Yes | Yes | Contradictory feedback: latch fault and block further cycling |

Two endpoint switches do not measure continuous position. A disconnected
endpoint wire is indistinguishable from an unpressed switch; travel timeouts
and starting-position requirements must detect missing confirmations.

## Required controller changes before motion testing

- Boot disarmed. Require a validated closed door, consistent feedback, and an
  explicit operator arm/reset. Closing the door never starts or resumes motion.
- Enforce the door permit locally in Teensy firmware for ARM and every output-ON
  request. An open or disconnected door input revokes permission and latches a
  fault without waiting for the PC's 200 ms telemetry stream.
- Accept a new downstroke only from confirmed UP and with the required clamp
  confirmation. Allow endpoint departure and the intermediate state during a
  stroke. Require destination arrival within a measured, bounded travel time.
- Debounce physical confirmations; begin with approximately 20 ms stable
  assertion and tune from observed contact behavior. Revoke door permission
  promptly on loss; avoid a long debounce delay on the stop path.
- Latch contradictory endpoint, missing destination, and door faults. Require
  explicit reset and a fresh command after the fault is corrected.
- Show DOOR CLOSED / OPEN, SAW UP / DOWN / BETWEEN / FAULT in the HMI and identify
  whether the values are fresh. Indicator polarity alone is not an interlock.
- Define the physical fault response before commissioning: de-energizing the
  saw valve must have a verified safe mechanical effect. Do not assume dropping
  every valve, venting air, or releasing the clamp during a stroke is safe. Assess
  supported saw return, trapped energy, blade stopping, and clamp retention.

Firmware 0.4.0 implements a limited, logic-only manual test policy: stable closed
door and UP before arming, single-output exclusion, immediate door-loss and
contradiction trips, unexpected position-loss detection, provisional five-second
down/return limits, latched faults, and separate RESET then ARM. The actual C++
policy and command handler pass host tests, and the Teensy build compiles.
It is not a cutting state machine: clamp confirmation/retention, supported return
on air loss, independent guarding, calibrated travel times, and physical fault
response validation remain required. Keep coil power and air disconnected.
Firmware 0.4.0 was flashed and identified on COM4 on 2026-11-08. Initial status
was disarmed, all outputs OFF, door open, no endpoint confirmed, and ARM blocked.
Manual door/endpoint/fault acceptance with loads disconnected remains pending.

The DIYables switch and single-channel Teensy input provide commissioning and
operational feedback. They are not a personnel safety-rated guard system. A
suitable safety-rated guard interlock, safety relay/controller, and independently
controlled hazardous-energy path are required for personnel guarding. An open
wire removes confirmation; a short across COM/NO or welded contact can falsely
maintain it, so this arrangement is not comprehensive fault detection.

## Hardware acceptance sequence

1. Isolate blade power, cylinder air, and valve power while wiring and positioning
   switches. The lever must be reliably depressed at its intended position,
   without becoming a hard stop or being over-travelled.
2. With all power removed, verify each COM-NO pair is open released and continuous
   depressed, and verify no signal conductor is tied to an external positive rail.
3. Restore only logic power. Confirm expected raw transitions and the bench
   polarity table above by hand, including wire-disconnection tests.
4. Record actual endpoint readings and verify the switches cannot both be
   depressed by the saw at one physical position.
5. After controller interlocks are implemented, verify door-open prevents arm,
   opening/unplugging it trips the permit, and reclosing cannot restart outputs.
   Simulate endpoint contradictions and timeouts with valve power isolated.
6. Progress to supervised low-pressure travel with blade power isolated only
   after the agreed stop/return/clamp response and independent protections pass.

## References

- [DIYables switch specification](https://diyables.io/products/limit-switch)
- [Official breakout resources](https://www.grbl.org/t41u5xbb-information)
- [Stored V2.20 schematic](references/T41U5XBB-V2.20-schematic.pdf)
- Firmware: `firmware/chopsaw_sensor_bench/chopsaw_sensor_bench.ino`
