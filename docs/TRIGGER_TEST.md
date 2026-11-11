# Unpowered Manual controls - 2026-11-10

Prepared firmware **0.18.0 / CARRIAGE_V12 / UNLOADED_V3** replaces the click-heavy
0.17 trigger test with one Manual session-enable gesture and hold-to-test.
**Not yet flashed.** Prior 0.17.0 is preserved; 0.16.0 is the hard-trigger-locked
rollback. Physical acceptance remains pending. Flood TTL / D19 drives the tiny
trigger-cylinder valve. No powered cutting or automatic blade triggering is enabled.

## Operator flow

1. Saw mains must remain **physically unplugged**, with no stock. The app cannot
   verify that plug or actual switch release. Inspect free mechanical return.
2. For flashing: app closed, driver/valve power OFF, air isolated/bleed verified,
   saw head secured. Boot and connection remain disarmed, all outputs OFF.
3. Verify guard closed, saw UP/DOWN inactive, healthy alarm, suppression/fuses
   and regulated air. Restore valve power/air yourself when ready. Driver may
   stay OFF; stationary pneumatic tests do not need Home or carriage enable.
4. MANUAL / Manual Machine Controls: click **Enable unpowered manual controls**.
   That single explicit gesture transfers the current bounded timing snapshot,
   waits for token/hash acknowledgment and enables the Manual session. It does
   not turn on a coil. No additional checkboxes or per-action arm buttons.
5. Use Clamp/Release, Lower/Return UP or Unloaded Saw Cycle as appropriate.
   Stroke still requires the clamp command to settle and real endpoint feedback.
6. **HOLD to press trigger**; release the mouse/touch to release. Repeat without
   rearming. The two-second pulse cap and ten-second permission expiry are gone.
   Trigger is allowed only at UP in READY/CLAMPED; no concurrent clamp changes,
   saw strokes or carriage motion. It is not latched ON.
7. Stop / release or Disable manual controls ends the session and releases the
   unloaded clamp, requests UP, and releases trigger. Recovery never resumes.

## Protections retained

- Trigger releases on button release, leaving MANUAL, losing window focus,
  feedback/interlock loss, Stop, disconnect or reboot.
- While the button is genuinely held in the active Manual window, the app sends
  DTHOLD at 100 ms intervals. Firmware releases after 350 ms without a valid hold.
  Generic KEEPALIVE cannot sustain it. Late hold messages cannot repress it.
- Guard, driver alarm, contradictory/lost endpoint faults, 1500 ms watchdog,
  loaded travel deadlines, 60 s clamp maximum and 15 s saw-valve maximum remain.
  These are fault detection, not extra user confirmations.
- Carriage and pneumatics remain mutually excluded. Raw OUT 2 ON stays rejected.
- Auto uses DARM (not DMANUAL), never sends a trigger press/hold, and the firmware
  rejects trigger presses in Auto even with otherwise healthy feedback.
- Trigger and clamp readbacks are commands, not proof of switch release or grip.
  Production stock retention and powered-blade safety still require separate work.

The trigger timing fields in Settings do not control this isolated hold-to-test.
Other cylinder timing settings are loaded automatically by the enable action.
After editing them mid-session, disable/re-enable to transfer the new snapshot.

## Acceptance

- [ ] Boot/connection OFF, one enable gesture leaves all coils OFF.
- [ ] Repeat hold/release trigger tests without per-action rearming.
- [ ] Release, tab/window change, guard/Stop and communication loss release it.
- [ ] Verify actual printed mechanism/switch release and clearance.
- [ ] Accept individual clamp/travel controls and their fault limits.
- [ ] Separately commission powered blade/air-loss/guard/stock-retention behavior.

Actual-sketch host and Qt mouse press/release tests cover a hold longer than
two seconds, repeated tests, tab loss, lease expiry/no auto-repress, watchdog,
faults, rollover, source exclusion, one-click setup and Auto trigger rejection.
Software tests are not physical acceptance or safety certification.
