# Garage commissioning - 2026-11-11

Current board baseline is **0.19.0 / CARRIAGE_V13 / UNLOADED_V4**, flashed and
read back on 2026-11-10. Individual mechanisms passed; combined physical
acceptance is still unrecorded. The prepared geometry coordinator and Full Auto
workbench are app changes. This work did not access or flash the board.

Use the current source app after a normal restart. Full Auto now contains a
read-only workbench available disconnected. Its legacy animation retains the
older virtual fixture; it does not establish real clamp positions or permissions.
Native Auto remains the place to start acknowledged dry runs.

## Offline preparation

1. Full Auto / Layout & scenarios: select examples for normal stock, pusher
   overlap, short stock between clamps, blocked detector, inconsistent detector,
   lost contact/reference, guard, stale telemetry and blade keepout. Green means
   policy eligibility in the example, not real machine health or grip.
2. Enter lengths in Auto. Preview the whole list from the displayed stock state.
   This assumes stock is already trued/contacting the pusher, starts at entry 1
   and stops at the first unsupported cut. The final cleanup result predicts a
   detector state; real execution must verify it. No acquisition is simulated by
   this lookahead and production cut-list progress is unchanged.
3. Review Cylinder Timing in Settings. Stored profile/timing values are not
   overwritten by scenario selection. Readback diagnostics show acknowledged
   controller waits separately from travel limits.

## Measurements to bring back

Machine x=0 is the blade plane; positive points toward Home. Record inches.
The 9–10-inch pad in examples is illustrative, not machine configuration.

| Item | Measured value / result |
| --- | --- |
| Main pad edge closest to blade | |
| Main pad edge closest to Home | |
| Pusher projection toward blade from reported carriage position | |
| Pusher body extent toward Home from reported carriage position | |
| Positive blade swept-area keepout | |
| Conservative geometry clearance margin | |
| Detector near/far edges (same value if effectively a point) | |
| Existing native sensor offset and trim convention physically verified | |
| Maximum bounded detector-clearing push | |

Save measured geometry once, disarmed with any sequence cancelled. Verify the
native truing datum before checking its commissioning box. Automatic clearing
has a separate acceptance switch; leave it off for initial normal-cycle tests.
Do not copy scenario dimensions. Outfeed is still planned, unmapped and unavailable.

## Garage test order

Saw mains stay physically unplugged. INA228/MCP stay disconnected. Existing
driver, suppression, guard and mechanical isolation procedures still apply.
No firmware change is required for this workbench.

1. Connect and check matching identity, fresh inputs, UP/DOWN agreement, healthy
   driver alarm and all commanded outputs initially OFF. Use Live machine
   readback; an offline example is not telemetry.
2. Home and check short carriage moves using the established profiles. Verify
   the native sensor/truing datum and record actual geometry before enabling
   geometry-dependent combined cycles.
3. With a valid modeled stock location, perform one normal combined Manual
   cycle. Check clamp settle, trigger, DOWN/UP endpoints, trigger release, brake
   wait and release clearance in that order. Stock registration records location,
   not grip. For an empty-machine test, document the deliberately simulated stock.
4. Run a short Auto list, starting with the detector clear. Trip it at SEARCH
   and keep it active until the truing move is accepted. In empty-machine tests,
   subsequent manually simulated detector states must agree with modeled stock:
   if its remnant still covers the detector, keep that input active until the
   modeled rear clears. An early release will correctly cause a mismatch pause.
5. Observe the clamp-ineligible pause with outputs unarmed. Manual Cycle reviews
   again; it does not bypass an unavailable holding arrangement. Stop cancels.
6. Separately accept bounded cleanup: known contacting remnant, detector blocked,
   Gentle push just past the detector plus margin, stable clear feedback, then
   FAST return. A mismatch or failed clearing must pause/stop without another push.
   Do not fake an acceptable signal to force progress through an actual fault.
7. Verify Stop/fault: trigger release, saw valve OFF requesting UP, engaged clamp
   retained, no auto-resume. Explicit retained-clamp release requires UP and the
   programmed brake interval. Follow the integrated recovery procedure.
8. Mark only observed results in Full Auto / Session checklist. Add measurements
   or the first failed step in notes, then export a commissioning JSON report.

## Reading diagnostics

Cycle diagnostics records accepted native phases plus coordinator decisions,
raw input/output readback, reference/material revisions and observed intervals.
Configured durations appear only when the timing hash is acknowledged. A host
ACK-to-WAIT transition does not split a physical timed phase. Feedback loss ends
an observation as interrupted. Telemetry can miss short phases; durations are
host observations, not firmware timestamps, grip confirmation or blade standstill.

Reports contain the active real geometry/material separately from any displayed
offline preview, the cut list, configured/acknowledged timings, checklist and notes.
History is bounded (2,000 events / 500 phase records); dropped counts are exported.
Checklist marks are session-local until exported and confer no operating permission.

## Still pending

- Physical geometry/truing/combined-cycle/cleanup acceptance.
- Selected-clamp/alternative-holding execution. Current DCUT always uses main.
  See [recovery design](HOLDING_RECOVERY_DESIGN.md); no clamp-free override was added.
  Operator chose to leave this paused until the second clamp is installed/mapped.
- New outfeed clamp installation, wiring, footprint and holding-role acceptance.
- Independent safeguarding, grip/coverage and blade-stop acceptance before
  powered cutting. This session is an unplugged commissioning session.

## Offline verification record

Pure scenario/lookahead/diagnostic tests, non-actuating Qt workbench tests, the
actual-sketch/Qt combined-cycle/cleanup test and existing carriage, keypad,
health, timing, Manual, simulator and backend-boundary regressions passed.
The workbench's dark layout, overlap case, checklist and populated diagnostics
were rendered for inspection. Production firmware source is unchanged.

One sequential offscreen integration invocation terminated in Qt6Core.dll with
Windows exception 0xc0000409. An immediate diagnostic rerun and three consecutive
additional runs passed. The cause is unconfirmed; this is retained as an open
test-process stability observation, not claimed fixed or physical acceptance.

See [automation supervision](AUTOMATION_SUPERVISION.md),
[integrated recovery procedure](INTEGRATED_DRY_RUN.md) and the
[master checklist](../TEENSY_APP_MIGRATION_CHECKLIST.md).
