# Auto / Semi-Auto and manual intervention — app patch 0.22.2

Prepared/tested offline, 2026-11-12. Uses existing **0.22.0 / CARRIAGE_V16**
firmware. No board connection or firmware flash was performed or is required
for this app-only update. Physical acceptance remains pending, saw unplugged.

## Controls and modes

Auto now has **Automatic** and **Semi-Auto / approve each cut** sub-tabs. They
share one cut list, target entry, live feedback, carriage controls and progress
owner. Switching pages does not copy/reset the list. A running sequence can
change modes only at a paused/manual checkpoint, followed by an explicit Resume.

Both modes provide **Home**, **Confirm / Clear Error**, **Cancel Cycle**,
**Pause Cycle**, **Resume Cycle**, Load and jog controls. Manual's numeric keypad
also works while the list is paused. No separate arming/waiver controls return.

- Automatic retains normal clamp/cut/feed scheduling.
- Semi-Auto positions each cut, then waits with a highlighted **Clamp / Cut /
  Advance** button. The button stays visible in Semi-Auto while idle/moving,
  muted and disabled until the controller is waiting for approval. The mode
  heading identifies Semi-Auto in amber and Automatic in blue, and the start
  button names the selected mode. Truing is labeled **True-up / advance** separately. No
  completion is assumed from pressing either button; only controller DONE
  advances the index and history.
- Jog/position/Home from a Semi-Auto approval checkpoint automatically enters
  the paused manual window. After adjustment, the cut button can resume and
  approve that pending cut in one gesture, subject to current holding geometry.
- For unclamped early return, the amber operator button appears as soon as the
  board is positioned, before return begins, at the top of Cycle Control. It stays
  fully illuminated amber while returning (a separate attention state), and remains
  disabled until the carriage is stationary and the saved pending-cut conditions
  still match. No approval or stroke is queued during movement.

## Pause, adjust and resume

Pause during acquisition/truing/feed stops the carriage and waits for readback.
It keeps the pending list item and a checkpoint of the actual stopped position.
If a saw stroke has already been issued, routine Pause finishes that stroke,
brake wait and release, then stops before the next feed. **Cancel/STOP** is the
immediate interruption path; it cancels the saved sequence rather than guessing
where to continue. A retained clamp may still require the existing explicit
release after UP/brake conditions are satisfied.

While paused, jog, absolute positioning, Load and Home are available with normal
carriage interlocks. Resume never runs while a manual motion is in progress.

- Without adjustment, interrupted truing/feed completes its saved target.
- An intentional adjustment at a pending cut becomes the cut position and the
  baseline for the following feed. Place the stock against the pusher before
  Resume. The paused UI shows an adjusted cut estimate; history identifies this
  as an operator-adjusted feed estimate, not a measured finished-piece length.
- Home or a withdrawal that loses a usable material reference resumes by fresh
  detector acquisition/truing, keeping the next pending cut index. A blocked or
  contradictory detector prevents that reacquisition until reconciled. Old cuts
  are not silently repeated, nor is withdrawn stock modeled as attached to the
  pusher.
- During an early-return operator cut, Pause preserves that pending piece; Resume
  completes the return or restores the same operator-cut wait. It does not send
  a normal main-clamp cycle in place of the inhibited-clamp stroke.

Fault, disconnect, list/kerf edits or unknown reference outside this controlled
pause still stop/cancel the active sequence. Clear Error only resets eligible
faults; it does not replay a move or certify material/grip. Ambiguous interrupted
strokes are not declared complete. Geometry/holding, blade keepout, real inputs,
controller acknowledgments and existing soft limits remain enforced.

## Scrap and repeating production patterns

Three preferences are saved on this PC and frozen for a running batch:

| Preference | Behavior |
|---|---|
| Repeat cut list on each new board | After completing the list, retain it, reset its next index to the first cut and wait for Continue. Never sensor-start the next board. |
| Clear sensor zone between boards | Use the existing bounded sensor-clear push when another board is needed, including a completed repeating-pattern boundary. |
| Clear sensor zone at end of finite list | Optionally clear the remainder before the final return; OFF retains it for manual removal. Not used in Repeat mode. |

For **34 / 34 / 34 repeated from ten-foot stock**: Repeat ON, Between Boards ON.
Complete the three cuts, clear only the detector zone, return to Load, then load
stock and press Continue. Repeat until canceled; no target quantity is inferred.

For a **finite multi-board list with useful final remainder**: Repeat OFF,
Between Boards ON, End of Finite List OFF (defaults). Clear intermediate boards
when needed; on the final board return without pushing the remainder. Remove
it manually before starting another batch. Disabling between-board clearing
leaves detector clearance to the operator before Continue can reacquire stock.

## Verification

Actual-sketch/Qt tests exercise the real 0.22 C++ logic with mocked clock/GPIO,
never COM hardware. Coverage includes approval at truing/every cut, single-click
jog/absolute override, adjusted next-feed origin, pause-after-stroke, manual Load
and Home/reacquisition without losing the pending index, mid-search/truing/feed
pause, paused mode switching, early-return/returned-piece pause, signal mismatch,
Cancel revocation, repeat pattern clearing, finite remainder retention, highlight
and CSV completion. Existing Manual, keypad, health, acquisition and multi-board
regressions remain part of the harness.

Preview images: `tmp/ui-intervention/semi-adjusted.png` and
`tmp/ui-intervention/repeat-ready.png`. Local source/validation archive:
`tmp/commissioning/0.22.2`. Saw mains must remain unplugged for physical testing.
