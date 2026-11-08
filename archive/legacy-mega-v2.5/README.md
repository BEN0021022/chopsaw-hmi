# Preserved MEGA V2.5 firmware

Recovered 2026-11-08 from `C:\Users\bensc\OneDrive\Documents\Arduino\Arduino_Closed-Loop_Enabled_AUTO_V2.5.ino\Arduino_Closed-Loop_Enabled_AUTO_V2.5.ino.ino`. This file is preserved byte-for-byte;
it is historical MEGA code, not firmware to flash onto the current Teensy.

SHA-256: `99c0c1bb44fa83b24a2357401101456bef9069aa5884670807191d618667c697`

Source lines 45-50 define 200 motor steps/revolution, MICROSTEPS=1, and
STEPS_PER_INCH_DEFAULT=127.12. The later V2.6 migration startup note independently
carries over 127.12 steps/inch (5.00472440945 steps/mm).

The V2.5 source can change the factor using a serial manual-setting command
or the calibration function. Neither EEPROM storage nor startup loading of a
saved calibration appears in the sketch. This recovers the programmed default,
not an EEPROM dump or a new physical measurement. The user reports the old
machine was precisely dialed in and asks to reuse its firmware calibration.

The separately preserved HMI is in sibling project `ChopSawHMI`,
Git tag legacy-mega-last-working-2026-11-06, commit 97255b8. That HMI's 127.0
startup display value is not the motor firmware's 127.12 conversion factor.
