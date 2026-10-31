# Prompt v7 and Model Comparison

Date: November 1, 2026.
Branch: `feat/adaptive-skills`, runtime commits `33bc7d7` (prompt v7) and
`70b2951` (optional `think` switch). Local Ollama, `temperature=0`, one
request per task, no transformations. Scored on the frozen
`toolwright-eval-v1` corpus, as in earlier runs.

## Prompt v7

v7 is v6 plus one rule aimed at the defects v6 still showed: import `json` and
`sys` at the top level, exit only with `sys.exit(...)` (never `exit()` or
`quit()`), and treat empty collections as valid unless the task says otherwise.
The v6 prompt bytes are pinned by a hash test.

With `qwen2.5:7b`, v7 reaches **11/16 tasks, 38/48 cases, 26/32 held-out and
4/4 refusals**. That ties the best earlier result (v3 with the recorded fence
transformation) without any transformation, and with correct refusals. It fixed
`active-ids` (`exit()`) but the model still refuses the empty list in
`run-length` and rejects valid input in `group-totals`. Prompt wording alone
seems to plateau at about 11/16 for this model.

## Seeds do not vary output at temperature 0

18 of the 20 `qwen2.5:7b` v7 replies were byte-identical for seeds 7, 11 and 13.
The two that differed came only from the seed-7 run, and both were requested
while another workload was using the GPU or were re-requested afterwards. Greedy
decoding makes the seed irrelevant. A stability study needs a temperature above
zero; "more seeds at temperature 0" measures nothing.

## Models (prompt v7)

| Model | Usable sources | Tasks | Cases | Held-out | Decisions | Time per request |
| --- | --- | --- | --- | --- | --- | --- |
| qwen2.5:7b | 16/16 | 11/16 | 38/48 | 26/32 | 4/4 | 4–10 s |
| qwen3:8b, thinking on (4096 tokens) | 12/16 | 12/16 | 36/48 | 24/32 | 4/4 | 35–95 s |
| qwen3:8b, `think=false` (2048 tokens) | 16/16 | 11/16 | 41/48 | 26/32 | 4/4 | about 6 s |
| **gemma3:12b** | **16/16** | **14/16** | **44/48** | **29/32** | **4/4** | 30–60 s (partly on CPU) |

- **gemma3:12b** is the strongest so far. It failed only `date-distance` (wrong
  values) and `csv-projection` (quoted field).
- **qwen3:8b with thinking** was correct on every task it answered, but on 4 tasks
  the reasoning used the whole 4096-token budget (the client maximum) and no
  answer was returned. The new optional `think` switch (`think=False`) removes
  that, but the non-thinking model over-validates: it rejects equal bounds,
  empty lists and reversed dates.
- `csv-projection` (quoted fields) failed for every model and prompt so far.

## Run notes

- A guard now stops a generation run if another model is loaded in Ollama,
  instead of letting requests time out. An external `qwen3:8b` workload hit the
  GPU during the first `qwen2.5:7b` v7 run.
- Requests that returned no content (client timeouts: 6 in that run, and the
  first, cold-start request of the gemma3 run) were re-requested once in a
  separate, labelled run directory. With greedy decoding this does not choose
  among answers; no request that returned content was repeated.

## Admission

The gemma3 `run-length` candidate was admitted on corpus v2 (3/3 examples, 5/5
held-out) and promoted, so the local catalog now covers **13 of 16 tasks**.
Still uncovered: `date-distance`, `csv-projection`, and `chunk-list`. For
`chunk-list`, the last candidate slot is kept until the suspect held-out case has
been audited (see the [v6 qualification](prompt-v6-qualification-2026-10-28.md)).

Raw responses and receipts remain private.
