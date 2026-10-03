# Retention Qualification

Date: October 3, 2026, Asia/Yekaterinburg.
Tested implementation: `53dbd71b94d8f08b449902b1249f8a1f2e052179`.
The subsequent qualification commit changes documentation only. No remote push,
merge, release or live database migration was performed.

## Results

| Installation / Host Interpreter | Default Suite | Actual Linux Container Suite |
| --- | --- | --- |
| Editable source, Windows Python 3.13.14 | 434 passed, 22 skipped; 17.66 s | 21 passed; 34.15 s |
| Fresh installed wheel, Windows Python 3.12.10 | 434 passed, 22 skipped; 19.34 s | 21 passed; 39.64 s |

Twenty-one default skips are opt-in container checks, all exercised in the
separate Docker suite. The Windows symlink-privilege case remains skipped.
Environment runs repeat cases; counts are not summed as independent scenarios.
Timings are observations, not benchmarks. No test failures were encountered.
Earlier checkpoints passed 159 focused cases and, before the additional
unresolved-cleanup guard, 432 default cases plus all 21 Docker cases.

## What Was Qualified

`review prune` previews up to 100 explicit terminal IDs without modifying the
store. Apply requires confirmation and a store/record-bound preview digest.
Payloads are replaced atomically with permanent non-executable markers.
Pending, approved, claimed, missing-receipt and unresolved-cleanup records are
refused. Pruning does not remove independent copies in the version catalog.

`catalog retire` adds an immutable marker while retaining the original version
and proof. Later preparation snapshots and re-promotion are refused. Existing
proposals and preparations that already acquired an active snapshot are not
revoked. This snapshot boundary is explicitly tested, not a global kill switch.

Synthetic tests cover bounded selections, no-content previews, stale plans,
wrong-store binding, confirmation, process contention, thread retirement,
transaction rollback, lost commit acknowledgement, payload sizes, policy drift,
schema-1 read-only compatibility, schema-2 upgrades and failed upgrade rollback.
Future-schema tests now use version 99 because version 2 is supported.

The new actual-container workflow executes a packaged demo, promotes its valid
receipt, prunes its review through the CLI, refuses replay, executes separately
approved catalog reuse, then retires the version and refuses further preparation.
The full earlier containment/regression suite also passed. Fixtures use only
hand-written code and synthetic data, not model output or private databases.
Storage failures are injected, not physical outage tests.

Docker Desktop used a trusted local Linux/amd64 engine and immutable image ID:

```text
sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016
```

Owned-container cleanup assertions passed; the final executor-owner listing was
empty. No broad prune or unrelated cleanup occurred. This is Windows-host testing
with actual Linux containers, not native Linux-host default-suite qualification.

## Artifact

```text
evolution_llm_tools-0.1.0-py3-none-any.whl
SHA256: 52f6d09bd8e9fbebb0aa42970d2f8a2ebf59b2c275f9c0a4737648ff533df8e5
```

The fresh wheel environment loaded review/catalog modules from site-packages.
Default tests ran outside the repository; the container harness used the installed
interpreter. All 23 Python modules matched source bytes. Its 29 archive entries
contained no checked runtime database/environment/cache artifacts. `pip check`
and installed `review prune --help` / `catalog retire --help` passed. Inventory
checking is not an independent comprehensive security audit; no sdist was qualified.
The artifact predates this documentation-only report/README update.

## Limits And Next Gates

The [retention policy](retention.md) deliberately provides logical payload
removal, not secure erasure, physical compaction, bounded total disk usage or
catalog deletion. Unresolved cleanup receipts cannot yet be marked resolved by
an operator API. Permanent markers do not protect against privileged rewriting
or restoring old databases. Stop old clients before upgrading to schema 2.

This completes the previously outstanding local retention implementation and
qualification checkpoint, not a production-release certification. Native
Linux-host CI, privileged Windows symlink checks, model evaluation, external
integration trials and an explicitly approved release remain separate gates.
MCP Memory was not modified or tested.
