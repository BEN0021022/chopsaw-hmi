# Second / outfeed clamp — prepared firmware 0.24.0

Prepared offline on 2026-11-16. **Disabled by default. Not flashed, wired or
physically accepted.** This build also includes 0.23's configurable homing.

## Wiring when the cylinder is installed

| Breakout connection | MOSFET connection |
|---|---|
| JP10 **Mist / Sig**, Teensy **D18**, 5V TTL | PWM / signal input |
| Adjacent JP10 **Gnd** | Signal GND |

Use the TTL header, not the Mist relay screw terminal. Valve power goes through
the MOSFET as for the main clamp. Use the coil's correct supply, common signal
ground, branch protection and flyback diode (band/cathode to coil positive).
Wire with power off. Confirm ON clamps and OFF releases. Existing assignments:
main AUX1/D32, saw travel AUX2/D33, trigger Flood/D19. AUX0 stays retired.

## Settings and controls

- Settings → Machine dimensions has **Enable second / outfeed clamp — Mist TTL
  D18 (after wiring and testing)**. Defaults OFF; existing saved geometry gains
  no implicit enable. Checking an unsaved draft sends nothing.
- Enter measured pad near/far distances **outward from the blade on the outfeed
  side**, as positive distances. Far must exceed near; near must exceed blade
  keepout plus margin. No guessed footprint is assigned. Internally the pad
  occupies negative machine coordinates.
- Save while stationary, released and outside a cut-list cycle. Saving invalidates
  material plans. The next explicit Manual/Auto preparation loads and acknowledges
  the configuration. Connecting/saving dimensions never energizes a valve.
- Cylinder Timing → **Second / outfeed clamp — Mist D18** has independent engage
  delay, settle, release delay and clearance. Shared board-settle precedes engage.
  Confirmation timeout remains planned: no grip/end-position feedback exists.
- Manual has a second Clamp/Release row, disabled until enabled on supported
  firmware. Auto shows DISABLED/OFF COMMANDED/ON COMMANDED/UNKNOWN independently.
  The layout preview uses the saved footprint and holding role.
- Stop/fault releases the trigger and requests saw UP, retaining engaged clamps.
  **Release retained clamps** becomes available after controller-confirmed
  guard/UP/healthy alarm/brake wait. Any held clamp blocks carriage motion.

## Selecting a holding plan

The shared coordinator evaluates both pads against modeled material, pusher
closing envelope, margin and blade keepout. Auto/Semi-Auto select main only,
outfeed only or both when geometrically eligible and supported by current
controller readback. Outfeed holds the cut piece. It is never substituted onto
the main output. Each selected clamp completes its own engage/settle before
triggering and release/clearance before DONE, carriage movement or list advance.

Pieces between pads retain the existing operator-intervention path. No coverage
or grip is inferred merely because another cylinder exists. Manual Cycle normally
uses main; explicitly engage outfeed first to include it, since Manual lacks a
measured stock extent. When main is inhibited, that explicitly engaged outfeed
clamp can supply the Manual plan. Commanded/timed state is not grip feedback.

## Controller extension

Firmware **0.24.0 / CARRIAGE_V17** retains base unloaded V6 and adds capability
`SECOND_CLAMP:D18_MASK_V1`. Raw Sensor Bench output count stays three; D18 cannot
be energized through generic `OUT` commands.

- Existing 15-slot timing commits remain compatible and disable second clamp.
  New commits contain 20 slots: slot 15 strict 0/1 enable, slots 16–19 outfeed
  engage delay, settle, release delay, clearance. Hash covers committed values;
  incomplete/invalid commits are rejected.
  While disabled, the app sends zero for these four unused delay slots; stored
  future outfeed timing drafts cannot disrupt main-only operation.
- `DCLAMP2 1/0`: independent Manual engage/release only when enabled, saw UP,
  trigger OFF, and no other transition/cut running.
- `DCUTM <config-id> <next-request-id> <mask>`: one combined cycle. Mask 1=main,
  2=outfeed, 3=both. Zero/unsupported masks, stale/repeated requests and conflicting
  retained clamps are rejected. Legacy `DCUT` remains main-only.
- `BENCH_DRY` adds MAIN_CLAMP, SECOND_CLAMP, SECOND_ENABLED, CLAMP_MASK and
  PLAN_MASK. Existing CLAMP means **any held clamp**, preserving all carriage,
  feed and cleanup exclusions. The app validates aggregate/individual bits,
  enable, plan and hash. Missing/contradictory new-capability readback stops.
- Existing explicit unplugged operator-cut commands inhibit both clamp outputs.

On 0.22/0.23, main-only features remain supported with second clamp disabled.
Enabling it without the capability blocks preparation. No secondary command
or silent main-clamp substitution is sent.

## Later garage sequence

1. Close app; isolate driver/valve power and air, saw mains unplugged, before
   flashing. Read back identity, D18 LOW, second disabled, all outputs OFF.
   Preserve/restore carriage profiles as usual.
2. Install MOSFET/diode; measure and save the pad dimensions and desired timings.
3. Enable/save, then test unloaded Manual Clamp/Release, polarity, travel,
   interference and retained-clamp recovery.
4. With saw unplugged, test main-only, both, outfeed-only and uncovered-piece
   cut-list cases. Physically validate restraint on both sides before powered cuts.

Host tests use the real sketch and Qt app for disabled rejection, independent
timing, outfeed-only Auto, stale plans, retained holding and legacy lockout.
Physical acceptance remains pending. Build/source/hash records are archived in
`tmp/commissioning/0.24.0`.
