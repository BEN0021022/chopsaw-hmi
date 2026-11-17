# App patch 0.24.1 — early operator attention and saved speed defaults

App-only changes for firmware 0.24.0 (also compatible with 0.22/0.23).

Historical behavior below: [0.25](CONTINUOUS_FEED_RETURN_025.md) supersedes the
disabled-during-return rule with an explicitly authorized return-only cut path.

The operator-cut button illuminates amber in EARLY_RETURN_ARM, before the Fast
return command, and stays amber throughout return/disarm. This visual attention
state is independent of click eligibility. Returning clicks remain ignored;
no saw command or queued approval can be sent until the carriage stops and the
existing operator-cut conditions pass. Semi-Auto idle controls remain muted.

Native startup profiles are Gentle 600 pulses/s / 600 pulses/s², Normal 2500 /
900 and Fast 3500 / 2000. Separate `teensy_profiles/<id>/rate,accel` PC preferences
preserve later explicit, acknowledged profile edits. Archived simulator settings
are untouched. Ordinary RAM readback or simple profile selection cannot overwrite
the saved defaults. Unsaved drafts are not applied to a move.

An explicit carriage move/Load/Auto request prepares and acknowledges any differing
saved profiles while disarmed, before arming or moving. Auto next-board preparation
uses the same check. Connecting alone sends no profile changes, arm or motion.
Home keeps its own independent approach/latch settings. Missing profile ACK cancels
the request and stops; it cannot start the requested move later. Settings continues
to show real controller readback separately from saved defaults/drafts.

Validation: actual-sketch/Qt startup defaults, unchanged display on old telemetry,
ACK-before-motion, restart persistence and missing-ACK cancellation; early-return
disabled-button amber pixels before return and ignored early click; existing
operator-return, Semi-Auto/pause, direct control, homing and second-clamp tests.
No firmware change, homing operation or physical motion was initiated for validation.
