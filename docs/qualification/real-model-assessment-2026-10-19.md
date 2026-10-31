# Real-Model Candidate Assessment

Date: October 19, 2026.
Repository branch: `feat/measured-generation-results`.
Assessed runtime: commit `c3ab773` (runtime modules unchanged from hosted-tested
commit `e163644`).

## Summary

The implementation and containment workflow are well-tested. The available
real-model evidence is much narrower: it covers one generated integer-sum
candidate, after an explicit recorded source transformation, on a small number
of cases. It does not show that Toolwright reliably generates useful tools across
tasks.

The unchanged candidate source SHA256 was
`dd32760d335e2273e4e2c8c3b8df2c535bb00ecc70c88447c685b9b5ada6831c`. The raw
model response and workstation execution receipts remain private.

## Candidate Probes

Four additional valid inputs were each prepared as a separate pending review,
explicitly approved, executed once in a disposable Linux container, and checked
against an independently supplied output contract:

| Probe | Result |
| --- | --- |
| Negative values with cancellation | Correct (`0`) |
| Integer above JavaScript's exact-number range | Correct (`9007199254741000`) |
| Duplicate values | Correct (`8`) |
| 2,000 integer values | Correct (`2000`) |

All four passed. End-to-end operator-observed times, including Docker control,
journal writes and cleanup, ranged from 1.89 to 2.42 seconds. They are not tool
runtime benchmarks.

Five malformed inputs were also reviewed and run once:

| Input issue | Observed behavior | Assessment |
| --- | --- | --- |
| Missing `values` field | Returned sum `0` | Not rejected |
| Boolean in values | Returned sum `3` (`bool` is accepted by Python arithmetic) | Not rejected |
| Float in values | Returned sum `3.5` | Not rejected |
| Null values | Nonzero exit, empty stdout, traceback on stderr | Rejected, but error handling is rough |
| String in values | Nonzero exit, empty stdout, traceback on stderr | Rejected, but error handling is rough |

Therefore the candidate passed **4/4** tested valid robustness inputs and
explicitly rejected **2/5** malformed inputs under the checked policy. This is a
small, task-specific probe, not a statistical quality estimate. Each attempt
required fresh approval, consumed its approval once, saved a receipt, confirmed
owned-container cleanup and left no owned container running. No retries,
regeneration, candidate edits or model requests occurred during these probes.

## Generation And Corpus Evidence

Earlier operator records contain four generation requests across the original
prompt and prompt-v2 pilots. The first integer-sum response included a Markdown
fence and reversed the required argv positions. Prompt v2 corrected the argv
positions in one response but still returned a fenced source, which the source
checker correctly refused. An explicit provenance-bound fence transformation
produced the candidate assessed above. The two refusal-task responses were
correct in those limited attempts.

The official frozen evaluation corpus remains **3 correct / 48 runnable cases**
and **1 of 16 runnable tasks passed**, with 45 cases missing. The four valid and
five invalid probes in this report are not added to that score or represented as
held-out corpus results. The 48 handwritten reference executions qualify the
harness and containment, not model quality.

## System Checks And Limits

At `c3ab773`, the installed-wheel qualifier passed with **679 passed, 38
skipped**; all 30 Python modules matched the existing wheel and source bytes.
The exact runtime commit `e163644` passed hosted CI on Ubuntu 24.04 and Windows
2022 with Python 3.12/3.13, including required symlink coverage and 37 actual
container tests on each Ubuntu job. `c3ab773` changes documentation only.

No generation call was made on October 19. There is no current comparison of
direct-model answers versus generated-tool answers, repeated-seed reliability,
cross-task pass rate, general invalid-input behavior, peak memory or production
workload latency. Container containment does not establish resistance to every
escape or production/multi-tenant readiness.

## Conclusion

Toolwright's review, single-use approval, output-validation and container-cleanup
mechanisms have strong automated evidence. The model-generation feature remains
experimental: one narrowly successful candidate, weak malformed-input handling,
and very low measured corpus coverage. Do not describe the project as reliably
generating production-ready tools. The next quality gate should be a separately
budgeted, predeclared multi-task model evaluation with a frozen prompt, exact
model artifact/license review, bounded request count and no automatic retries.
