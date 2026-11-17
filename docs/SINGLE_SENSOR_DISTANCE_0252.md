# One board sensor distance — app patch 0.25.2

2026-11-16. App-only update; firmware remains 0.25.0.

Settings → Board Sensor Distance beside Blade Kerf is the only editable and
persisted sensor coordinate. The laser detector is modeled as a point at
that distance. Motion acquisition/truing, material tracking, detector agreement,
cleanup planning and live visualization now use this same value. The duplicate
near/far fields have been removed from Machine dimensions.

Saved geometry is loaded using the existing `board_sensor_location` preference
(10.8-inch default if absent). Legacy `sensor_near`/`sensor_far` keys are ignored
and removed after the remaining saved geometry validates. Clamp/pusher/keepout
dimensions and second-clamp enable are preserved. New geometry saves do not
write the retired keys. Ordinary cutting-setting persistence remains in place.

Editing the sensor distance immediately updates the geometry point and
invalidates the old material reference. Kerf edits also invalidate the material
reference. Active sequences retain their existing reference-change cancellation;
the setting change never commands motion or valves. Start a fresh acquisition
after editing; do not reuse a board reference captured at the old distance.

The reported acquisition snapshot identified the original failure precisely:
controller offset 10.5 inches, modeled detector 10.8 inches, kerf 0.12 inch.
The model consequently put the leading edge at +0.180236 inch and refused the
stroke with NO_STOCK_AT_CUT. The operator confirmed that matching the former
fields resolved it. This update removes the duplicate source of that mismatch.

Validation: stale-key migration, removed UI fields, immediate reference
invalidation, clamp/pusher preservation, geometry save/restart persistence,
reported-cut capacity/diagnostics and actual-sketch acquisition/truing tests.
Tests use isolated settings and simulated GPIO/time; no garage connection or
firmware flash is required. Prior intermittent native Qt test-process crashes
remain separately documented in the 0.25 deployment notes.

The actual-sketch regression changes only Board Sensor Distance from 10.8 to
10.5 after saving the other dimensions, confirms a 10.62-inch sensor-plus-kerf
advance and completion of the first truing stroke, then checks bounded
no-detection handling. A late capture made with old sensor/kerf parameters
cannot restore an invalidated material reference. Full native dry-list and
second-clamp compatibility cases also passed during this change.
