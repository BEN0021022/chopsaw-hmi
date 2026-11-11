# Integrated saw-unplugged commissioning - 0.19.0

For the prepared 2026-11-11 geometry supervisor/workbench, use the
[current garage procedure](GARAGE_COMMISSIONING.md) alongside the controller
sequence below. Geometry commissioning is now required for automatic combined
cycles. Full Auto's read-only workbench is available offline; its native cycle
execution remains unavailable. Simulated detector states must agree with modeled
material during the new remnant-clearance check.

Flashed/read back on COM4 on 2026-11-10 with isolation confirmed: all outputs OFF,
disarmed/unconfigured, no faults/queued motion, Home unknown. Matching Manual app
reopened; connection/verification were reads only. Individual mechanisms were confirmed
working by the operator on 0.18. Combined-cycle and new Home/Auto acceptance are
still pending. No powered cutting in this build's approved test scope.

The operator confirms saw mains stay physically unplugged. Driver and air were
switched OFF/isolated for the update. Guard currently only signals the Teensy.
No mains wiring or OEM brake circuit has been changed by this software. Trigger
release requests the original switch's braking action; timer/readback does not
prove actual switch release or blade stop. Independent safeguarding remains a
separate engineering task before powered operation.

## Home and Manual

- Connect the matching app. Connection sends reads only and never moves.
- Manual has Dashboard, a single **Home** button, then Machine Controls/keypad.
  The old Controls frame/checks/setup/arm/motor-power widgets are no longer shown.
- Home explicitly authorizes acknowledged XCONFIG 0 1 if needed, then XHOME 20594.
  It does not require a separate sensor-trip ritual, setup or arm. The maximum
  seek is approximately 162 inches at 40 pulses/s, not the old two-inch setting.
  Slow latch/release/pull-off remain. The finite 10-minute and phase/pulse limits,
  guard, alarm and watchdog stops remain; this is not an unlimited search.
- In Manual Machine Controls, Enable unpowered manual controls transfers all
  15 timing values and waits for ACK. Individual Clamp/Release, Lower/UP and
  hold-to-test trigger buttons remain separate. No Home is needed for stationary
  pneumatic tests. Keep carriage clear and driver OFF for that first test.
- **Manual Cycle — saw unplugged** accepts READY (clamp OFF) or CLAMPED. Firmware
  engages/settles clamp if needed, waits trigger press delay, presses trigger,
  waits spin-up, runs DOWN/bottom dwell/UP using real switches, settles UP, waits
  release delay, releases trigger, waits brake interval, then releases clamp and
  waits clearance. Completion returns READY; a new cycle needs a new click.

## Auto

Home first, add a short list and choose Load. Detector starts clear; saw UP;
clamp/trigger OFF; driver green/red healthy. Click **Start Auto — dry run**.
That explicit gesture loads/ACKs current timings, prepares carriage and starts
the sequence. No separate Auto timing-load checkbox/arm ritual.

At SEARCH, trip and hold the real Limit Y detector until the truing move starts,
then release it. The existing sensor offset/trim creates the truing target.
The carriage moves to it using Normal; disarms; performs the full DCUT sequence;
feeds each cut length + kerf and repeats; returns to selected Load using FAST.
One truing stroke plus one stroke per list item. Firmware never emits carriage
pulses while clamp/saw/trigger owns control. Production list progress is not
consumed by these dry runs. Full Auto and automatic recovery remain unavailable.

## Timing and recovery

Settings / Cylinder Timing has all main clamp, saw travel and trigger fields.
Values load on Manual enable or Start Auto. Delays 0..5000 ms, travel limits
100..5000 ms. After editing during a Manual session, disable/re-enable to load.
Firmware retains 1500 ms watchdog, 60 s clamp, 15 s saw valve, 30 s automatic
trigger maximum. Extreme summed settings can exceed those bounds and fault.
Timed settling is not grip feedback; timed brake wait is not standstill sensing.

Stop/fault releases trigger, turns saw valve OFF (requests UP), retains an engaged
clamp, retains carriage holding and cancels pending sequences/preparations.
This is commanded behavior only: actual switch return, air/power loss and OEM
braking must be engineered/verified independently. StopReturn waits 5 s for UP.

Use **Release retained clamp** only after clearing the cause and confirming real
UP/guard/alarm; firmware also waits the programmed brake interval since Stop.
Then acknowledge any latched fault. Fault invalidates Home; recovery never arms
or resumes. Normal successful full cycle releases clamp only after UP/trigger
release/brake wait. An individual travel-only stroke still retains clamp.

## Physical acceptance (operator initiated)

- [ ] Verify all outputs OFF/disarmed after flash, fresh matching telemetry.
- [ ] One-click Home from several carriage locations; Stop/failed-sensor responses.
- [ ] Manual Cycle from unclamped and already-clamped states; check every timing.
- [ ] Verify trigger physically releases; no unwanted mechanical interference.
- [ ] Stop/guard/endpoint/watchdog retains clamp and releases trigger; recovery.
- [ ] Short Auto list: real detector/truing, trigger cycles, carriage feeds, FAST return.
- [ ] Separate powered-operation safeguarding, grip/coverage and brake acceptance.
