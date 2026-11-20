# v1.1.0 release record

Published 2026-11-20:
https://github.com/BEN0021022/chopsaw-hmi/releases/tag/v1.1.0

- App/source tag: `v1.1.0`, commit `7a47a63eb81d00ae92ec2e190833f224cdaa47e2`.
- EXE SHA-256: `44d56a00755543a2e6d2f6943780765ceabc9eaedfba3d8e1ee4c07492e9eb7e`.
- Paired controller: 0.27.0 / CARRIAGE_V20, source tree
  `f4e591ce27c4feb0746d4750c54116465140fcfd`.
- Optional manual-flash HEX SHA-256:
  `74dcd008c9080934cf03124f0abefb71a32f23363ad345ce2f9518a86203b177`.
- Published assets: EXE, matching EXE checksum, controller HEX, build manifest
  and validation report. Only the app is installed by Check for Updates.

The full native C++/Qt regression harness passes with independent Qt fixtures
in separate processes. C++ policies/sketch checks total 222974. Additional
updater (13 cases), UI boundaries, carriage, keypad, health, timing and complete
virtual-machine cycle checks pass. A manual-registration display crash and
simulator keypad re-enabling issue found during preparation were fixed; status
labels no longer restyle unchanged values on every refresh.

The exact packaged EXE passed isolated startup on both the offscreen and native
Windows Qt platforms, including HTTPS access to GitHub and the updated keypad.
A frozen test installation running the original v1.0.2 update helper replaced
itself with this EXE and restarted it; sentinel cut-list/history files survived.
This is an isolated helper/restart test, not a live machine update or motion test.

After publication, anonymous API/update checks detect v1.1.0 from v1.0.2.
The public EXE was downloaded, its checksum matched the tested local build,
the public manifest matched the tagged commit and v1.1.0 did not offer itself
again. The original v1.0.2 updater also selects the correct app/checksum assets.
Both GitHub branches (`master`, `teensy-only`) were fast-forwarded to the
release source; old releases and the legacy Mega tag remain available.

Evidence is under `tmp/release-1.1.0`; published manifest/validation assets
record the distributable hashes and test outcomes. Pre-fix failure logs are
retained separately. The operator's source app was left running, its modified
`cutlists.json` was preserved outside commits, and no firmware flash, serial
motion, Home or valve command was sent during release preparation.
