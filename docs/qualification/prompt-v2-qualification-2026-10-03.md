# Prompt V2 Qualification

Date: October 3, 2026, Asia/Yekaterinburg.
Tested implementation: `b0e4d88d9dd4286f12cfa79bb3446e36595b4055`.
Branch: `feat/measured-generation-results`, local only.

## Results

| Environment | Result |
| --- | --- |
| Source, Windows Python 3.13.14 | 606 passed, 38 skipped; 22.85 s |
| Fresh installed wheel, Windows Python 3.12.10 | 606 passed, 38 skipped; 19.93 s |

The 38 skips are 37 opt-in Docker tests and one local Windows symlink-privilege
test. Docker was not rerun in this checkpoint: changes concern prompt text and
offline generation assessment, not execution/container policy. Prior Docker
results qualify the prior implementation, not this new commit. No model calls,
generated-source execution, approval or automatic retry occurred.

The 57 new cases cover frozen v1 prompt/corpus hashes, v2 source/decision/refusal
selection, explicit argv and stdout/stderr instructions, rejection of unknown
versions and cross-version relabelling, malformed response handling, size bounds,
warning privacy, syntax failures and non-execution. A deliberately reversed argv
fixture remains unreviewed despite valid syntax: semantic correctness is not
implied by the check. Fixtures are handwritten, not production model outputs.

## Artifact Verification

Wheel: `evolution_llm_tools-0.1.0-py3-none-any.whl`.
SHA256: `5e42153102eb05e2f6fcee12ee5cd052fd7fa56aef7b037fa730ef8d73dc1e3b`.

The installed-wheel qualifier ran outside the source tree with Python isolated
mode. Dependencies and installed import checks passed; all 29 Python modules
and 35 allowlisted archive entries matched source/installed bytes. The repository
was clean at the tested commit before and after qualification. Runtime dependency
versions were held to the preceding wheel environment in a fresh virtualenv.
This artifact predates the subsequent documentation-only qualification commit.

Frozen corpus SHA256:
`c46892beb6f2a6ba1270e48147c9eeab0f09010b789b9a0c68ed9ab5dada0626`.
Canonical list of all v1 source/decision prompts SHA256:
`2ef22df001ec9945eaa779abe980881734d8aefa0b5e675f28f02eaffff98099`.

## Intermediate Failures

The first focused run had 145 passes, one failure and four reported fixture
errors. A trailing REQUIREMENTS marker parses as a Python annotation, so it now
has an explicit rejection. Oversized parametrized pytest IDs exceeded Windows'
environment-variable limit; short fixed IDs corrected those setup/teardown errors.
The focused rerun passed 148 cases before four additional boundary/error tests;
both final complete runs passed all 606 cases without errors or failures.

A no-build-isolation attempt lacked the setuptools backend. A subsequent normal
isolated build succeeded without changing the source-test environment.

## Limits And Next Gate

V2 is opt-in. V1 prompt bytes, corpus tasks and legacy capture statuses remain
unchanged. New record fields are additive. V2 syntax checks compile but never
execute source, do not normalize output and cannot prove safety or correctness.
They run in the operator process, not an isolated parser sandbox.

No real-model improvement, production readiness, new hosted CI result, merge,
release or publication is claimed. A separately bounded v2 real-model comparison
and any reviewed contained execution remain future work. Keep historical v1
observations intact and do not rerun prior attempts under a different prompt label.
