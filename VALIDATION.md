# Baseline validation — 2026-10-27

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
