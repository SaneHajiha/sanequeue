# Historical release snapshots

These files retain assertions tied to older beta version strings, deleted
Windows port-specific launchers, removed survey UI and the pre-beta12 unowned
control gate API. They failed on the supplied beta17 archive before this review.

They are retained for provenance, not run by current discovery. Relevant
authorization, AMI, privacy and UI behavior remains covered by current tests;
the current release also adds runtime and compatibility behavior tests.
Never restore the old permissive gate expectations to make these pass.
