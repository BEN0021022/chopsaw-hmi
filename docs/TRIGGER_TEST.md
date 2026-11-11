# Unpowered blade-trigger test - 2026-11-10

Firmware 0.17.0 / CARRIAGE_V11 / UNLOADED_V2 adds a separate bounded Manual
test for the tiny trigger-cylinder valve on **Flood TTL / D19**. This does not
enable powered cutting or add a blade trigger to the Auto dry-list sequence.
0.16.0 remains the hard-trigger-locked rollback. Physical acceptance is pending.
Flashed/read back on COM4 on 2026-11-10 after operator isolation confirmation:
no faults, disarmed/unconfigured, all outputs OFF, trigger locked, position
unknown and zero queued motion. The matching Manual app was reopened with no
consent checked; no arm/press/motion commands were sent by the agent.

## Procedure

1. Keep saw mains **physically unplugged throughout**, with no stock. The app
   cannot sense that plug. Inspect the trigger mechanism for free release and
   interference. Keep hands clear; a software OFF command does not prove that
   the printed mechanism has released the saw switch.
2. Flash only with app closed, driver OFF, valve power disconnected, air
   isolated/bleed verified and the saw head secured. Boot/connection never arms.
3. Check guard closed, real saw UP, DOWN inactive and healthy alarm readback.
   Confirm each DC coil's suppression orientation, fusing, OFF behavior and
   regulated air/flow controls before restoring valve power and air yourself.
   Leave carriage driver power OFF for this isolated trigger test.
4. In MANUAL / Manual Machine Controls, confirm unloaded preparation,
   **Load dry-run timings**, wait for acknowledgment, then **Arm unloaded
   pneumatics**. This alone does not turn an output ON. No Home is required for
   the stationary pneumatic test.
5. Check **Trigger test ONLY: saw mains physically unplugged**. Click
   **Arm ONE trigger press (2-second maximum)**. It enables one press, but does
   not press the switch. This unused permission expires after 10 seconds.
6. Click **Press trigger (max 2 s)** and observe the mechanism. **Release trigger**
   releases and locks it early. The controller automatically releases and locks
   it after at most 2 seconds, independent of PC timers/keepalive. A new press
   requires another explicit trigger arm. This is not a hold-to-run button.
7. Verify actual switch release. Test Stop and guard response while saw mains
   remain unplugged, then finish with **Stop / release**. Do not restore saw power.

Trigger arming is accepted only while unloaded pneumatics are armed and in READY
or CLAMPED, with stable UP, DOWN inactive, closed guard and healthy driver alarm.
During trigger arming/pressing, clamp changes and saw strokes are blocked;
carriage/legacy output commands are already excluded by the unloaded mode.
Door/alarm/position/communications faults clear the trigger and its permission.
The firmware watchdog is 1500 ms. Repeated press/arm commands cannot renew a
press. Stops, reset/reboot and reconnect do not rearm. The PC additionally
requires fresh matching telemetry and explicit consent. Raw `OUT 2 1` remains
rejected, including in the legacy Sensor Bench.

`TRIGGER` is the commanded electrical output, not feedback from the physical saw
switch, motor or blade. `LOCK:0` means one trigger test is armed; `LOCK:1` means
locked OFF. No automatic sequence uses DTARM/DTPRESS. The trigger timing fields
in Settings are not used for this fixed-duration isolated test.

## Acceptance

- [ ] Verify OFF/released startup before restoring valve power/air.
- [ ] One explicit arm/press actuates the trigger; release locks it OFF.
- [ ] Two-second maximum and ten-second unused-arm expiry work physically.
- [ ] Guard/Stop releases the mechanism; no unexpected other-cylinder/carriage motion.
- [ ] Verify physical switch return and clearance after repeated unloaded tests.
- [ ] Separately design and commission powered blade/air-loss/guard fault behavior.

Host tests exercise the actual sketch and Qt write boundary, including timeouts,
rollover, watchdog with blocked serial, interlocks, source exclusion, readback
and Auto trigger absence. They are not physical acceptance or safety certification.
