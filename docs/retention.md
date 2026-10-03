# Explicit Local Retention

Retention is manual and scoped to selected records. No timer, startup task,
age threshold, automatic quota or whole-store deletion runs in the background.
Historical review rows have no reliable creation timestamp, so the API does not
invent one or infer age from UUID order.

## Policy

| Data | Default | Explicit Maintenance |
| --- | --- | --- |
| Pending or approved proposal | Retain | Cancel first, then separately preview pruning. |
| Claimed attempt | Retain | Never prune: execution or persistence may be unresolved. |
| Finished receipt | Retain | Prune selected payloads, except missing receipts or `cleanup_unconfirmed`. |
| Cancelled proposal | Retain | Prune selected payloads. |
| Pruned proposal identity | Retain permanently | No deletion, reapproval or reactivation API. |
| Validated catalog version | Retain immutable content and proof | Retire to prevent new preparation snapshots. |
| Retired version | Retain immutable content and proof | No reactivation or content-deletion API. |

An unresolved cleanup receipt retains its resource identity for manual inspection.
This version has no operator-resolution API; even after external cleanup, that
receipt stays non-prunable. Do not rewrite its database state to bypass the rule.

Pruning a review removes its document (source, arguments, policy and expectation),
approval and result from the logical row. It retains the ID, original document
digest and a small marker containing the previous terminal state, a hash of the
old result when present, and removed-payload byte count. It becomes `pruned`.
Normal SQL updates/deletes of a pruned row are refused by triggers. Inspection
returns `document=null`, `result=null` and retention metadata; list/pagination
keep the same identity and position. The original approval cannot be reused.

Promoted catalog versions are independent copies. Pruning the original receipt
does not remove their source/arguments/outputs or original provenance. Promote
before pruning if that independent retained copy is deliberately wanted.
Pruned receipts themselves can no longer be promoted.

## Review Preview And Apply

From a private working directory, use explicit IDs from `review list`:

```sh
evolution-tools review --store private/reviews.sqlite3 prune <id> [<second-id>]
evolution-tools review --store private/reviews.sqlite3 prune <id> [<second-id>] --apply --plan-digest <preview-digest>
```

The first call is a read-only preview. It does not create a missing store, change
its schema, show source/arguments/outputs or execute anything. It reports the
selected IDs, states, document digests and payload byte counts. Digests and IDs
are metadata, not a guarantee that the response is suitable for public sharing.

Apply requires the exact digest of the inspected preview plus a confirmation
prompt defaulting to no. `--yes` supplies explicit noninteractive confirmation;
it cannot replace `--apply` or the digest. Missing/stale digests are refused.

The library equivalent is:

```python
from alita.review import ReviewStore

reader = ReviewStore("private/reviews.sqlite3", read_only=True)
plan = reader.prune([proposal_id])
# Inspect plan and deliberately choose to proceed.
writer = ReviewStore("private/reviews.sqlite3")
result = writer.prune([proposal_id], plan_digest=plan["plan_digest"], confirm=True)
```

Selections contain 1-100 distinct IDs. Order does not affect the plan. The digest
binds the selected records, their payload hashes, states and store path. Changes
to unrelated rows do not invalidate it. The writer reloads all selected rows in
one `BEGIN IMMEDIATE` transaction. A missing, ineligible or changed row aborts
the whole batch; no partial deletion is committed. Plan generation works after
execution-policy drift but still rejects a modified proposal document.

## Version Retirement

```sh
evolution-tools catalog --store private/versions.sqlite3 retire <name> <full-version>
evolution-tools catalog --store private/versions.sqlite3 retire <name> <full-version> --apply --plan-digest <preview-digest>
```

`VersionCatalog.retire(name, version)` previews; pass its `plan_digest` and
`confirm=True` to apply. The same read-only preview, no-by-default confirmation,
store-bound digest and transactional recheck rules apply. Retirement records are
permanent append-only markers, not changes to the immutable version payload.
`inspect` and `list` include `retired`; inspection still returns original proof.
Re-promotion of identical content cannot reactivate a retired version. Other
versions remain independent, with no implicit fallback to an older version.

Retirement blocks preparations whose catalog snapshot observes the committed
marker. A preparation already holding an active-version snapshot may finish
creating a pending proposal. Already prepared or approved proposals are not
revoked; cancel eligible proposals explicitly in their review journals. There
is no cross-store transaction, tracking of every copied proposal, or global
execution kill switch. A deliberate fresh proposal created by another route is
not forbidden by retirement; ordinary approval rules still apply.

## Storage And Compatibility

Writable opens transactionally upgrade review/catalog schema version 1 to 2.
Read-only opens accept both versions and do not migrate. The review upgrade adds
terminal-marker guards; the catalog upgrade adds an immutable retirement table.
Proposal document versions remain unchanged. Back up privately and stop old
clients before upgrading; do not run mixed old/new binaries against these files.
Older binaries reject schema 2 when opening; already-open old handles are not
remotely revoked. No downgrade command or automatic restore is provided.

This is logical payload removal, **not secure erasure**, physical compaction or
a fixed disk quota. SQLite free pages, journals/WAL, backups, exported files and
catalog copies may retain content. No automatic `VACUUM`, checkpoint, backup
deletion or filesystem wipe runs. Plan byte counts describe selected payloads,
not disk space guaranteed to be reclaimed. Tombstones and catalog history still
grow; whole-store lifecycle management remains the operator's responsibility.

The operator and storage directory remain trusted. A privileged writer can drop
triggers or restore older files; hashes/markers are not defenses against that
attacker. Never restore an old approved snapshot as a retry mechanism. On lost
commit acknowledgement, reopen and inspect affected IDs/versions: do not assume
the mutation rolled back, and do not automatically retry execution.

## Verification

```sh
python -m pytest tests/test_retention.py -q
python -m pytest tests -q --tb=short -ra
python tools/run_container_tests.py
```

Synthetic tests cover bounded previews, stale plans, permanent IDs, process
contention, rollback, lost acknowledgement, old-schema upgrades and confirmation.
The actual-container case executes a demo, promotes it, prunes its review,
performs separately approved reuse, then retires the version and refuses further
preparation. Fault injection is synthetic, not a storage/daemon outage test.
