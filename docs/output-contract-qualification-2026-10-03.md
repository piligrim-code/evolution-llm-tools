# Output Contract Qualification

Date: October 3, 2026, Asia/Yekaterinburg.
Tested implementation: `6cd22cfd5d334dbd2462fb42f331fdcee1bdecb4`.
The subsequent report commit changes documentation only. No release, merge or
remote push was performed.

## Results

| Installation / Host Interpreter | Default Suite | Actual Linux Container Suite |
| --- | --- | --- |
| Editable source, Windows Python 3.13.14 | 313 passed, 14 skipped; 11.82 s | 13 passed; 16.16 s |
| Fresh installed wheel, Windows Python 3.12.10 | 313 passed, 14 skipped; 12.18 s | 13 passed; 16.97 s |

Thirteen default skips are the opt-in Docker cases, all run successfully by the
separate harness in each environment. The remaining Windows symlink-privilege
case is still skipped. Repeated runs on two interpreters are not independent
additional test scenarios. Timings are observations, not benchmarks.

An initial focused run had 143 passes and one failure: a new test incorrectly
expected a plain-text contract containing NUL to be accepted. The existing
`bounded_text` rule forbids NUL. That rule was retained, and the case was moved
to invalid-contract assertions. The separate check that actual hidden NUL bytes
cannot pass after display sanitization was retained. All final runs above passed.

## Evidence And Scope

- 61 added default cases cover expected-output validation, strict JSON types,
  altered stdout, missing evidence, binding/removal of assertions, old proposals,
  provider isolation, cleanup precedence, receipt failures and non-replay.
- Four additional actual-container cases exercise the reviewed CLI's
  inspect/approve/execute path for text match/mismatch, JSON match and hidden-NUL
  JSON refusal. Mismatching output fails the CLI even when process exit code is 0.
- Output checks run after confirmed container cleanup. No assertion grants new
  execution permissions, repeats a consumed attempt or promotes a registry entry.
- Existing resource, ownership and isolation controls were not relaxed. Fixtures
  use hand-written synthetic code, not live model-generated output or private data.
- Test cleanup assertions passed and the post-run executor-owner listing was empty.
  No broad prune, unrelated-container cleanup or operational database access occurred.

The same local Docker Desktop Linux/amd64 image as the earlier lifecycle
qualification was used:

```text
sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016
```

The harness resolves the public setup image to an immutable local ID. The
executor itself does not pull images or install tool dependencies.

## Installed Artifact

```text
evolution_llm_tools-0.1.0-py3-none-any.whl
SHA256: c8843272a7b2560efaa3a86b256b4c11a81b0899c01e0c8449a26db2ec8be0c8
```

The new environment imported both `alita.review` and `alita.output_contracts`
from its own site-packages, not an editable checkout. Default tests were launched
outside the source tree; the actual Docker harness also used the installed
environment. All 18 packaged Python modules matched the tested source bytes.
The 24-entry archive had no checked runtime database/environment/cache artifacts.
`pip check` and installed `review propose --help` passed, including the new option.
This inventory is not an independent comprehensive secret/security audit; no
sdist was qualified. Rebuilding after README changes can change the artifact hash.

## Remaining Gates

This validates [the documented assertions](output-contracts.md) on the stated
environments, not general tool correctness or a production release. Matching one
independently supplied expectation is specific to those arguments and the
correctness of that expectation. V1 proposals remain explicitly unvalidated.

The general typed execution-outcome API, immutable working-tool versions,
promotion/reuse and deterministic product demos remain further EVO-2 work.
Native Linux-host default-suite CI, the privileged Windows symlink case,
real-model evaluation and external adoption remain separate gates. MCP Memory
tests and deployments were not part of this task.
