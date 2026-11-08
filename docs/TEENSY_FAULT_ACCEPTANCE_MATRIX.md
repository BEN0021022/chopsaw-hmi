# Carriage fault acceptance matrix

Prepared 2026-11-08. These are expected software behaviors for prepared 0.13.0,
with no claim that the physical fault tests have passed. Manual motion and the
first Home were previously reported successful by the operator; they do not
complete this matrix. The saw is unplugged, valve power disconnected and air
isolated throughout carriage commissioning. Independent hazardous-energy
isolation must remain available.

For each physical test, record date/build, starting state, observed stop/motion,
driver indication, position validity and recovery. Change one condition at a
time under a controlled test plan. Do not simulate a wire fault by manipulating
exposed energized motor/supply conductors.

| Event | Expected app/controller result | Position/reference after event | Software evidence / physical result |
| --- | --- | --- | --- |
| Boot or reconnect | Reads only; no arm, enable or motion; setup and consent required | Unknown after boot; no invented coordinate | Boot/Qt checks pass; physical no-motion observation to record |
| Explicit STOP during jog/absolute/edge | Cancel remaining pulses, disarm, retain holding level; no resume | Counted reference retained for normal interrupted move; edge proposal expires | Native/Qt checks pass; physical stop distance/outcome pending |
| STOP during Home | Cancel sequence; no reference assigned | Unknown | Native/Qt checks pass; physical pending |
| Door opens | Immediate controller fault/cancellation; first fault latched | Unknown; rehome required | Native checks pass; door input works, moving-fault acceptance pending |
| Driver ALM becomes active | DRIVER_ALARM, cancellation/disarm | Unknown | Native checks pass; earlier real encoder-wire fault observed; controlled acceptance pending |
| Home asserts during non-Home motion | HOME_LIMIT, cancellation/disarm | Unknown | Native checks pass; physical pending |
| Saw leaves UP or contradictory endpoints assert | POSITION_LOST or POSITION_CONFLICT, cancel/disarm | Unknown | Policy/integration checks pass; physical pending |
| Keepalive stops / PC stalls / USB disconnects | Controller watchdog cancels at 1.5s; no queued resume | Unknown after watchdog | Native timing checks pass; hardware link-loss test pending |
| Motion or safety telemetry goes stale | App sends OFF, revokes consent; controller watchdog remains fallback | App blocks motion; firmware state depends on OFF versus watchdog | Qt checks pass; physical pending |
| Controller reboots | Outputs initialize OFF, ENA HIGH; app revokes consent | Unknown | Startup/restart checks pass; physical/mechanical result pending |
| Motor holding release | Stop then ENA HIGH, clear setup | Unknown; rehome required | Native/Qt checks pass; free-carriage mechanical behavior pending |
| Home missing/stuck/bouncing | Bounded phase pulse/time limits; HOME_FAILED; no automatic retry | Unknown | 209 policy/sketch checks pass; physical pending |
| Board sensor already active | Reject acquisition without movement | Existing reference retained | Native/Qt checks pass; physical pending |
| Board edge missing/bouncing | Exact search budget and timeout; EDGE_FAILED | Unknown after failed search; no truing proposal | Native/Qt checks pass; physical pending |
| Edge detected normally | Pause immediately, require 20ms stable input, capture then stop/disarm | Home retained; separate fresh proposal | Native and real-serial replay pass; geometry/physical pending |
| Old/cleared edge capture requested | Reject XTRUING; no substitute target or automatic search | No new reference established | Native/Qt checks pass; physical pending |
| Profile change while armed | Reject; leave active profile/timing unchanged | Unchanged | Native/Qt checks pass; physical pending |
| Target/search outside referenced range | Reject before motion; per-pulse violation instead faults | Rejected request retains reference; per-pulse fault invalidates it | Native/Qt checks pass; actual collision envelope pending |
| Malformed/unsupported control command | Fault/cancel at controller; legacy/raw outputs blocked by main app | Unknown on controller command fault | Native/Qt checks pass; hardware manipulation unnecessary |
| Electrical or air supply loss | Software cannot establish the resulting mechanical state | Treat reference/fixture state as unverified on recovery | Physical design/retention/isolation review required |

## Wiring limitations to retain in the design

Door wiring closes the input to ground when the guard is depressed. An open
door wire therefore reads unconfirmed and blocks carriage motion. That alone
does not make the guard circuit safety-rated or redundant.

Home, board edge and driver alarm use raw levels without supervised wiring.
A broken wire can resemble an inactive sensor or healthy alarm. The missing-Home
and missing-edge search bounds limit those particular sequences; they do not
detect every wire failure or establish an independent travel stop. A healthy
alarm reading alone does not prove continuity of its cable.

Combined pneumatics are deferred until clamp retention/release and saw behavior
on faults, power loss and air loss are established. The present all-OFF software
policy is not proof that a loaded clamp or saw will reach a safe mechanical state.
