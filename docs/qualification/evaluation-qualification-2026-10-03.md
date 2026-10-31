# Offline Evaluation Qualification

Date: October 3, 2026, Asia/Yekaterinburg.
Tested implementation: `3aa2346b5ba272786be868f554d030d3906dde55`.
Branch: `feat/offline-evaluation-corpus`, local only.
The subsequent qualification update changes documentation, not runtime/tests.

## Results

| Environment | Default Suite | Actual Linux Containers |
| --- | --- | --- |
| Source, Windows Python 3.13.14 | 496 passed, 38 skipped; 38.54 s | 37 passed; 113.21 s |
| Fresh installed wheel, Windows Python 3.12.10 | 496 passed, 38 skipped; 17.99 s | 37 passed; 93.32 s |

Thirty-seven default skips are the explicit Docker cases, all exercised in the
separate suite. The existing local Windows symlink-privilege case remains skipped.
Repeated environment runs do not multiply distinct coverage. Timings are not
model-performance measurements or benchmarks.

The new focused tests initially passed 42 cases in 1.71 s. The first Docker
attempt failed during collection because isolated Python could not import the
shared `tests.evaluation_reference` module from the container test directory.
Adding `tests/container/__init__.py` fixed the package structure; no isolation
flag, test or approval rule was disabled. Both full Docker runs above passed
after that correction. This failed attempt is not execution evidence.

## Corpus And Scope

```text
toolwright-eval-v1
SHA256: c46892beb6f2a6ba1270e48147c9eeab0f09010b789b9a0c68ed9ab5dada0626
```

The corpus contains 16 runnable tasks with one example and two held-out cases
each, plus four policy-refusal tasks. Sixteen new parameterized Docker tests
exercise 48 separately approved handwritten reference inputs. Each checks
refusal before approval and after consumption, exact output, grading, and owned
container cleanup. Every task's three cases passed, including its two held-out
cases. References are not model-generated candidates.

Default tests exercise prepare-only behavior, all 48 synthetic receipt bindings,
unchanged read-only scoring, fixed denominators, inconsistent candidate rejection,
wrong output, fabricated passing flags, missing output evidence, approval checks,
ambiguous/failed/pruned states, stale manifests, refusal labels and direct answers.
No provider was called. Stored receipt fixtures are explicitly synthetic; only
the separate Docker tests establish actual execution of reference code.

The grader does not infer missing latency, tokens, peak memory or cleanup evidence.
These fields remain unavailable where the journal does not record them. Configured
resource bounds are separate from measured utilization. Public held-out data is
excluded from prompts, not secret or contamination-resistant benchmark data.

## Package Evidence

```text
evolution_llm_tools-0.1.0-py3-none-any.whl
SHA256: 170e6dd0cc17dbaf00ad1d8230b6d82fc2b8d282cb6bb09158055299be2d920d
```

The isolated installed-wheel gate passed at the exact clean implementation head.
All 26 module bytes matched source and installation; 32 archive entries passed
the allowlist. Dependency checks, installed `eval --help`, console `eval list`
and the frozen corpus hash passed. No workstation databases/environment artifacts
were included. No sdist or independent comprehensive security audit was performed.
The wheel predates the documentation-only qualification update.

Docker Desktop used local Linux/amd64 image:

```text
sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016
```

Owned cleanup assertions passed and the final executor-owner listing was empty.
No broad cleanup, other-project change, live database migration or MCP Memory
testing occurred. No new branch push, merge, release or hosted CI run occurred.
Hosted results for the earlier `97b4b79` baseline do not qualify this new code.

## Remaining

This delivers the offline corpus, grading and handwritten reference checkpoint,
not the EVO-3 exit gate. Actual model artifact/license/settings review, provider
generation and provenance, latency/resource instrumentation, direct-model and
reuse comparison, two external API users and a release decision remain open.
Real-model quality, production readiness and arbitrary generated-code safety are
not established by these synthetic checks.
