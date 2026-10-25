# Beta.26 installation follow-up

The beta.25 public-installer exercise exposed `chmod: follow_symlinks unavailable on this platform` on Rocky Linux 8.10. The installer returned to its previous source/configuration/services; Asterisk PID was unchanged. This was not a successful beta.25 installer acceptance.

Beta.26 replaces both ownership/mode path operations with `O_NOFOLLOW` + `fstat` + `fchown` + `fchmod` on the same descriptor, rejecting symlinks and non-regular/non-directory files. A Linux regression test deliberately disables path-based `chmod`, checks file/directory modes and verifies refusal of a symlink without changing its target.

The automated, telephone, UI and bounded Local-load evidence and limitations remain documented in [beta.25 audit](AUDIT_BETA25.md). Consult the beta.26 commit checks and installer acceptance results before deploying. This remains a controlled-pilot beta, not a claim of universal production compatibility.
