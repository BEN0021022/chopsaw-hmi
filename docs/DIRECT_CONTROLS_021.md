# Direct controls — 0.21.0

The normal workflow is **Connect → Home → use the controls**. The app handles
driver configuration, timing acknowledgments and controller-mode handoffs for
each explicit gesture. There is no session checklist, consent checkbox, manual
enable, separate arm button or stock-registration step in Manual/Auto.

- **Manual carriage:** type a target or use the touch keypad, then Enter. Home
  establishes the reference first. Typing never queues a later move.
- **Manual mechanisms:** Clamp/Release, Lower/Return UP, and hold-to-press
  trigger work directly. Individual unplugged saw travel does not require the
  clamp to be engaged. Manual Cycle runs clamp → trigger → saw down/up →
  trigger release → brake wait → clamp release with the saved timings.
- **Auto:** load the cut list and press Start Auto. At a board boundary, load
  the next board and press Start next board. Detector acquisition and the
  sensor-plus-kerf truing advance remain automatic.
- **Settings:** valid saved physical dimensions are reused at startup. Edit
  and save them when the hardware changes; no verification waiver is needed.

The trigger remains held by the operator during individual testing; releasing
the button, losing focus or leaving Manual releases it. Stop is always
available. Reset fault appears only for an actual fault. The workbench keeps
its layout, scenarios, diagnostics and report export; its checklist page is
removed.

## Machine conditions

Fresh matching feedback, closed guard, healthy driver and consistent saw
position remain required. Carriage moves require saw UP and trigger/clamp OFF;
referenced targets stay inside the existing soft limits. Known pusher/clamp
overlap and blade keepout remain blocked. Automatic cuts still use the material
and holding coordinator; no-clamp recovery stays paused until the second clamp
is installed and mapped. Manual Cycle uses operator-positioned stock and never
fabricates a stock location or grip confirmation.

A pending gesture belongs to one connection and is revoked by Stop, fault,
feedback loss or reconnect. It is never replayed after recovery. Connect sends
identity/status requests only. UI checkboxes no longer authorize machine
readiness; the controller still validates commands and acknowledges state.

## Verification / deployment

Matching firmware: **0.21.0 / CARRIAGE_V15 / UNLOADED_V5 / PROTO5**. This changes
individual Manual travel to support clamp-OFF Lower/Return UP. Wiring, profiles,
calibration, combined-cycle order, watchdog and travel bounds are retained.

Host tests cover one-gesture Home, physical/touch carriage entry, load/jog,
actuator-to-carriage handoff, independent unclamped travel, held trigger,
Manual Cycle without registration, cancellation during preparation, real
sketch/Qt protocol replay and multi-board cut lists. The Teensy 4.1 build is
compiled separately. Physical acceptance is performed by the operator.

This build remains for **saw-mains-unplugged testing**. The guard is a Teensy
input; it does not provide independent machine shutdown. The app changes do
not establish powered production readiness.

Local deployment artifacts are saved under `tmp/commissioning/0.21.0` with
source, HEX hash, readback and preserved RAM motion profiles. The 0.20 archive
is retained for rollback.

Deployment confirmed 2026-11-11 on COM4 after operator isolation confirmation.
Source checkpoint `106b854160d703bfea64928d68d64c2166217999`. HEX SHA256
`29274ec1ec1af609f2108460be20959a06be2429f97f26abae5ad3ab3f5c1d17`. Startup and captured-profile restoration
verified; matching app reopened on Manual. Physical Home/cycles left to the operator.
