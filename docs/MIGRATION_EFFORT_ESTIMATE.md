# Remaining migration effort estimate

Planning estimate 2026-11-08, after manual carriage motion passed and software
homing 0.10.0 was implemented. Allow **12-24 active engineering hours** for the
remaining core workflow, plus elapsed time for physical validation, hardware
changes and troubleshooting. This is a rough scope estimate, not a delivery
commitment or an unattended-work schedule. It assumes the present hardware and
mechanics remain unchanged and the existing HMI/cut-list UI is retained.

| Work package | Remaining work | Active effort |
|---|---|---|
| Referenced carriage operations | Accept Home, add firmware soft limits and position invalidation, absolute cut-length/load moves, acceleration and speed profiles | 2-4 h |
| Stock/board workflow | Board-edge search, truing/near-calibration offsets, safe loading/return positions and collision bounds | 2-4 h |
| Pneumatic control | Individual suppressed-coil acceptance, clamp/saw/trigger commands and feedback, travel timeouts, defined fault/air-loss behavior, blade-disconnected dry runs | 3-6 h |
| Automatic cut-list workflow | Replace MEGA commands/state strings with explicit controller acknowledgments/completion events; next cut, cancel, reset/recovery, multi-board sequences | 3-6 h |
| Final validation and release | Fault matrix, regression/physical acceptance record, packaging, protocol compatibility, rollback and GitHub backup | 2-4 h |

Existing cut-list editing/import, settings UI, simulator and most presentation
code remain usable. The work is mainly translating operations to controller-owned
state machines and validating completion/fault behavior, not rewriting the UI.
The MEGA PID/encoder-position UI will not be recreated as a duplicate control
loop: the CL57T owns closed-loop feedback; alarm means stop and rehome, as agreed.

INA228 current sensing/MCP expansion is deferred, outside the core estimate.
Allow a separate roughly 3-6 engineering hours after a safe isolated hardware
setup is established; diagnosing damaged hardware or a supply/wiring fault could
add more. Begin with passive measurements before any protective behavior.

Coil suppression arriving does not itself complete physical acceptance. Final
blade-powered testing also depends on the independent guard/E-stop/energy controls
and the trigger/brake mechanism. Those hardware and acceptance tasks can dominate
elapsed time and are not guaranteed by the software estimate.
