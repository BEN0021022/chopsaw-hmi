# Recovered carriage calibration

Recovered 2026-11-08: **127.12 STEP pulses per inch**, or
**5.00472440945 pulses/mm**, from the MEGA V2.5 firmware. It specifies
200 steps/revolution and MICROSTEPS=1, matching the user's current CL57T
SW1-SW4 all ON/full-step setting. User reports the old machine was precisely
calibrated and requests reuse rather than a fresh ruler measurement.

[Preserved original firmware](../archive/legacy-mega-v2.5/legacy_mega_v2_5.ino)
contains the value at line 49. [Archive provenance](../archive/legacy-mega-v2.5/README.md)
records the source and checksum. V2.3 used 127.1, V2.4 used 127, V2.5 uses 127.12;
the later V2.6 migration startup notes also explicitly carry 127.12 forward.
The old Python HMI's 127.0 display/simulation default is not the authoritative
firmware conversion. No EEPROM calibration persistence was found in V2.5.

Use **127.12** as the recovered machine calibration with the same mechanical
transmission and full-step driver setting. This is recovered source provenance,
not a new accuracy measurement. Changes to microstepping, pulley/gearing or
mechanical transmission require a revised conversion.

Current bench jogs remain fixed raw counts: 13, 64, 127 pulses; 254 total per
arm. At 127.12 pulses/inch they represent 0.102266, 0.503461, 0.999056 and
1.998112 inches respectively. Their labels remain approximate. No firmware
flash or physical motion was performed while recovering these files.
