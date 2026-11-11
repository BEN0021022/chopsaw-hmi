# Multi-board queue and forward truing correction - 0.20.0

Prepared/tested 2026-11-11. Matching firmware 0.20.0 / CARRIAGE_V14 advertises
`TRUING:SENSOR_PLUS_TRIM_V1`. Prior 0.19 source/HEX remain archived. No pulse
calibration, wiring, motion soft limits or pneumatic interlocks are changed.

Flashed/read back on COM4, 2026-11-11 after operator closed the app and confirmed
ready for flashing. Boot OFF/disarmed/unconfigured, Home unknown, no faults or
queued motion. Captured RAM profiles were restored/verified using XPROFILE only:
Gentle 600/600, Normal 2000/1500, Fast 3500/2000. No setup, enable, Home, motion or
valve command was sent. Source checkpoint `08374d5`; HEX SHA256
`7f0968e90c2a49efdad82dbc02446c59848c0a3d024a3b1279c765d53d184a6f`.

## Reported failure and correction

The five listed lengths (57.75, 57.75, 24, 24, 17.5 inches) total 181 inches,
before kerfs. The native runner incorrectly compared the entire queue with the
single captured board's truing coordinate. That incorrectly stopped before
truing even when the next several cuts fit. The grouped list UI already displayed
multiple boards, making this check contradictory to the intended workflow.

The new small `plan_board_feed` policy assesses ONE next cut against current
referenced stock and blade keepout, including a calibrated-pulse rounding buffer.
Holding eligibility is still reviewed separately after positioning. A cut that
fits in travel can still pause if the pusher occupies the clamp envelope.

If the next cut needs another board, perform the same commissioned bounded
detector cleanup (if needed), verify clearance, return using FAST, disarm and
wait. **Start next board** explicitly reacquires/trues fresh stock and resumes
the retained next-cut index. Detector changes alone never restart. The waiting
state has no arbitrary stage timeout. Edits to the cut list/kerf require restoring
the frozen batch or cancelling it; no silent changed queue executes.

If even the first next cut will not fit a newly captured board, pause before
truing or pneumatic arm. The displayed next-cut index remains intact. Stop
cancels; no generic clamp-free recovery is added.

## Forward truing

The old firmware used `capture - sensor + trim`, so a positive trim SHORTENED
the advance. This also required an app-side material-origin reset to conceal the
board not reaching the blade in the modeled geometry. That reset is removed.

The corrected target is `capture - sensor - forward_trim`. Auto freezes the
batch kerf as forward trim: **10.8 + 0.12 = 10.92 inches toward the blade** after
the edge capture. The first stroke is a truing stroke; finished list cuts follow.
Actual motion is quantized to the calibrated 127.12 pulses/inch. The carriage
diagnostic panel's independent trim setting is explicitly labeled extra forward
trim; it does not override Auto's kerf setting.

The app validates the new sign against controller readback. An old 0.19 identity
is incompatible with the new app. Stored geometry verification tied to the old
truing convention is invalidated; measured dimensions are retained. Review and
save the geometry using the new datum before Auto. Automatic cleanup must be
accepted separately. Operator supplied physical pusher body extent: **16.75 in**;
160 in is the cleanup/travel allowance, not that physical dimension.

## Verification / garage acceptance

- Actual sketch/Qt test covers the reported five-cut queue on two boards; the
  test fixture uses a different clamp footprint to isolate capacity from holding.
- Separate 90/90-inch queue exercises cleanup before the next board and the
  final return. Board ID/cut metrics stay grouped and no pieces are duplicated.
- Tests cover a wait longer than 180 seconds, blocked detector, queue edits,
  deliberate restart only, too-long first cut and exact sensor-plus-kerf command.
- Existing edge/interlock/positioning/protocol/Manual/dry-run suites and Teensy
  compile pass. Physical acceptance is still pending, with saw unplugged.

For the real machine's 8.75–9.75-inch main clamp footprint, the reported queue
can reach a later cut where the pusher interferes with that clamp. The expected
result there is the separate operator holding pause, not permission to clamp
onto the pusher. No-main-clamp recovery remains paused until the second clamp is
installed, mapped and commissioned.

After flash: verify OFF/disarmed/unknown position, restore captured profile
values without motion, then let the operator review geometry, Home and initiate
dry runs. Do not automatically repeat the failed sequence.
