# Release management / نسخه‌بندی

SaneQueue follows [Semantic Versioning](https://semver.org/):

- `2.0.0-beta.1`: recovered prototype for internal review (not production).
- `2.0.0-beta.2`: follow-up validation and defects fixed.
- `2.0.0-rc.1`: release candidate after staged AMI testing.
- `2.0.0`: stable only after deployment acceptance and rollback test.

## Branches

- `master`: protected stable history; avoid direct development commits.
- `work-recovery-2026-10-22`: recovered work in review.
- `feature/<scope>`, `fix/<scope>`, `release/<version>`: short-lived branches.

## Checklist

1. Ensure `VERSION`, project version and `CHANGELOG.md` agree.
2. Run tests on supported Python versions and JavaScript syntax checks.
3. Confirm no secrets, credentials, SSH keys, call logs, recordings, databases, or runtime configuration are committed.
4. Review MIT attribution to QPanel.
5. Test login and queue-scoped access using fake AMI.
6. Test actual PBX commands *only on test calls*, including failure cases and staffing safeguards.
7. Review translations, RTL layout and accessibility on desktop/mobile.
8. Merge approved PR to stable branch, create an annotated `vX.Y.Z` git tag, then publish release notes and checksum of distribution archive.
9. Keep prior release package and config backup for rollback.

### Local release commands

```bash
python -m unittest tests.test_sanequeue -v
python -m compileall -q qpanel
node --check qpanel/themes/qpanel/static/js/operations.js
git tag -a v2.0.0-beta.1 -m "SaneQueue 2.0.0 beta 1"
git push origin v2.0.0-beta.1
```

Do **not** tag a build that has not passed the stated acceptance checks. The tag commands above are an example, not an instruction to publish now.
