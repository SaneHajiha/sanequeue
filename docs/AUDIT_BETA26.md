# Beta.26 installation follow-up

The beta.25 public-installer exercise exposed `chmod: follow_symlinks unavailable on this platform` on Rocky Linux 8.10. The installer returned to its previous source/configuration/services; Asterisk PID was unchanged. This was not a successful beta.25 installer acceptance.

Beta.26 replaces both ownership/mode path operations with `O_NOFOLLOW` + `fstat` + `fchown` + `fchmod` on the same descriptor, rejecting symlinks and non-regular/non-directory files. A Linux regression test deliberately disables path-based `chmod`, checks file/directory modes and verifies refusal of a symlink without changing its target.

The automated, telephone, UI and bounded Local-load evidence and limitations remain documented in [beta.25 audit](AUDIT_BETA25.md). Consult the beta.26 commit checks and installer acceptance results before deploying. This remains a controlled-pilot beta, not a claim of universal production compatibility.

## Completed public-release acceptance

- GitHub PR [11](https://github.com/SaneHajiha/sanequeue/pull/11): all three Linux jobs (Python 3.10, 3.11, 3.12 with Redis) passed on commit `1d58f70217d5d4688ee0351f48a9a2a2eba6c675`. The master tests and prerelease validation also passed for `13754659f91c5c7a6df2bdeac44c99e9f7042ab5`.
- Published [beta.26](https://github.com/SaneHajiha/sanequeue/releases/tag/v2.1.0-beta.26) ZIP/tar.gz downloaded publicly and matched SHA256SUMS.
- The published one-file installer completed on Rocky Linux 8.10 with exit **0**. Login, existing accounts and both discovered queues remained available. Web, collector, Redis and Asterisk services were active; Asterisk PID was unchanged.
- All **366** installed runtime/source/assets files checked matched the published Git tree exactly, including the bundled callback prompt.
- Post-install operations, telephone module, notification and personal activity APIs returned 200. The supported telephone adapter remained applied and the four existing callback report rows were retained.
- Live browser queue cards showed the correct distinction between no-ready-agent and healthy states, without horizontal overflow. Callback report displayed verified target connection and the observed duration rounded to 23 seconds; older unverified rows retained unknown timestamps.

Gemini could not retrieve the newly published sources from its web search. Its initial response explicitly described hypothetical architecture risks. Sending source text was interrupted by the Chrome connection; **no independent Gemini source-code approval is claimed**.
