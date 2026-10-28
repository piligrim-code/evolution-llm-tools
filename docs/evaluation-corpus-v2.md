# Evaluation Corpus v2

`toolwright-eval-v2`
(`531a8347ac1cca7e024c2b74308b620d5971fe917619821a75203d75df2031c9`) extends the
frozen `toolwright-eval-v1` corpus for evidence-gated admission (see the
[adaptive-skills roadmap](roadmap-adaptive-skills.md)). v1 is unchanged.

## What changed

- Every v1 case becomes an **example** case, including the two former held-out
  cases per task. Earlier live runs were scored on those cases and their failures
  were analysed, so they no longer count as unseen.
- Each of the 16 tool tasks gains **five new held-out cases** (80 in total)
  whose inputs differ from every v1 input. Tool tasks now have 8 cases each:
  3 example and 5 held-out.
- Instructions, the first example and the four refusal tasks are unchanged, so
  the existing v1 and v2–v5 prompts stay valid. Candidates generated from them
  can be scored on cases they have never seen.

## Rules

- Example cases may be used for development and repair.
- Held-out cases are used only for admission. They must never be shown to a
  generation or repair step.
- `list_cases()` returns IDs and splits only, never inputs or expected answers.

## Verification

Every expected answer, in v1 and in v2, is checked against an independent
reference solution in `tests/test_evaluation_corpus_v2.py`. The comparison uses
JSON text, so `3.0` and `3` and `true` and `1` are not treated as equal. The tests
also check that the held-out inputs never appear in a generation prompt.

These are synthetic cases chosen by hand. Passing them is evidence for these
behaviours, not proof of general correctness.
