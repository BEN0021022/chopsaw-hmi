# Acquisition rejection diagnostics — app patch 0.25.1

Prepared 2026-11-16 for existing firmware 0.25.0; no flash required.

The generic “waiting for suitable stock” status previously replaced every
acquisition capacity-check rejection, including reference and machine-state
failures. That hid the reason needed to investigate repeated refusals after
Stop/Cancel or an app restart. A reported pair of 38.313-inch cuts at about
82.125 inches passes the pure capacity check with the saved 0.12-inch kerf.
The cause on the physical machine is not yet identified.

Acquisition rejection now preserves the decision code/reason in the status
and serial log. Only NEXT_BOARD_REQUIRED uses BOARD_TOO_SHORT. Other refusal
codes pause for operator reconciliation; none bypasses the failed check or
starts a stroke. Detector/model disagreement also has a specific reason.

At the first refusal, the app writes a timestamped
`diagnostics/acquisition-rejected-*.json` beside `cut_history.csv` (beside the
executable when packaged, project directory when running from source). It
includes the exact evaluated material span, contact/confidence/source,
geometry, freshness/readiness flags, raw inputs, carriage and pneumatic
readback, sequence and recent phase diagnostics. Ordinary status refreshes
do not overwrite the reason or create repeated files. A file-write error
is reported while the refusal remains in effect. Snapshots occur at the
stationary acquisition review and do not send any controller command.

Validation: classification/persistence/snapshot/write-failure tests; reported
lengths fit; real-sketch delayed acquisition and bounded-no-detection tests;
stop during acquisition followed by fresh acquisition passes offline. Physical
reproduction is pending. Existing intermittent native Qt test-process crashes
recorded with 0.25 remain a separate unresolved limitation.

Reproduction: connect normally, Home if position is unknown, run the same
unplugged test. If it pauses, leave the state unchanged and inspect the newest
snapshot. No need to repeatedly Cancel/Start or manually export a report.
