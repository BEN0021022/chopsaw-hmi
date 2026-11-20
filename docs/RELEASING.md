# Build and publish a Windows release

Builds use `ChopSawHMI.spec`, `_version.py` and `build.py`. GitHub Releases in
`BEN0021022/chopsaw-hmi` are the public updater channel. The app's EXE version
and the controller firmware version are separate.

1. Commit the intended app version and source changes. Keep operator data out
   of the release commit. `cutlists.json` is editable operator data and is not
   bundled in the executable; publishing excludes its working-copy edits from
   the source-cleanliness check.
2. Use a Windows virtual environment with `requirements.txt` installed. Run
   the updater checks and relevant native-controller/Qt regressions.
3. Run `python build.py --no-bump --no-publish`. This produces
   `dist/ChopSawHMI.exe`, its matching `.sha256` and `release-manifest.json`.
   The manifest records the exact commit, source cleanliness, EXE hash,
   interpreter/dependencies and controller source tree.
4. Test the exact built EXE, including startup and replacement/restart in a
   disposable installation. Keep the operator app and machine disconnected
   from this test. The optional `CHOPSAW_RELEASE_SMOKE_DIR` environment variable
   runs an isolated packaging diagnostic: temporary INI settings/data, no serial
   access, window/report output and automatic exit. It is unused in normal runs.
5. Push the tested source commit. Publish without rebuilding:
   `python build.py --publish-only --notes-file <release-notes-file>`.
   `--draft` stages assets for review. Publishing rejects a dirty/different
   application source commit, changed EXE or mismatched manifest and targets
   the recorded commit explicitly. Write multi-paragraph notes to a UTF-8 file.
6. Verify GitHub's latest stable release contains `ChopSawHMI.exe` and
   `ChopSawHMI.exe.sha256`, and that the public download hashes match. Verify an
   older-version update check detects it and a current-version check does not.

The app selects the exact named EXE and its matching checksum; unrelated
firmware/tools in a release cannot be mistaken for the app. If a published
checksum cannot be retrieved/parsed, the download is rejected. The Windows
update helper waits for the running EXE to exit, replaces only that EXE, then
relaunches it. Settings, cut lists and logs are not replaced by the updater.

For v1.1.0, the paired custom controller is **0.27.0 / CARRIAGE_V20**. The app
does not flash firmware. Preserve old releases and the legacy Mega source tag
for rollback; do not overwrite a published version with different bytes.

Qt integration cases with independent fake clocks/settings run in separate OS
processes (`qt_test_cases.py`), preventing stale Qt objects from one fixture from
entering the next. Preserve failed pre-fix logs separately from final test
results. The v1.1.0 fixes also cover manual material registration without a
cut-list index, simulator keypad re-enabling and redundant status-pill restyling.
