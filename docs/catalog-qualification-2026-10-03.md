# Catalog Qualification

Date: October 3, 2026, Asia/Yekaterinburg.
Tested implementation: `488e8c19271d196cade8e19aa50f2319c3b2adbc`.
The subsequent qualification commit changes documentation only. No remote push,
merge or release was performed.

## Results

| Installation / Host Interpreter | Default Suite | Actual Linux Container Suite |
| --- | --- | --- |
| Editable source, Windows Python 3.13.14 | 359 passed, 16 skipped; 17.67 s | 15 passed; 24.11 s |
| Fresh installed wheel, Windows Python 3.12.10 | 359 passed, 16 skipped; 20.75 s | 15 passed; 30.18 s |

Fifteen default skips are the opt-in container checks, all exercised successfully
in the separate suite. The Windows symlink-privilege case remains skipped. The
two environment runs repeat the same cases; do not sum them as independent
scenarios. Timings are observations, not benchmark claims. An earlier focused
run passed all 187 cases; no test failure was encountered in this checkpoint.

## Coverage And Limits

The 46 added default cases cover explicit confirmation, revalidation of completed
v2 receipts, rejection of fabricated passing flags and unvalidated v1 proposals,
immutable old versions, first-provenance preservation, thread/process concurrency,
initialization/commit failure, readonly/wrong-store guards, paging and policy drift.

Two additional actual Docker tests cover the full CLI sequence: approved
execution, promotion, listing/inspection, fresh pending preparation, refusal
before new approval, independently approved reuse and changed arguments with a
new expectation. They also confirm that an incorrect answer with exit code zero
cannot be promoted. Repeated promotion does not overwrite provenance; successful
reuse does not automatically create a new version. Test-owned cleanup checks passed.

Tests use hand-written synthetic fixtures, not live model output or private data.
Existing container controls were retained. The local Docker Desktop Linux/amd64
engine used immutable image ID:

```text
sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016
```

The post-run executor-owner listing was empty. No broad prune, unrelated
container cleanup or live database migration was performed. This is Windows-host
testing with actual Linux containers, not native Linux-host default-suite CI.

## Artifact

```text
evolution_llm_tools-0.1.0-py3-none-any.whl
SHA256: a8d296d1c828d73db9a3f2b67367efb5f46d9b7d4e1af06239d286550248f269
```

The wheel was built from the tested implementation and installed in a fresh
environment. Both review and catalog imports resolved under site-packages; default
tests were launched outside the source tree and the container harness used the
installed interpreter. All 20 Python modules matched the source bytes. The
26-entry archive contained no checked runtime database/environment/cache artifacts.
`pip check` and installed `catalog --help` passed. This is an inventory check,
not an independent comprehensive security audit; no sdist was qualified.

The artifact predates the documentation-only qualification commit; rebuilding
after README changes may change its hash without changing runtime code.

## Remaining Work

The [catalog contract](version-catalog.md) preserves exact validated configurations,
not a proof of correctness for all inputs or a complete audit of every reuse.
The general typed execution-result API, explicit retention/pruning policy and
three packaged deterministic demos remain EVO-2 work. Native Linux-host CI,
the Windows privileged-symlink case, live model evaluation and external adoption
remain separate gates. No production-release claim is made. MCP Memory tests
remain deferred and that product was not modified by this task.
