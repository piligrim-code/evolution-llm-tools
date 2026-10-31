# Toolwright Qualification Checkpoint

Date: October 7, 2026.
Tested revision: `251fd00f4f0ce16680eb41a5772d754a79517ab6`.
This summary records completed checks, not a production-release certification.

## Completed Work

Catalog reuse has an offline regression test covering fresh approval, rejection
of an old digest for changed arguments/contracts, and a typed execution refusal
without a saved receipt or consumed approval. Approval alone does not execute.
Original receipt and catalog contents remain unchanged. Documentation clarifies
that identical documents may share a digest but require separate proposal approval.

## Results

| Check | Result |
| --- | --- |
| Catalog and retention tests | 85 passed |
| Full source-tree suite | 679 passed, 38 skipped |
| Installed-wheel suite, Windows / Python 3.13.14 | 679 passed, 38 skipped |
| Installed dependencies (`pip check`) | Passed |
| Wheel inventory and source/installed bytes | Matched: 36 entries, 30 modules |
| Separate Linux-container suite, Windows host | 37 passed, no failures/errors/skips; 94.14s |

Wheel SHA256:
`6b92d438382ab8f8f2efd8a402beb05214c1690e107ac5126096ccff17d3719e`.

The container suite resolved `python:3.12-slim` to the immutable local image ID:
`sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f`
(`linux/amd64`). This identifies the tested image, not a registry digest.

Container checks covered containment and resource limits, reviewed execution,
output contracts, three deterministic demos, catalog reuse/retirement, typed
failures, and 16 handwritten evaluation tasks. Per-owner cleanup assertions passed.

## Limits And Remaining Gates

The 38 offline skips comprise 37 opt-in container cases and one unavailable
Windows symlink test. Requiring symlink coverage explicitly produced one failure
(`WinError 1314`), with 679 passed and 37 skipped. That requirement was not met;
the normal Windows qualification mode passed with the recorded skip.

The separate container run does not qualify the full suite on a native Linux host
or establish fresh hosted CI results for this revision. Strict symlink coverage
and a current hosted platform matrix remain outstanding.

No new model generation was performed. Handwritten reference successes are not
model-quality evidence: the previously evaluated model candidate remains limited
to one integer-sum task, with 3 correct and 45 missing corpus cases. Private
journals, raw logs and machine-specific evidence are intentionally not included.

No push, merge, release or deployment was performed for this checkpoint.
