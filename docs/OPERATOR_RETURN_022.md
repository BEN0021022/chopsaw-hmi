# Auto feed profiles, early return and operator cut — 0.22

## Profile sequence

Real detector acquisition now uses the stored **Gentle** rate and acceleration,
including the initial approach/contact push. Gentle stays selected through the
sensor-plus-kerf advance to the first truing cut. Subsequent cut-list feeds use
**Normal**. Load/return moves use **Fast**. Bounded scrap clearance uses Gentle.
User profile values and calibration are preserved; Home retains its existing
bounded homing profile.

## Unclamped piece at a pending cut

The coordinator first checks the normal main-clamp holding plan. If the installed
main clamp cannot cover the wood or overlaps the pusher, a separate operator-cut
policy handles the already-positioned cut. It does not bypass unknown geometry,
missing material reference, contradictory detector state or blade keepout.

- If another queued cut still fits the remaining material, **keep the carriage
  forward** and wait for the operator-controlled cut. After completion, feed the
  next cut normally and assess it again.
- For the **last usable cut**, when the measured detector and material model
  agree that the detector is clear, return to Load in Fast **before** the cut.
  No scrap-clearing push is sent. Withdrawal does not pull the modeled stock
  back or pretend that pusher contact remains established.
- After the carriage is stationary/disarmed, show an amber dashboard state and
  **Wood secured / run cut — Saw unplugged** button. The operator verifies the
  positioned piece and requests one stroke. There is no pause timeout and no
  sensor-driven automatic resume.
- That one explicit action prepares the controller and sends a distinct
  config/request-bound `DOPCUT` command. The main clamp remains OFF throughout.
  Trigger delay, spinup, saw travel/endpoints, trigger release and brake wait
  remain controller-owned. Ordinary `DCUT` still uses the main clamp.
- Only confirmed controller DONE advances the pending cut and CSV history.
  If already returned, wait for **Continue cut list / next board**, retaining
  the next index. Acquire a fresh board before feeding again. Do not load the
  next board over the detector before the pending operator cut finishes.

If the detector still blocks a last-cut return, stay forward for operator input;
normal bounded detector clearing is assessed after that cut. Unknown/disagreeing
state keeps the sequence paused. Stop, disconnect, reference/list/kerf changes
or faults revoke the pending operator action, rather than replaying it.

## List display

Auto and Full Auto highlight and scroll to the native runner's current cut.
Truing does not consume a list entry. Operator pauses keep the same entry
highlighted, confirmed cuts move the highlight down, and next-board waits retain
the next pending entry. The loaded list remains intact for later reruns.

## Scope and verification

This is **saw-mains-unplugged testing**, not approval for hand-held stock during
a powered automatic cut. Operator input is an assertion, not measured grip or
blade standstill. A powered holding arrangement and independent guarding remain
separate work. Planned outfeed clamps are not silently commissioned or mapped.

Firmware: **0.22.0 / CARRIAGE_V16 / UNLOADED_V6 / PROTO6**. Readback explicitly
identifies operator cycles and requires CLAMP=0. Wrong/stale request/config IDs,
duplicate commands, Manual mode and clamp-held starts reject `DOPCUT`. Stop,
guard and watchdog clear operator authorization and trigger.

Actual-sketch/Qt regression uses the physical pusher/clamp geometry and a
142/2/40-inch queue: stay forward for 142, early return before 2, no automatic
stroke while waiting, two explicit clamp-inhibited strokes, then continue 40
on another board without duplicate cuts. It checks profile readback, highlight,
CSV completion, blocked detector before confirmation, long pauses and Stop.
Host suites, existing Manual/Auto tests and a Teensy 4.1 compile also pass.

Local source/HEX/readback/profile archive: `tmp/commissioning/0.22.0`.
Previous 0.21 archive is retained for rollback. Physical operator acceptance
of this new workflow remains pending.

Deployment verified 2026-11-11 on COM4 after operator isolation confirmation.
Source `57ba1e018755ebc24706bfe7d9abf5420edd632a`; HEX SHA256
`0d97a7b1893fac03f951910553323ef934e95f0d192a4794a7cbcd9e77b402e8`. Captured Gentle 600/600, Normal
2000/1500 and Fast 3500/2000 restored. Matching app opened on Auto; startup
outputs OFF, Home unknown, no queued motion. Physical tests left to operator.
