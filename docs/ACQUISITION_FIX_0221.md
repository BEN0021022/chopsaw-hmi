# Auto acquisition correction — app patch 0.22.1

Firmware remains **0.22.0 / CARRIAGE_V16**. No firmware flash is required.

The reported stop was reproduced against the actual sketch: Auto sent
`XEDGE 254 10800 120`, stopped after 254 pulses (1.998 inches), and reported
`EDGE_FAILED / NOT_FOUND`. Readback from the physical board confirmed those
same fault/error/pulse values, healthy driver, closed door, saw UP and all
actuator outputs OFF. The app had reused the advanced bench search widget's
two-inch default. Its generic feedback message then concealed the real cause.

Auto now calculates its own acquisition bound from the referenced carriage
position and soft limits. It reserves room for the full sensor-plus-kerf truing
advance, pusher projection and blade keepout plus one calibrated pulse. The
advanced bench's short search setting remains independent. Auto does not gain
unlimited travel or bypass an end limit.

Acquisition and truing remain Gentle. The search ends on stable detection or
its bounded failure conditions. The error display preserves the controller
cause, distinguishing detector not found, timeout, driver/guard faults and
missing/stale feedback. Resolving a fault never automatically replays a move.

Regression coverage now waits until the carriage has actually advanced eight
inches before tripping the detector. It also checks different start positions,
reserved truing/keepout distance, no acquisition from unknown/insufficient
reference, unchanged bench limit, and exhausting a complete search without
any truing/cylinder command. The original two-inch version fails this test;
the corrected app passes. Earlier tests tripped the detector immediately and
therefore did not catch the short search cap.

Physical motion/cycle acceptance remains with the operator. Keep the saw mains
unplugged for this commissioning scope. Local patch/readback/source archive:
`tmp/commissioning/0.22.1`.

App patch reopened on Manual/COM4, 2026-11-11. The exact latched search fault
was reset only with RESET_READY and all outputs OFF. No arming, Home, carriage
or valve command was sent. Firmware tree is unchanged from deployed 0.22.0;
source checkpoint `0dfa16328f12f4fa927f5be2b9bfa262c6bde77e`. Operator Homes and retries Auto.
