# Baseline validation — 2026-10-27

## Extended live verification and fix — 2026-11-01

- Live pointer testing exposed a real activity-bridge failure: KWin logged
  `Property 'contains' of object KWin::Rect(...) is not a function`.
  The earlier hardware-free suites did not execute activity.js, so they did not
  detect the broken mouse reporting.
- Replaced the unsupported rectangle method with coordinate comparisons using
  half-open bounds. Six new Qt JavaScript regression tests reproduced the
  startup failure before the fix and passed afterward. They cover scaled,
  reversed and vertical layouts, shared edges, gaps, overlap, negative positions,
  geometry updates, hotplug subscriptions and TV-only activity throttling.
  The 15 monitor self-tests also passed after the fix.
- Reloaded only the activity bridge into the active KWin session. No logout,
  session restart or controller restart was performed.
- Repeated live tests with HDMI-A-1 at 150% and HDMI-A-2 at 125%, swapped
  left/right placement at the original scales, and HDMI-A-2 below HDMI-A-1.
  A temporary virtual mouse moved to the center of both displays in every layout.
  Captured production D-Bus traffic confirmed both `Mus:` output transitions
  and `TV-aktivitet: mus` in all three layouts after the fix.
- Initial measurement attempts were aborted when feedback lag prevented precise
  pointer positioning; their finally blocks restored display settings. The final
  successful pass waited for fresh KWin samples between pointer movements.
- Final checks found no differences in output scale, position, enabled state,
  mode, rotation or priority. All tracked windows had their original output,
  geometry, minimized state and maximization state; the cursor returned to its
  saved coordinates. A minimized Spotify window needed temporary unminimizing
  to accept its original size before being minimized again.
- Temporary KWin scripts and the virtual input device were removed. The fixed
  production bridge remains loaded. topcec.service remained active, and no new
  activity.js errors appeared during the final pass.

## Follow-up verification — 2026-11-01

- All six documented hardware-free suites passed: 15 monitor self-tests,
  6 CEC power tests, 9 fixed-behavior tests, 7 historical tests, and the
  queue/error-recovery and KDE settings assertion scripts.
- Live KDE Wayland session: topcec.service was active before and after testing.
  HDMI-A-1 used 1920x1080 at 125% scale (1536x864 logical geometry);
  HDMI-A-2 used 1920x1080 at 100%, positioned at logical x=1536.
- A process-verified Firefox web-app window was moved from HDMI-A-1 to HDMI-A-2
  and back with a temporary KWin script. Captured production bridge D-Bus
  snapshots reported both transitions. The script restored the original output,
  frame geometry and active window, then was unloaded and removed.
- Live KDE AC display timeout changes were observed by the running controller:
  300 -> 600 seconds -> disabled -> 300 seconds. The original powerdevilrc was
  restored byte-for-byte and verified. No service restart was needed.
- During observation, the running controller independently issued its normal
  idle OFF and logged confirmed TV standby. No explicit CEC command was sent
  by the test. Physical TV state and a complete OFF/ON cycle were not verified.
- Display resolution, scaling and arrangement were inspected, not changed.
  Login/reboot, display hotplug and physical mouse movement were not tested.
  No application source changes were needed.

## Original baseline results

- 17 original files copied byte-for-byte. SHA-256 checked against both originals
  and SNAPSHOT.json after copying and testing. Source installation unchanged.
- monitor.py built-in self-test: 11 tests passed.
- check_fixed.py: 9 tests passed, including activity-driven ON retry cooldown.
- check_cec.py: 7 historical tests passed. This older suite uses the old activity
  call pattern; its no-retry test does not supersede check_fixed.py's current API coverage.
- test_cec_live.py: mocked queue/error-recovery assertions passed.
- test_kde_settings.py: settings parsing and runtime timeout-change assertions passed;
  its existing syntax compilation check also passed for every controller Python file.
- Tests ran against the copied monitor, never the installed monitor. Historical
  import paths were redirected in memory; preserved test files were not edited.
  The runner blocks actual process launch, device access, network connections and
  process signals. CEC-looking test output comes from mocks, not hardware commands.
- Manual source review and pattern scan of the selected snapshot found no private
  keys, GitHub tokens, AWS access keys, common API tokens, literal password/secret
  assignments or credential-bearing URLs. This bounded scan is not proof that
  arbitrary secrets can never be present. Local paths and input device identifiers
  are deliberately retained and documented.
- No logs, backups, cache, credentials, unrelated user configuration or third-party
  research source trees were copied. Test output stayed outside the repository.
- No controller startup, service reload/restart, CEC command, input-device read,
  KWin script loading or installation modification was performed for validation.
- Hardware behavior, desktop integration and login/reboot startup are not verified
  by these hardware-free tests. No new software license was inferred or assigned.
