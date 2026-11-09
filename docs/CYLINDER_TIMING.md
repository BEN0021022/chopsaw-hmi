# Cylinder timing and sequencing

Updated 2026-11-09. Settings now owns one **Cylinder Timing** frame. Full Auto
has no timing controls or automation-enable switch. Its clamp display describes
the virtual three-clamp fixture, not the physical Teensy output map.

## Settings

Select Board positioning, Main clamp, Saw travel cylinder, Blade trigger
cylinder, planned Outfeed clamp or planned Backstop/fence clamp. Values are
milliseconds and are shared across carriage speed profiles. Each clamp has its
own independent values. Planned entries do not declare hardware installed.

| Stage/device | Configurable values | Current use |
| --- | --- | --- |
| Board positioning | Settle after carriage stops | Simulator |
| Each clamp | Engage delay, engage settling, release delay, release clearance | Simulator's participating virtual clamps |
| Each clamp | Confirmation limit | Saved plan; feedback not configured/enforced |
| Saw travel | Downstroke delay, bottom dwell, return-UP delay, settle after UP | Simulator |
| Saw travel | Down/UP travel limits | Saved plan; future controller phase watchdogs |
| Blade trigger | Press delay, spin-up wait, release delay after UP, braking wait | Simulator timing model |

**Save Timing Settings** persists the values locally. Closing the app also saves
them. Editing/saving never sends hardware commands. Settings is scrollable so
more devices/settings can be added without enlarging the application window.

Live Teensy automatic cutting remains unavailable. These fields do not change
the independent Sensor Bench/manual firmware's provisional five-second limits.
Native timing transfer, phase watchdogs and combined pneumatic sequencing still
need implementation and physical acceptance. Values shown here are not verified
physical operating times. In particular, newly introduced normal-cycle delays
default to zero; planned confirmation/travel limits start at 5000 ms.

## Saved-value migration

- Old `clamp_engage_delay` means board settling, and migrates to `board.settle`.
- Old `saw_start_delay` means clamp closing/settling, and migrates to each
  clamp's `engage_settle`. It does not become blade spin-up time.
- Defaults preserve 300 ms board settling and 800 ms clamp settling.
- New keys use `cylinder_timing/<device>.<action>` and take precedence over old
  keys. Old keys remain read-only compatibility inputs for rollback; there are
  no old widgets or alternative active timing paths.

## Simulator sequence

Each cut takes a timing snapshot; edits made during it affect the next cut.
Board settle completes first. Each selected virtual clamp then gets its own
engage delay and settling wait. Saw activation waits for every participant.
Trigger press/spin-up and saw-down waits precede virtual travel. Bottom dwell and
return delay extend the virtual stroke. After a real virtual not-UP to UP edge,
the sequence waits for UP settling, trigger release and braking, then applies
each clamp's release delay/clearance. Cut completion waits for every release.
An acknowledgment or new cycle cannot bypass those phases.

The fixed virtual travel model remains 0.4 seconds to leave UP, 1.6 seconds to
the cut, and 2.6 seconds to return UP before added delays. These are simulation
constants, not predictions of real cylinder speed. Normal-cycle delays are
distinct from a destination-confirmation timeout. Planned timeouts are clearly
marked and are not silently treated as active protection.

Stop, disconnect and automation-off invalidate pending callbacks. Simulator
cancellation stops its pending stroke events and releases virtual clamps
immediately; normal-cycle release delays do not postpone cancellation. This
does not specify a safe real-machine fault response.

## Manual controls (Simulator)

The MANUAL tab also has independent main-clamp, saw-travel and blade-trigger
buttons plus a combined Manual Saw Cycle and Stop. These are functional in
Simulator only; their handlers reject native hardware even when invoked directly.
They do not use the Auto simulation checkbox, legacy clamp-selection rules or
cut-list advancement. Manual saw activation requires a settled virtual main
clamp and UP. A normal manual cycle returns UP, releases the trigger after the
configured waits and leaves the clamp held until an explicit Release command.
Carriage motion and Auto startup are excluded while the manual clamp/saw is active.

Manual Stop cancels delayed callbacks/virtual stroke events, releases the virtual
trigger and retains the clamp. Freshness loss or disconnect cannot automatically
resume a pending action. The virtual stop resets the simulated saw UP; this is
not proof of the mechanical result of a real fault. Native controls remain visibly
locked: current firmware permits only one pneumatic output at a time, so it cannot
support the combined held-clamp/saw/trigger workflow. A controller-owned manual
sequence and its physical feedback/retention policy must be commissioned first.

## Physical clamp selection remains separate

The archived simulator fixture uses main/fence for truing, all virtual clamps
for longer stock, and virtual outfeed only below its old three-inch threshold.
That rule is isolated in `simulation_clamps` and cannot authorize a native cut.
Its IDs 1/2/3 are not Teensy OUT indices.

Before native automatic cutting, record actual clamp footprints and stock
coverage, decide which material must remain restrained through separation, and
require eligible clamp confirmation. A cylinder reaching an endpoint alone
does not prove wood is gripped. No eligible holding arrangement must block the
cut. Define retention/release behavior on guard, driver, power and air faults;
do not infer that releasing every clamp is safe. New clamp timings may share
the same settings framework without copying geometry or scenario decisions.
