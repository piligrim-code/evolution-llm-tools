# Typed Outcomes And Demos Qualification

Date: October 3, 2026, Asia/Yekaterinburg.
Tested implementation: `d895a14005d61658b20ddadf6ceb42603af2c086`.
The subsequent qualification commit changes documentation only. No remote push,
merge or release was performed.

## Results

| Installation / Host Interpreter | Default Suite | Actual Linux Container Suite |
| --- | --- | --- |
| Editable source, Windows Python 3.13.14 | 395 passed, 21 skipped; 17.72 s | 20 passed; 36.65 s |
| Fresh installed wheel, Windows Python 3.12.10 | 395 passed, 21 skipped; 19.86 s | 20 passed; 36.47 s |

Twenty default skips are the opt-in container checks, all exercised successfully
in the separate suite. The Windows symlink-privilege case remains skipped. These
are repeated environment runs of the same cases, not independent scenario counts.
Timings are observations, not benchmark claims. The focused outcomes/demo run
passed 36 cases in 1.31 s. No test failures were encountered in this checkpoint.

## Coverage And Limits

The additive `ReviewStore.execute_result()` API and `review execute --structured`
CLI report typed v2-only outcomes. Tests cover refusal before claim, concurrent
callers, output mismatch, timeout, process/resource failures, cleanup uncertainty,
claim and receipt persistence errors, lost acknowledgements and interruption.
Ambiguous outcomes do not confer success or automatic retry permission. Existing
`execute()` behavior remains covered by the regression suite.

The packaged `text-summary`, `table-totals` and `json-projection` demos prepare
pending proposals only. Their expected outputs are independent literal fixtures.
Actual container tests run all three, exercise independently specified alternate
inputs, validate outputs, promote explicit versions, and require fresh approval
before reuse. Typed timeout and nonzero-exit outcomes also run in actual containers.

Fixtures are hand-written and synthetic; no live model output or private data is
used. Storage and cleanup failure injection is synthetic, not a reproduction of
a physical storage failure or real daemon outage. The demo names do not imply
general-purpose text, accounting or schema engines.

Docker Desktop used a local Linux/amd64 engine with immutable image ID:

```text
sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016
```

Owned-container cleanup assertions passed, and the final executor-owner listing
was empty. No broad prune or unrelated cleanup occurred. Windows-host testing
with Linux containers is not native Linux-host default-suite CI.

## Artifact

```text
evolution_llm_tools-0.1.0-py3-none-any.whl
SHA256: 46113f203154a60adc76ac0fea3c03ec0fd9e14c01957e040fe1f8039859b9df
```

The wheel was built from the tested implementation and installed into a fresh
Python 3.12 environment. Review, outcome and demo imports resolved to site-packages.
Default tests ran from outside the repository; the container harness used that
installed interpreter. All 23 Python modules matched source bytes. The 29-entry
archive contained no checked runtime database/environment/cache artifacts.
`pip check`, installed `demo list`, `demo prepare --help` and
`review execute --help` passed. This inventory check is not an independent
comprehensive security audit; no sdist was qualified.

The artifact predates the documentation-only qualification commit. Rebuilding
after README changes may change its hash without changing runtime code.

## Remaining Work

EVO-2 still needs an explicit retention/retirement/pruning policy and bounded,
reviewed maintenance behavior. Native Linux-host CI, privileged Windows symlink
checks, live-model evaluation and external adoption remain separate gates. These
results do not establish production readiness or arbitrary generated-code safety.
MCP Memory tests remain deferred; that product was not modified.
