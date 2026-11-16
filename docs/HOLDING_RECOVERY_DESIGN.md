# Holding-plan recovery - design history

**2026-11-16 update:** the selected-clamp executor described below is now written
and host-tested in prepared 0.24.0, with outfeed on Mist/D18. It is default-disabled,
not flashed or physically accepted. Current setup/protocol and remaining physical
checks: [second-clamp setup](SECOND_CLAMP_024.md). The main-only executor statements
below describe the earlier design boundary, not the prepared 0.24 implementation.

Operator decision, 2026-11-11: **keep no-main-clamp recovery paused until the
second clamp is installed and mapped.** The design below does not authorize an
external-fixture or clamp-free execution path in the meantime. Installation and
mapping will still need measured coverage/role and executor acceptance.

The coordinator can pause before arming, name inhibited clamps and re-evaluate
on an explicit Manual Cycle review. The current 0.19 DCUT executor always closes
the main clamp. Therefore it cannot implement a main-inhibited cut, even if an
alternative holding method is acknowledged in the UI. No such command is sent.

## Small extension once a holding arrangement is defined

1. Register a holding device with measured pad envelope, installed/commissioned
   status, role (remaining stock vs cut piece), channel and feedback availability.
   An external fixture must have its securing procedure defined. A future clamp
   does not become available from a name or estimated position alone.
2. Have the existing coordinator produce one immutable cycle plan: selected and
   inhibited devices, action, material/config revisions and current prerequisites.
   The plan must specify how both stock sides relevant to this cut are retained.
   Location registration and presumed hand support do not supply that evidence.
3. Extend the controller protocol with explicit supported holding plans. Exact
   command format/version remains to be implemented. Unsupported identities fail
   closed; old DCUT must not be substituted. Controller owns valve ordering,
   endpoint/watchdog checks and output states throughout execution.
4. At the existing unenergized operator pause, show the missing condition. One
   deliberate review/cycle gesture re-evaluates the current plan. No repeated
   confirmation stack, no automatic resume and no unlimited reusable permission.
5. Immediately before executing, reject changed material/geometry/reference,
   conflicting active clamps, guard/fault/stale feedback or blade keepout. Consume
   the approved one-shot plan once; Stop/disconnect/fault invalidates it.
6. Preserve defined Stop/recovery behavior for whichever holding devices actually
   engaged. Do not release holding merely because a PC times out or a preview
   step changes. Retained-clamp release remains a separate deliberate recovery.

## Acceptance cases for that future extension

- Main eligible: execute existing behavior without extra clicks.
- Main inhibited, alternative absent/planned: remain paused; no valve command.
- Main inhibited, installed alternative eligible and supported: execute only the
  selected plan after a new gesture; never substitute main or close onto pusher.
- Cut piece between pads: remain paused if no defined holding arrangement covers it.
- Changed revision, repeated request, late ACK, reconnect or lost reference:
  invalidate permission and do not restart.
- Stop during each phase: release trigger/request UP, retain engaged holding as
  specified, reject carriage motion and release only through validated recovery.

This design is ready for refinement; controller implementation and physical
acceptance remain pending the actual securing arrangement and I/O map.
