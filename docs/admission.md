# Evidence-Gated Admission

Step B of the [adaptive-skills roadmap](roadmap-adaptive-skills.md). A candidate
tool for a corpus task enters the version catalog only after it passes cases it
was not generated from. Nothing in this module generates, approves or executes
code.

## Rules

- **Corpus.** Admission uses [corpus v2](evaluation-corpus-v2.md): 3 example and
  5 held-out cases per tool task.
- **Evidence.** One identical candidate (spec, scripts and execution policy) must
  have a finished, approved receipt for every case of the task, and every case
  must be correct. Mixed candidates, missing cases and unfinished receipts are
  refused before anything is recorded.
- **Every look is recorded.** Scoring held-out receipts is itself a use of the
  held-out cases, so `evaluate` writes the attempt to an append-only ledger
  before returning. There is no unrecorded preview.
- **Budget.** Each task allows a limited number of distinct candidates per corpus
  version (3 by default). Re-evaluating the same candidate returns its first
  decision and uses no budget; a fresh run of the same code cannot buy a second
  look.
- **No hints.** Results report how many held-out cases passed, never which ones.
  Example statuses are reported, since example cases may feed repair. Held-out
  details are available to a human through
  `AdmissionLedger.inspect(attempt, include_held_out=True)` and must never be
  passed to a generation or repair step.
- **Promotion.** `promote` requires explicit confirmation and an admitted attempt.
  It promotes through the first example receipt, so the catalog never stores a
  held-out input.

The ledger is a separate SQLite file whose rows cannot be updated or deleted
(enforced by triggers). Like the review journal, it is local evidence, not
protection against a hostile operator with file access.

## CLI

```sh
evolution-tools eval admission-cases integer-sum
evolution-tools eval admission-prepare integer-sum <case-id> --scripts candidate.json --container-image <sha256-image-id>
# inspect, approve and execute each proposal with `evolution-tools review ...`
evolution-tools eval admission-evaluate manifest.json --ledger .mcp/admissions.sqlite3
evolution-tools eval admission-budget integer-sum
evolution-tools eval admission-promote <attempt> --catalog .mcp/versions.sqlite3 --yes
```

The manifest names the corpus hash, the task and one proposal per case:

```json
{"corpus_sha256": "<toolwright-eval-v2 sha256>", "task_id": "integer-sum",
 "assignments": [{"case_id": "example", "proposal_id": "<id>"}]}
```

## Limits

- Admission covers corpus tasks only. For a tool a user requests, held-out cases
  would have to be supplied with the request; that flow does not exist yet, and
  `catalog promote` still validates a single input for such tools.
- Five held-out cases are a small sample. Passing them is evidence, not proof of
  correctness.
