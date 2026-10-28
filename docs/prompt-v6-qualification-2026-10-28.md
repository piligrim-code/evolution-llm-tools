# Prompt v6 Qualification

Date: October 28–29, 2026.
Branch: `feat/adaptive-skills`, runtime commit `e20116e`. Model: local Ollama
`qwen2.5:7b`, `temperature=0`, `seed=7`, `max_tokens=2048`. JSON mode for
decisions only. One request per task, no retries, no transformations. Scored on
the frozen `toolwright-eval-v1` corpus for comparison with earlier runs.

## Change

v6 is v5 with only the format rule reworded. v5 said "a ```python line, the
complete source of tool.py, then a ``` line", and three of its replies closed
the block twice. v6 asks for one ```python block, closed by a single ``` line
written once, with nothing after it and no second closing fence. The v5 prompt
bytes are now pinned by a hash test.

## Results

| Run | Usable sources | Tasks passed | Cases | Held-out | Decisions |
| --- | --- | --- | --- | --- | --- |
| v3 + recorded fence transformation | 16/16 | 11/16 | 39/48 | 25/32 | 0/4 |
| v5 | 13/16 | 8/16 | 31/48 | 20/32 | 4/4 |
| **v6** | **16/16** | **10/16** | **37/48** | **24/32** | **4/4** |

The reworded rule removed the doubled fence: all 16 tool replies were in the
declared format. v6 is the best prompt so far that needs no transformation, and
the only one that gets both usable sources and correct refusals from the same
run.

## Remaining failures

| Task | Failure |
| --- | --- |
| group-totals | `NameError`: `sys` not imported |
| active-ids | `NameError`: `exit` is not defined (see below) |
| word-counts | tokens not lowercased |
| date-distance | absolute instead of signed day difference |
| csv-projection | crashes on a quoted field (`split(',')`, not the `csv` module) |
| run-length | rejects the empty list as invalid input |

- `exit()` and `quit()` exist only when Python's `site` module is loaded. The
  contained executor runs Python in isolated mode, where they are missing.
  `sys.exit()` is the portable call.
- `run-length` is a side effect of the "validate the full input shape" rule: the
  model treated an empty list as invalid.
- A missing import remains the most frequent defect across prompts, despite the
  "Import every module you use" rule.

## Admission

The v6 candidates for the two tasks that passed v1 and had no admitted version
(`chunk-list`, `sort-records`) were submitted to admission on corpus v2:

- `sort-records`: admitted (3/3 examples, 5/5 held-out) and promoted. The local
  catalog now covers 12 of 16 tasks.
- `chunk-list`: refused again with 4/5 held-out. This is the second distinct
  candidate to fail exactly one held-out case. That case may be ambiguous (the
  instruction does not say values are integers, while v3–v6 tell the model to
  validate integer fields). This needs a human audit of the case with
  `inspect(include_held_out=True)`; the audit result must not reach a
  generation or repair prompt.

Raw responses and receipts remain private.
