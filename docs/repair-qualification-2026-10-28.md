# Repair Qualification: First Live Repair

Date: October 28, 2026.
Branch: `feat/adaptive-skills`, runtime commit `c1fd56c`.
Model: local Ollama `qwen2.5:7b`, `temperature=0`, `seed=7`, `max_tokens=2048`,
no JSON mode. One repair request per task, no retries.

## Summary

The first live use of [failure-driven repair](repair.md). The five repairable
failures from the [admission run](admission-qualification-2026-10-28.md) were
each given one repair request built only from failed example cases. **One of
five repaired candidates was admitted** (`active-ids`, 8/8 cases). The other
repairs were refused by the format check, returned the unchanged code, or
changed code without fixing the cause.

## Results

| Task | Failure shown to the model | Repair reply | Admission |
| --- | --- | --- | --- |
| active-ids | `NameError`: `sys` not imported | Added `import sys` | **admitted** (3/3 examples, 5/5 held-out) |
| sort-records | `NameError`: `sys` not imported | Returned the original code unchanged | same candidate: ledger returned the earlier refusal, no new slot used |
| date-distance | `reverse`: returned `1`, expected `-1` | Wrapped the date parsing in `try`, kept `abs()` | refused (2/3 examples, 4/5 held-out) |
| csv-projection | `quoted`: "Invalid number of columns" | Added `.strip()`, kept `split(',')` instead of the `csv` module | refused (2/3 examples, 4/5 held-out) |
| run-length | `empty`: returned `[[0, 0]]`, expected `[]` | Code block followed by a stray extra fence line | `invalid_source` (`ambiguous_python_fence`), not executed |

All executions were reviewed and single-use in image
`sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f`;
no owned container was left behind. Held-out details were not inspected.

## Observations

- The guards worked as designed. Repair prompts held no held-out input, the
  strict fence check refused a malformed reply instead of guessing, and the
  admission ledger recognised a repair that only repeated its parent, so it did
  not use up a slot.
- With this model, one repair attempt fixes only the most local defect (a
  missing import). Where the fix needs a different approach (signed rather than
  absolute day difference, a real CSV parser), the reply changes surface
  details and keeps the faulty logic. `sort-records` shows the model can ignore
  the error entirely.
- Including the expected value and the observed output in the prompt was not
  enough to make a semantic fix. A stronger model or a prompt that names the
  violated rule may do better; neither was tried.

## Catalog state

With this repair, 11 of the 16 corpus tasks have an admitted version (10 from
the first admission run plus `active-ids`). Slots used per task: 2 of 3 for
`active-ids`, `date-distance` and `csv-projection`; 1 of 3 for the rest.

## Scope

One model, one seed, five repairs. This shows the repair path works end to end
and where it falls short, not a repair success rate.

A v5 baseline generation was attempted afterwards but was voided: another
workload took the GPU mid-run and most requests timed out.
