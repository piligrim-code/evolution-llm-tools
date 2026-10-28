# Prompt v5 Qualification: Baseline Run

Date: October 28, 2026.
Branch: `feat/adaptive-skills`. Model: local Ollama `qwen2.5:7b`,
`temperature=0`, `seed=7`, `max_tokens=2048`. JSON mode for decisions only.
One request per task, no retries, no transformations. Scored on the frozen
`toolwright-eval-v1` corpus for comparison with earlier runs.

An earlier v5 attempt the same day was voided: another workload took the GPU
mid-run and 14 of 20 requests timed out. This run had the GPU to itself
(4 to 11 seconds per request).

## Results

| Run | Usable sources | Tasks passed | Cases | Held-out | Decisions |
| --- | --- | --- | --- | --- | --- |
| v3 + recorded fence transformation (Oct 21) | 16/16 | 11/16 | 39/48 | 25/32 | 0/4 |
| v4 JSON envelope (Oct 21) | 7/16 | 4/16 | 16/48 | 10/32 | 4/4 |
| **v5, no transformation** | 13/16 | 8/16 | 31/48 | 20/32 | **4/4** |

v5 is the first prompt that gets correct refusals and usable tool sources from
the same run without any after-the-fact transformation. It still scores below
v3 with the fence transformation.

## Where v5 loses

- **3 format refusals.** `group-totals`, `clamp-values` and
  `balanced-parentheses` each ended with two closing fence lines. The strict
  envelope refuses that (`ambiguous_python_fence`). The same habit appeared in a
  repair reply. A likely trigger is the prompt's own wording ("then a ``` line").
  v3 solved all three tasks, so this one formatting habit costs about three tasks.
- **5 tasks failed on execution or output:**
  - `date-distance`: `NameError`, `sys` not imported. This happened despite the
    "Import every module you use" rule.
  - `word-counts`: did not lowercase tokens.
  - `json-project`: dropped a key whose value is `null`.
  - `csv-projection`: crashed on a quoted field.
  - `run-length`: returned `null` for empty input.

Per usable source the two prompts are similar: 8/13 for v5 and 11/16 for v3.

## Next

- Reword the v5 format rule so it does not invite a second fence (a v6), or add
  a recorded, narrow transformation for exactly one duplicated closing fence.
  Either change must be checked live, not assumed.
- The v5 candidates were not submitted for admission, so no admission slots were
  used.

Raw responses and receipts remain private.
