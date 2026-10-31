# Generation Observation Qualification

Date: October 3, 2026, Asia/Yekaterinburg.
Tested implementation: `a3457b4cbde824d1f84b1634d2bb763d431ca6f8`.
Branch: `feat/measured-generation-results`, local only.
The subsequent qualification commit changes documentation only.

## Results

| Environment | Result |
| --- | --- |
| Source, Windows Python 3.13.14 | 549 passed, 38 skipped; 30.23 s |
| Fresh installed wheel, Windows Python 3.12.10 | 549 passed, 38 skipped; 24.53 s |
| Installed wheel, actual Linux containers | 37 passed, no skips; 108.17 s |

Thirty-seven default skips are opt-in Docker cases exercised separately. The
local Windows symlink-privilege case remains skipped. Repeated runs do not add
distinct scenario counts. Timings are test observations, not model benchmarks.
No pytest failures occurred in this checkpoint. Earlier intermediate suites also
passed before final corpus binding and request-timeout snapshot adjustments.

## Tested Behavior

Predetermined loopback HTTP fixtures cover sync/async measured calls, request
options and optional seed, exact hashes, locally observed elapsed time, immutable
and detached results, missing versus zero provider counters, malformed metadata,
complete-stream requirements, no retry on HTTP errors, legacy compatibility,
client-field snapshotting and frozen-corpus/prompt/response/request binding.

The provider metric allowlist was checked against upstream Ollama v0.32.9
`api/types.go`: six counters/duration fields. Unsupported cache-hit metrics are
not inferred or added. Fields remain unverified provider self-reports; local
elapsed time is a separate measurement. No peak-memory or model-artifact identity
measurement was implemented or claimed.

Evaluation source responses stay unreviewed. Explicit policy decisions may be
graded without preparing or executing anything. Changed text/settings, stale
corpus hashes and incompatible prompts cannot silently reuse a generation record.
Record hashes are not cryptographic proof that a server actually generated code.

No real inference call, model download, external model service or execution of
model-generated code was performed. The Docker suite still uses handwritten
synthetic references and includes 48 separately approved corpus inputs.

## Package Evidence

```text
evolution_llm_tools-0.1.0-py3-none-any.whl
SHA256: d6fe57f5826c42ae1adb28e438b28b5327cccd6f73fed3f6a99cce3bb0ab4580
```

The clean-commit installed-wheel qualifier passed with source and installed
bytes matching for all 28 Python modules and 34 allowlisted archive entries.
Dependency checks and installed imports passed; the frozen corpus SHA remained:

```text
c46892beb6f2a6ba1270e48147c9eeab0f09010b789b9a0c68ed9ab5dada0626
```

Actual Docker used local Linux/amd64 image:

```text
sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016
```

Owned cleanup assertions passed and the final owner-label listing was empty.
No broad cleanup or unrelated project modification occurred. Full local logs
and model inventory stay outside the repository. No sdist or comprehensive
security audit was performed. The wheel predates the documentation-only update.

## Open Gates

This branch has not been pushed or qualified on hosted CI. The earlier published
baseline's matrix does not qualify newly added code. No merge, release, deployment,
private database migration or MCP Memory testing occurred.

Actual model artifact/license/resource review, an explicitly bounded real-model
pilot, full quality and direct-answer/reuse comparison, tool-execution timing/
peak-memory measurement and external API trials remain open. These synthetic
measurements do not establish actual model quality or production readiness.
