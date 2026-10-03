# Offline Evaluation Corpus

This is preparation for EVO-3, not a real-model quality report. The package adds
a fixed synthetic corpus, candidate preparation and deterministic grading. It
never calls a provider, approves a proposal, executes code or retries an attempt.

## Frozen Tasks

Corpus version: `toolwright-eval-v1`.
Canonical corpus SHA-256 (also pinned by a regression test):

```text
c46892beb6f2a6ba1270e48147c9eeab0f09010b789b9a0c68ed9ab5dada0626
```

Sixteen runnable tasks cover integer sums, stable deduplication, word counts,
grouped totals, active-record filtering, median, clamping, chunking, one-level
flattening, dot products, multi-key sorting, date distance, CSV projection,
JSON projection, run-length grouping and balanced parentheses. Every task has
one demonstration and two additional cases: 16 examples plus 32 held-out cases.
The expected outputs are literal fixture data, not computed by candidate code.

Four refusal tasks request forbidden network access, an unavailable host file,
pip installation or bypassing approval. They have no executable cases, and the
preparation API refuses them before creating a proposal. Supported input shapes
are described by each task; this corpus is not a general malformed-input fuzzer.

Held-out cases are excluded from generation prompts, but are public source data,
not a secret test set or a claim of resistance to benchmark contamination. Inspecting
and approving a held-out execution necessarily reveals its exact input/assertion.
Freeze candidates before inspecting those cases when performing a quality study.

```sh
evolution-tools eval list
evolution-tools eval cases integer-sum
evolution-tools eval prompt integer-sum
evolution-tools eval prompt integer-sum --decision
```

Prompt output includes its SHA-256. Generation prompts for runnable tasks request
source only; `--decision` requests a separate explicit classification. For refusal
tasks, the normal prompt also asks for classification, never executable code.
Prompt printing does not send anything to a provider.

## Prepare And Review

The candidate input is a local JSON scripts object using the existing format:
`{"tool.py":"...","requirements.txt":""}`. The empty requirements field is
optional; execution remains standard-library-only. For an already obtained
candidate and a trusted local immutable image:

```sh
evolution-tools eval prepare integer-sum example --scripts candidate.json --container-image <sha256-image-id> --store private/reviews.sqlite3
evolution-tools review --store private/reviews.sqlite3 inspect <proposal-id> --json
evolution-tools review --store private/reviews.sqlite3 approve <proposal-id> --digest <inspected-digest>
evolution-tools review --store private/reviews.sqlite3 execute <proposal-id> --structured
```

Prepare each selected case independently using its ID from `eval cases` and the
same frozen scripts/image/policy for that task. Every case needs its own normal
inspection and explicit approval. There is no evaluate-and-auto-run shortcut.
Proposal creation supplies the case's fixed arguments and independent output
contract; candidates cannot replace the expected answer.

The library equivalent is
`prepare_case(task_id, case_id, scripts, policy, reviews)` in `alita.evaluation`.
It returns identifiers, corpus hash and pending state, not permission to execute.

## Score Existing Receipts

A manifest contains the current corpus hash and assignments. Each assignment
selects exactly `task_id`, `case_id` and `proposal_id` from the prepare response:

```json
{
  "corpus_sha256": "c46892beb6f2a6ba1270e48147c9eeab0f09010b789b9a0c68ed9ab5dada0626",
  "assignments": [
    {"task_id": "integer-sum", "case_id": "example", "proposal_id": "<actual-proposal-id>"}
  ]
}
```

```sh
evolution-tools eval score manifest.json --store private/reviews.sqlite3
evolution-tools eval score manifest.json --store private/reviews.sqlite3 --details
```

CLI scoring opens the journal read-only and reads one snapshot. The API is
`score_run(reviews, assignments, expected_corpus_sha256=...)`. Manifests permit
at most 48 unique case/receipt assignments; duplicates, unknown cases and stale
corpus hashes are rejected. No source/arguments/output text is echoed in scores.
IDs, source/policy hashes and image identities are still potentially sensitive.

The denominator is always all 48 runnable cases, including missing cases. Example
and held-out totals are separate; a task passes only when all three cases pass.
Different scripts or execution policies across a task's cases produce
`inconsistent_candidate`, even if individually stored receipts say passed.

Scoring rechecks the approved proposal binding, fixed task arguments/contract,
receipt provenance fields and output bytes/hash. A stored passing flag alone is
insufficient. States distinguish missing/unavailable/binding mismatch, not run,
indeterminate, invalid receipt, timeout, execution failure, unknown cleanup,
incorrect answer and correct answer. Pruned receipts are unavailable, not passed.
Policy drift can also make a receipt unavailable under current validation rules.

The journal and local operator remain trusted: manually forged database receipts
are outside the security boundary, as with catalog promotion. The grader cannot
prove which provider generated a candidate, and reports this explicitly.

## Other Baselines And Measurements

`eval answer <task> <case> --answer '<JSON>'` grades a supplied direct-answer
object. `eval decision <task> --decision '<JSON>'` grades a supplied policy label:
`{"action":"prepare"}` or `{"action":"refuse","reason":"<code>"}`. These
functions are available as `score_answer` and `score_decision`. They neither
execute nor verify that a model produced the supplied value. Refusal scores are
not folded into execution correctness: `score_run` reports zero refusal tasks
scored, with four available for this separate classification evaluation.

Answers use exact canonical JSON, including numeric/boolean type distinctions.
Task instructions explicitly require a floating-point median for nonempty input.
No fuzzy matching, model-as-judge or automatic tolerance tuning is used.

Current receipts record stdout byte count and configured execution limits, not
generation latency, execution wall time, peak memory or token counts. Unavailable
measurements are `null`; configured bounds are reported separately, never as
measured utilization. Cleanup is `not_recorded` unless an explicit unconfirmed
cleanup error is present. Do not infer performance or resource efficiency here.

## Verification And Remaining Work

`tests/evaluation_reference.py` contains handwritten baselines, separate from
the literal expectations. The opt-in Docker suite runs every baseline against
all three of its cases, using 48 separately approved contained attempts. Each
fixture checks refusal before approval and after consumption, plus owned cleanup.
These runs qualify the fixtures/harness, not model generation quality.

```sh
python -m pytest tests/test_evaluation.py -q
python tools/run_container_tests.py
```

EVO-3 remains incomplete: actual model artifact/license/settings review,
generation/latency/resource instrumentation, direct-model comparison, reuse-benefit
measurement and at least two voluntary external API users remain separate gates.
No real model run, new execution permission or production-readiness claim is
implied by introducing this offline corpus.
