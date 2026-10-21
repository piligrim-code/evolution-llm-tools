# Live Generation Qualification: qwen2.5:7b, Prompt v3

Date: October 21, 2026.
Repository branch: `feat/measured-generation-results`.
Corpus: `toolwright-eval-v1`
(`c46892beb6f2a6ba1270e48147c9eeab0f09010b789b9a0c68ed9ab5dada0626`), unchanged.

## Summary

The first whole-corpus live run. A local `qwen2.5:7b` produced usable
source for all 16 tool tasks, but only after an explicit fence transformation:
every response was wrapped in a Markdown fence despite prompt v3 forbidding it.
The generated tools solved **11/16 tasks** completely and **39/48 cases**
(25/32 held-out). The four refusal tasks chose the correct action and reason,
but all four were fenced JSON and so fail the strict decision format.

## Procedure

- Model: Ollama tag `qwen2.5:7b` (local, alias only; weight identity not
  verified). Prompt v3, `temperature=0`, `seed=7`, `max_tokens=1024`.
- Exactly one request per task (20 total), no retries or regeneration.
  Client-observed time per tool request was 2.7–7.6 seconds.
- Each fenced tool response was passed through `unwrap-python-fence-v1`; all
  16 unwrapped sources passed the syntax check. No other edits were made.
- Each of the 48 cases was prepared, inspected, approved and executed once in
  image `sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f`
  (no network, read-only root, 10 second timeout). No owned container remained.
- Scored with `score_run` over all 48 receipts.

## Results

| Measure | Result |
| --- | --- |
| Raw responses passing the v3 source check | 0/16 (all `markdown_fence`) |
| Sources after fence transformation | 16/16 syntax-valid |
| Tool tasks passed (all 3 cases) | 11/16 |
| Cases correct | 39/48 (example 14/16, held-out 25/32) |
| Refusal decisions scored | 0/4 (all fenced JSON; content was correct) |

Failures:

| Task | Cases | Cause |
| --- | --- | --- |
| `active-ids` | 3/3 failed | `NameError`: uses `sys` without importing it |
| `sort-records` | 3/3 failed | `NameError`: uses `sys` without importing it |
| `csv-projection` | `quoted` failed | Splits on commas, so quoted fields break the column count |
| `date-distance` | `reverse` incorrect | Returns a signed distance where the task expects an absolute one |
| `run-length` | `empty` incorrect | Emits `[[0, 0]]` for empty input instead of `[]` |

## Robustness Of The New Integer-Sum Candidate

The v3 `integer-sum` candidate was also run through `toolwright-robustness-v1`
(11 reviewed single-use executions, same image):

| Class | Result |
| --- | --- |
| Valid | 4/4 correct |
| Invalid, clean rejection | 5/7 (missing field, float, null, string, non-object) |
| Invalid, accepted | 2/7 (extra field, boolean member) |

`robustness_passed`: false. Compared with the October 19 candidate (0/7 clean
rejections), prompt v3 led the model to add input validation, but it still
accepts `bool` as an integer and ignores extra fields. Its rejection messages
are not uniform (one is a raw Python exception message), which the scorer
would also refuse if all seven rejections had been clean.

## Scorer Correction

This run exposed a defect in the robustness scorer: it treated any newline in
stderr as unclean, so a normal `print(message, file=sys.stderr)` rejection
could never pass. The scorer now allows exactly one trailing line terminator;
interior newlines and tracebacks are still refused. Re-scoring the October 21
run of the earlier candidate gives the same result (its rejections were
multi-line tracebacks).

## Scope

One model, one seed, one request per task. The pass counts are a small
observation, not a quality estimate; fence handling was needed for every
response. Raw responses, receipts and the review journals remain private and
are not committed.
