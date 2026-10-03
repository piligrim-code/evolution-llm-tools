# Reviewed Tool Lifecycle

The `review` commands add a separate proposal -> inspection -> approval ->
single execution attempt path. A proposal is not a working tool. Drafting calls
Ollama but does not invoke Docker, install dependencies, execute generated code,
or register anything in the legacy tool registry. Inspection, approval and
cancellation need neither Ollama nor Docker.

This is an experimental local workflow, not a multi-user authorization service.
The existing `run`, `tool-run` and `--unsafe-exec` semantics are unchanged;
they do not acquire review receipts automatically. Use `review` when you need
per-artifact inspection before execution. There is no unsafe-host fallback in
this path.

## CLI Walkthrough

Use a trusted immutable image already present on your local Linux Docker engine
as described in [container execution](container-execution.md). The following
shell placeholders are values you supply, not image tags or automatic pulls:

```sh
evolution-tools review propose "Count characters in the supplied text" --name text_length --container-image <sha256-image-id> --args '{"text":"synthetic"}'
evolution-tools review inspect <proposal-id>
evolution-tools review approve <proposal-id> --digest <inspected-digest>
evolution-tools review execute <proposal-id>
evolution-tools review inspect <proposal-id> --json
```

Read the entire source, input/output description, exact arguments and policy
before approving. The confirmation defaults to **no**; EOF or cancellation does
not approve. `--yes` is explicit confirmation for callers that have already
reviewed that digest, not a substitute for reviewing generated code. Never let
the generating model call `approve` or control your operator shell/database.

`propose` defaults to the configured model (currently `qwen2.5:14b`); `--model`
overrides it for drafting only. Without `--args`, the question supplies declared
string arguments named `text`, `question` or `input`. Other names require explicit
arguments. All declared arguments are required, extra keys are rejected, and
top-level types are checked without coercion. Nested arrays/objects must contain
finite JSON values but do not yet have nested schemas. Output is bounded text;
its description is not a runtime-validated output schema.

`review cancel <proposal-id>` permanently cancels a pending or approved proposal.
It cannot cancel a claimed/running execution. Changed source, arguments or image
require a new proposal and a new inspection. There is no edit, reset, automatic
retry or approval renewal command.

The default database is `.mcp/reviews.sqlite3` relative to the current directory.
To select another one, put the option before the subcommand:

```sh
evolution-tools review --store /private/local/reviews.sqlite3 inspect <proposal-id>
```

## Find Existing Proposals

Discovery at implementation commit `125ec0d` passed local source and installed-wheel
qualification, including the actual Linux container suite. See
[the exact-commit results and remaining gaps](qualification-2026-10-03.md).

```sh
evolution-tools review list --state pending --limit 20
evolution-tools review list --state claimed --limit 20
evolution-tools review list --state pending --limit 20 --before <next_cursor>
```

Without a state filter, all states are eligible. Supported filters are `pending`,
`approved`, `claimed`, `finished` and `cancelled`; limits are integers 1 through
100. Results contain only proposal ID, state and `has_result`, plus page count,
`next_cursor`, `content_included=false` and `integrity_checked=false`. They omit
source, arguments, names, result text and approval digests. The presence of a
result is not proof of success, cleanup or valid contents. Inspect a proposal
explicitly before approving it; listing never verifies source integrity.

Pages use newest insertion order, not last-update time. Pass the returned cursor
with the same filter for older entries; null means no further matching entries
in that page's snapshot. An invalid/missing cursor is refused rather than silently
restarting at page one. New insertions do not shift older cursor pages, but state
changes between calls can change filter membership: pagination is not a frozen
multi-page audit. Do not restore, vacuum or edit the database while paging.

`list` and `inspect` open the existing database in SQLite read-only/query-only
mode, without creating a missing directory/store or initializing its schema.
They refuse unsupported schema versions. For library discovery use
`ReviewStore(path, read_only=True).list(state="pending", limit=20, before=None)`;
mutating methods on that handle refuse writes. Normal writer handles retain their
existing behavior. SQLite may use ordinary locking sidecars while reading a live
store; read-only here means no application-data/schema changes, not immutable
filesystem metadata.

Use the `claimed` filter to find consumed attempts without a final receipt, then
inspect each one. A claimed attempt may still be running or have an ambiguous
outcome; discovery does not start/stop Docker, reset approval or retry execution.
A corrupt source document can still appear in the list even though inspection
refuses it. IDs and states are metadata and may themselves be sensitive.

## Inspect Exact Content

`inspect` prints source as plain, terminal-sanitized text. `inspect --json` emits
the full escaped JSON record, including exact source characters, for inspection
with a trusted JSON viewer. The SHA-256 digest covers the canonical JSON document,
including source/dependency hashes, contract, exact arguments, immutable image
and the fixed execution profile. It is an integrity fingerprint, not a signature
or proof that the code is safe. A changed profile also invalidates old proposals.
Maintainers must bump the profile identifier when changing execution semantics.

## Local API Without A Model

This hand-written fixture only creates a proposal; it does not execute code:

```python
from alita.container_runner import ContainerPolicy
from alita.review import ReviewStore

store = ReviewStore()
proposal_id = store.create(
    {"name": "length", "args": [{"name": "text", "type": "string"}],
     "output": "Text length"},
    {"tool.py": "import json, sys\nprint(len(json.loads(sys.argv[2])['text']))\n"},
    {"text": "synthetic"},
    ContainerPolicy("sha256:" + "a" * 64),  # Replace with your trusted local image ID.
)
record = store.inspect(proposal_id)
print(record)
```

After independently inspecting that record, an operator may call
`store.approve(proposal_id, inspected_digest, confirm=True)`, then
`store.execute(proposal_id)`. Approval does not execute anything. The API remains
experimental; typed outcome categories and a versioned working-tool registry
belong to the next roadmap stage, not this change.

## Failures And Concurrency

SQLite serializes transitions in a private local database. Execution commits
`approved -> claimed` **before** entering the existing container executor. This
prevents competing threads/processes from consuming the same receipt twice.
Transactions use SQLite full synchronous writes; reliability still depends on
the local filesystem and storage hardware. Do not use a network filesystem.

- `pending`: no approval; execution refused.
- `approved`: one approved attempt remains, with the inspected digest.
- `cancelled`: permanently refused; no execution took place through this receipt.
- `claimed`: the attempt was consumed. It may be running, interrupted, or complete
  without a persisted result. This is **not** evidence of success or failure.
- `finished`: a result or container error was saved, not necessarily a success.

A nonzero exit, timeout or cleanup error consumes the approval. Even preflight
failure consumes it conservatively. Unexpected exceptions, process termination
or result-save failure leave it claimed and cannot trigger replay. A container
error receipt includes the owned-resource name when available. If receipt storage
also fails, that error/resource remains in the raised container exception.

If a result is missing, inspect the owned container on the same trusted engine
before deciding what happened. A hard parent kill may prevent a resource name
from being saved. Do not reset the database or restore an old approved backup
to retry. A new proposal is a deliberate new authorization, not recovery of an
exactly-once distributed operation. No exactly-once guarantee is claimed.

Success is not automatically promoted into the legacy registry. This avoids
both an execution/registration gap and silently turning a one-use receipt into
unlimited reuse. Working-tool versioning/promotion is follow-up work.

## Data And Trust Boundary

The database stores source, contract, arguments and bounded outputs/errors.
Treat it and SQLite sidecars/backups as private: protect the directory with your
OS account permissions, keep `.mcp/` out of Git, and do not submit secrets as tool
arguments. Prompts/provider transcripts are not separately archived, but source,
specs and arguments can themselves contain supplied text. Nothing is uploaded by
the review store; drafting still sends the request to your configured Ollama URL.

The host, operator, database directory, local Docker daemon and selected image
remain trusted. Someone who can rewrite the database or restore its old state
can forge approvals; hashes do not stop that attacker. Linked paths are rejected
but hostile filesystem races/administrators are outside the threat model. The
existing container limits, cleanup rules and kernel-sharing caveats still apply.

## Verification

```sh
python -m pytest tests/test_review.py -q
python -m pytest tests/test_review_discovery.py -q
python -m pytest tests -q
python tools/run_container_tests.py
```

The default suite uses fake providers/executors for review tests, including
independent-process contention, interrupted approval, changed content, changed
policy, cancellation, nonzero exit, cleanup errors and receipt-write failure.
The opt-in Docker suite adds a real hand-written reviewed fixture with confirmed
owned-container cleanup and replay refusal. A skipped Docker test is not evidence
of containment on that machine. No live model or private data is needed by tests.
