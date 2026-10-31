# Robustness Qualification: Integer-Sum Candidate

Date: October 21, 2026.
Repository branch: `feat/measured-generation-results`, runtime commit `863b21c`.
Corpus: `toolwright-robustness-v1`
(`b4f34205f9a67bdda2c50aaf31910a5f844de71d55b85a9e65c8ff4d1d511fa5`).

## Summary

The only existing real-model candidate **fails** the robustness set: it
returns the correct sum for all 4 valid probes and cleanly rejects none of the
7 invalid probes. This is the first complete receipt-bound robustness result;
it replaces the earlier 2/5 informal rejection count, which used a different
and smaller probe set.

## Procedure

The unchanged candidate source
(`dd32760d335e2273e4e2c8c3b8df2c535bb00ecc70c88447c685b9b5ada6831c`, the same
provenance-bound transformation used in the October 19 assessment) was
prepared once per case with `eval robustness-prepare` against image
`sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f`.
Each of the 11 pending proposals was inspected; all shared the same source,
image and policy (no network, read-only root, 10 second timeout) and differed
only in arguments. Each proposal was then approved and executed once, in
sequence, with no retries. No owned container remained afterwards. No model
request was made.

`eval robustness-score` on the manifest of all 11 assignments reported one
consistent candidate identity.

## Results

| Case | Class | Status |
| --- | --- | --- |
| `empty-values` | valid | correct |
| `negative-cancellation` | valid | correct |
| `large-exact-integer` | valid | correct |
| `many-values` | valid | correct |
| `missing-values` | invalid | invalid input accepted (sum `0`) |
| `extra-field` | invalid | invalid input accepted |
| `boolean-member` | invalid | invalid input accepted |
| `float-member` | invalid | invalid input accepted |
| `null-values` | invalid | unclean rejection (traceback) |
| `string-values` | invalid | unclean rejection (traceback) |
| `non-object-data` | invalid | unclean rejection (traceback) |

Status counts: `correct` 4, `invalid_input_accepted` 4, `unclean_rejection` 3.
`robustness_passed`: false.

The candidate does no input validation: it sums whatever `data.get("values",
[])` yields, so missing fields, extra fields, booleans and floats are silently
accepted, and other malformed shapes crash with an uncaught Python exception.

## Scope

One candidate, one task, one run. The result says nothing about other tasks or
models. Raw receipts, inspected documents and the review journal remain in the
private workstation evidence directory and are not committed.
