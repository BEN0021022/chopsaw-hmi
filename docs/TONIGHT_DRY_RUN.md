# Unloaded commissioning preparation — 2026-11-09

This is a readiness audit and implementation queue, not a declaration that the
combined test firmware is ready. The current baseline remains **0.15.0**.

## Operator-confirmed test scope

- No board, stock or cutting during these tests.
- Saw mains physically unplugged throughout.
- Blade-trigger channel disabled/OFF; do not exercise it tonight.
- Main clamp: ON clamps, OFF releases (confirmed 2026-11-09).
- Saw-travel valve: OFF returns UP (previously operator-confirmed).
- Fit/verify coil suppression and branch fuses before valve power; keep suspect
  INA228/MCP disconnected.

Outputs are saw travel AUX2/D33, main clamp AUX1/D32 and blade trigger Flood/D19.
Virtual clamp IDs 1/2/3 are not physical OUT channel numbers.

## Ready now

- Baseline firmware/source/readbacks are preserved in `tmp/commissioning/0.15.0`.
- Archived HEX SHA-256 matches its manifest:
  `5E2BAB99FBFA21DEE529B0DE899720BE6386CFF20D0E5ADC4187B8AC56F6C267`.
- Firmware source tree is unchanged: `b81f87f66cf43d861982c83d6eb65a6eb746735c`.
- All seven host firmware suites passed 2026-11-09 (2451 checks), plus 55
  actual-sketch motion-record replays through the Qt protocol parser.
- Carriage Home, jog, absolute target and FAST Load commands exist; previous
  operator tests passed. Physical fault acceptance still needs completion.
- Sensor Bench supports individual pneumatic tests: one output at a time,
  endpoint/door checks, five-second maximum ON, travel timeout and heartbeat.
- New Manual actuator controls and timing settings work in Simulator. Their
  native hardware handlers/buttons remain locked.

Flashing 0.15.0 does NOT enable combined manual controls or live Auto Start.
Nothing has been flashed during this preparation.

## P0 work before combined tests

1. **Controller-owned unloaded pneumatic mode:** hold main clamp while cycling
   saw travel; hard-lock Flood/D19 OFF. Do not expose production cutting or raw
   output commands as a shortcut.
2. **Configuration/arm acknowledgments:** validate and transfer a bounded timing
   snapshot; report the accepted configuration and exact dry-run capability.
   Connect/reset/guard-close must never start or resume motion.
3. **Native manual actions:** clamp/release, lower/return and one unloaded stroke.
   Require clamp-command settling before downstroke, but label it commanded,
   not verified grip. Use real UP/DOWN endpoints and bounded departure/arrival
   deadlines; reject contradictions and queued/repeated stroke requests.
4. **Carriage exclusion:** no feed while clamp ON or saw away from UP, and no
   pneumatic sequence while carriage pulses remain. Holding torque is separate.
5. **Unloaded fault policy:** saw OFF, clamp OFF/released, trigger locked OFF;
   cancel pending phases and require recovery/rearm. This is not a production
   clamp-retention policy. Test door, alarm, endpoint, timeout and link loss.
6. **Native app adapter:** match new capability/identity, fresh phase/output
   telemetry and acknowledgments; heartbeat locally. Do not unlock PC-timed
   Simulator handlers to drive real valves.
7. **Explicit no-stock cut-list stepping:** establish a separate operator-started
   test reference from genuinely homed coordinates and validate every target.
   Board-edge acquisition cannot run normally without a board. Do not fake Home,
   switches or production edge detection. Start one move/cycle at a time initially;
   do not mark real cuts complete or consume production progress.
8. **Matching build package:** HEX/hashes, app revision, source rollback, passing
   firmware/protocol tests and separate physical acceptance steps.

## Physical acceptance order

1. Blade unplugged, valve power/air isolated: check exact identity, pin map,
   polarity and timing readback; boot disarmed, zero queued motion, outputs OFF.
2. Check door/endpoints by hand, then Home, short carriage jogs, direction and STOP
   with valve power still disconnected.
3. After diode/fuse checks, accept one cylinder at a time using regulated air and
   flow controls. Measure travel and confirm OFF behavior before choosing limits.
4. Only after the new combined path is implemented/tested and physically accepted,
   test unloaded clamp + saw down/up, release and motion exclusion.
5. Step a short no-stock cut list, explicitly starting each feed/cycle initially.
6. Record controlled stop, guard, missing endpoint, alarm and link-loss responses.

Blade mains stay unplugged and the trigger channel disabled throughout.

## Still excluded

Blade operation; real cutting; production Auto/Full Auto; claiming grip from time;
inheriting the simulator's three-inch clamp rule; automatic retry/resume; assuming
retention on air/power loss. These need separate design and acceptance work.
