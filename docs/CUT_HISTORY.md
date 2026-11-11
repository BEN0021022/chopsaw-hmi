# Cut history CSV

The source app automatically appends **cut_history.csv** beside `main.py`.
Packaged builds use the executable's directory, never the working directory or
PyInstaller's temporary extraction folder. The file is created on the first
confirmed native cycle, with one header, and retained across restarts. No new
button, setting or firmware flash is required. Restart an already-open app to
load this feature. Keep the CSV when replacing the executable during updates.

## What a row means

- `event_type=completed_cycle`: an accepted native DONE counter advanced by one.
  Completion is the controller's full combined cycle, including return/release;
  it is not an assertion that a spinning blade physically cut wood.
- Current firmware only supports saw-unplugged combined testing. All these rows
  have `run_type=dry_run`. Production execution/classification is not enabled by
  this feature. The virtual simulator and offline scenario previews write no rows.
- `cut_type=truing` identifies trim strokes separately from finished-list cuts.
  `mode` distinguishes Auto, Manual and an unassociated completion.
- A first counter reading after connect is a baseline, not a new cut. Repeated
  readings do not duplicate rows. A jump greater than one creates one
  `counter_gap` row with `completed_count` and unknown per-cut lengths; missing
  data is not invented. Normal piece counts should exclude gaps and truing rows.
- Cancelled/rejected cycles that never advance DONE produce no completed row.
  A fault after blade contact may have physically cut stock without completing
  the cycle. That partial cut cannot be inferred reliably from this counter.
  Logging requires the app to be connected; offline cuts cannot be backfilled.

## Lengths and identity

All dimensions are inches. `cut_length_in` for Auto is the frozen cut-list
target, labeled `cut_list_target`, not a measured finished-piece length. Truing
uses the configured trim and is labeled `truing_setting`. Manual positioning has
no known finished length, so that field remains blank (`unknown_manual_length`).

`board_length_in` is the starting stock length estimated at native edge capture,
labeled `edge_estimate`. It remains unchanged for every cut on that acquired
board; `remaining_infeed_in` tracks the current modeled remainder separately.
Manual stock registration locates infeed stock but does not measure the entire
original board: the original-length field remains blank. `board_preset_in`
records the selected nominal stock preset separately, never as a measurement.

`board_id` groups one edge acquisition/stock registration, not a globally tracked
physical piece. A reconnect or new acquisition establishes a new session/board
identity. `event_id` is the session plus controller counter and can be used as a
deduplication key in later analysis. UTC timestamps include an explicit offset.
Other columns record cut ordinal, carriage position, kerf and app version.

## Writing and errors

A bounded background writer appends/flushes each record. Disk access does not
run on the controller/Qt command thread and never authorizes or stops motion.
On write failure, a visible amber message gives the path/reason; queued rows
retry in order while the app stays open. A locked file or unexpected old header
is not silently overwritten or redirected to another folder. Only one running
app should write this history at a time; do not edit its live CSV externally.

The queue holds 1,000 waiting records. Queue overflow produces a persistent lost
record warning. A normal close waits briefly for writes, but forced shutdown,
power loss, a persistent write error or a full queue can lose unsaved records.
This is a metrics log, not a transactional production ledger. Runtime history is
ignored by Git; back up the CSV separately for long-term retention.

Verified offline: append across restart, single header, duplicate suppression,
unknown Manual dimensions, board grouping, slow/failed file writes, visible
warning, actual-sketch Manual/truing/two-cut Auto rows and no false completion
after cancellation/fault. No hardware was accessed for this change.
