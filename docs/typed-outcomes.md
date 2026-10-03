# Typed Execution Outcomes

`ReviewStore.execute_result(proposal_id)` adds a typed result for a single reviewed
attempt. It does not replay, approve, repair or promote anything. The existing
`execute()` method, its exceptions and raw persisted receipts remain unchanged.

The new method accepts only v2 proposals with independent output assertions.
An approved v1 proposal is refused before consumption, not silently relabeled
as validated. Deliberate legacy callers may continue to use `execute()`.

## API And CLI

```python
from alita.outcomes import ExecutionStatus
from alita.review import ReviewStore

store = ReviewStore("private/reviews.sqlite3")
# Use an already inspected and explicitly approved v2 proposal ID.
outcome = store.execute_result(proposal_id)
if outcome.status is ExecutionStatus.SUCCEEDED:
    print(outcome.result["stdout"])
else:
    print(outcome.status.value, outcome.reason)
# Do not wrap this call in an automatic retry loop.
```

The corresponding explicit CLI mode is:

```sh
evolution-tools review execute <proposal-id> --structured
```

It prints `ExecutionOutcome.to_dict()` and exits 0 only for `succeeded`, otherwise
1. Without `--structured`, previous output and exit behavior are retained.
CLI parsing/store-initialization failures occur before an attempt and retain the
existing error path (exit 2, not necessarily an outcome JSON object). The library
likewise requires a successfully opened ReviewStore handle.

`ExecutionOutcome`, `ExecutionStatus` and `CleanupState` are importable from
`alita.outcomes`. The frozen dataclass contains a caller-owned result dictionary;
it is not a tamper-proof authorization object. `to_dict()` copies that payload.
The catalog still validates the persisted review receipt, never a caller-supplied
outcome object or boolean flag.

## Statuses

| Status | Meaning |
| --- | --- |
| `refused` | This invocation did not consume approval: missing/already-used approval, readonly handle or missing output contract. |
| `invalid` | Invalid proposal before claim, or a completed output/result that did not satisfy the contract. See consumption and receipt fields. |
| `timeout` | The container executor reported its execution deadline. Cleanup and persistence still have explicit fields. |
| `failed` | Known process/resource/container failure, or inability to access the review before claiming. |
| `cleanup_unknown` | Container removal could not be confirmed. This overrides apparent success. |
| `indeterminate` | Claim, execution result or receipt persistence could not be confirmed after an unexpected failure. Never infer success or replay permission. |
| `succeeded` | Output matched its independent assertion, container cleanup returned successfully and receipt persistence was acknowledged. |

The `reason` is a fixed code, not the raw exception string. Full tool output is
still private data and can appear in `result`; this is not a sanitized report for
public issue attachments. Known owned-resource names are returned as `resource`
only in the executor's `alita-box-<32 lowercase hex>` form. Raw exception messages,
arbitrary resource text and malformed proposal IDs are not echoed.

## Per-Invocation Evidence

The JSON envelope has `schema_version=1`, `proposal_id`, `status`, `reason`,
`approval_consumed`, `cleanup`, `receipt_saved`, `result`, `resource` and
`automatic_retry_allowed=false`.

- `approval_consumed=true`: this call received confirmation of the claim commit.
- `approval_consumed=false`: this call never attempted a claim. It does **not**
  mean the proposal is available: another call may already have consumed it.
- `approval_consumed=null`: the claim may have committed, but confirmation failed.
- `receipt_saved=true`: this call received persistence acknowledgement, including
  for a saved failure receipt. It does not imply a correct result.
- `receipt_saved=false`: this call did not attempt receipt persistence. A receipt
  from an earlier invocation may still exist.
- `receipt_saved=null`: persistence was attempted but acknowledgement failed;
  the row may be claimed or already finished. Inspect deliberately, never replay.
- `cleanup=not_started`: this call did not enter container creation.
- `cleanup=confirmed`: owned-container removal was confirmed, not that the tool
  answer is correct or all host/IO health conditions are known.
- `cleanup=unknown`: removal is not confirmed. Reconcile only the owned resource
  on the same trusted engine; do not use broad cleanup/prune commands.

These fields are tracked within the invocation, not inferred by rereading a
potentially changed global row after an exception. A receipt-write failure after
a correctly validated execution is therefore `indeterminate`, even if its
in-memory `result` contains a passing check. A lost commit acknowledgement may
leave a finished row; subsequent attempts still refuse rather than execute again.

`result` preserves raw process return codes separately from the high-level status.
For example `returncode=0` with failed output validation is `invalid`, not success.
The output assertion remains specific to the reviewed arguments and expectation.
An envelope never grants additional execution or reuse permissions.

Ordinary exceptions are classified; `KeyboardInterrupt`, `SystemExit` and hard
process termination are not converted into success or swallowed. They may prevent
an envelope from being returned. Existing claimed-attempt/non-replay rules still
apply. A container error's original code remains inspectable in a saved raw
receipt when persistence succeeded. There is no schema migration or model call.

## Verification

```sh
python -m pytest tests/test_outcomes.py -q
python -m pytest tests -q --tb=short -ra
python tools/run_container_tests.py
```

Synthetic tests cover refusal, concurrent callers, missing/legacy proposals,
output mismatch, resource failures, preflight failure, cleanup uncertainty,
claim/receipt-write failures, lost acknowledgement and interrupt propagation.
Actual Docker fixtures cover typed success, timeout, nonzero exit and independently
validated demo reuse. Cleanup/storage fault injection is synthetic, not a claim
that a real daemon outage or physical storage failure was reproduced.
