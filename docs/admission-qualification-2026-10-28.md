# Admission Qualification: October 21 Candidates

Date: October 28, 2026.
Branch: `feat/adaptive-skills`, runtime commit `f6d72ab`.
Corpus: `toolwright-eval-v2`
(`531a8347ac1cca7e024c2b74308b620d5971fe917619821a75203d75df2031c9`).

## Summary

The first real use of [evidence-gated admission](admission.md). The 16 tool
candidates from the October 21 `qwen2.5:7b` prompt-v3 run (sources after the
recorded fence transformation, unchanged since) went through admission on
corpus v2. **10 of 16 were admitted** and promoted into a local catalog. No model
request was made.

`chunk-list` shows what admission adds. On v1 it passed all three cases and
counted as solved; on v2 it passes the same three (now example) cases but fails
one of the five fresh held-out cases, so it is not admitted. Without held-out
cases it would have entered the catalog as a false admission.

## Procedure

- For each task with a candidate, all 8 cases were prepared, inspected, approved
  and executed once in image
  `sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f`
  (no network, read-only root, 10 second timeout). 128 executions, no retries,
  no owned container left behind.
- Each task's receipts were evaluated once by `AdmissionLedger.evaluate`, using
  one of three candidate slots per task.
- The 10 admitted attempts were promoted with explicit confirmation, each through
  its first example receipt.
- Held-out details were not inspected and are not reported here, so the cases
  stay unseen for later repair work.

## Results

| Task | Examples (3) | Held-out passed (5) | Admitted |
| --- | --- | --- | --- |
| integer-sum | 3/3 | 5 | yes |
| stable-unique | 3/3 | 5 | yes |
| word-counts | 3/3 | 5 | yes |
| group-totals | 3/3 | 5 | yes |
| active-ids | 0/3 (`NameError`) | 0 | no |
| median | 3/3 | 5 | yes |
| clamp-values | 3/3 | 5 | yes |
| chunk-list | 3/3 | 4 | **no** |
| flatten-once | 3/3 | 5 | yes |
| dot-product | 3/3 | 5 | yes |
| sort-records | 0/3 (`NameError`) | 0 | no |
| date-distance | 2/3 | 4 | no |
| csv-projection | 2/3 | 4 | no |
| json-project | 3/3 | 5 | yes |
| run-length | 2/3 | 5 | no |
| balanced-parentheses | 3/3 | 5 | yes |

v1 counted 11 tasks as passed; v2 admission accepts 10. The five other refusals
match the failures already known from the October 21 run, which all appear in
example cases. That makes them valid input for repair (step C), since repair may
use example failures only.

## Scope

One model, one prompt, one seed, 16 synthetic tasks. The October 21 v4
candidates were not submitted: they were weaker and would have spent a second
candidate slot per task. Receipts, the ledger and the catalog remain private
workstation evidence.
