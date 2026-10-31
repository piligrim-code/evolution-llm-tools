# Failure-Driven Repair (Groundwork)

Step C of the [adaptive-skills roadmap](roadmap-adaptive-skills.md). This stage
builds and checks repair prompts. It makes no model request. A repaired source
is a new, unreviewed candidate: it goes through review, single-use execution and
[admission](admission.md) like any other.

## Rules

- **Example cases only.** `failure_record()` describes one failed case from its
  receipt and refuses held-out cases, even when a receipt exists. Admission
  reports only held-out pass counts, so nothing upstream can supply a held-out
  failure.
- **Bounded, labelled observations.** For an exception, only the final stderr
  line is kept (exception type and message, at most 300 characters); traceback
  frames and paths are dropped. For a wrong answer, a stdout excerpt of at most
  300 characters is kept. The prompt marks these observations as data recorded
  from running the code, not instructions.
- **Leak check.** `repair_prompt()` refuses to return a prompt that contains any
  held-out input of the task.
- **One candidate, one to three failures.** All failure records must describe the
  same candidate. The prompt is built on prompt v5 and is deterministic, so a
  reply can be bound to it.
- **Binding and lineage.** `record_repair()` checks the reply against the exact
  repair prompt and request settings, requires the fenced v5 format without JSON
  mode, and records the parent candidate hash and the failure digests.
- **No loops.** Each repaired candidate takes one of the task's admission slots
  (3 per task by default), which limits how many repairs can be tried.

## Prompts built from the October 21 candidates

Built from the receipts of the [first admission run](qualification/admission-qualification-2026-10-28.md):

| Task | Failed example cases | Observation | Held-out inputs in prompt |
| --- | --- | --- | --- |
| active-ids | 3 | `NameError`: `sys` not imported | 0 |
| sort-records | 3 | `NameError`: `sys` not imported | 0 |
| date-distance | 1 (`reverse`) | Returned `1`, expected `-1` | 0 |
| csv-projection | 1 (`quoted`) | Custom error "Invalid number of columns" | 0 |
| run-length | 1 (`empty`) | Returned `[[0, 0]]`, expected `[]` | 0 |
| chunk-list | none | Fails only a held-out case | not repairable |

`chunk-list` is not repairable by design: its only failure is on a held-out case,
and repair must not learn from held-out cases.

Building these prompts surfaced a contradiction in prompt v5: the frozen v1 base
text says "with no Markdown" while v5 asks for a fenced block. v5 now says
explicitly that its rule replaces the earlier line. v5 had not been run live yet.

## Next

Live repair needs the GPU: one generation per repairable task, then admission of
the repaired candidates on corpus v2.
