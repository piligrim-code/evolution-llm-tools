# Versioned Input Robustness Probes

`toolwright-robustness-v1` is a separate, fixed probe set for the opt-in
`integer-sum` prompt-v3 contract. It does not change `toolwright-eval-v1`, its
task definitions, prompt bytes, or 48-case denominator.

The set contains four valid boundary cases (empty, negative/cancellation, a
large exact integer, and 2,000 values) and seven invalid-shape/type cases
(missing/extra fields, booleans, floats, null/string values, and non-object
data). Valid cases require the exact JSON result. Invalid cases require a
nonzero exit, empty stdout, and a fixed nonempty stderr message without a
traceback. No coercion is accepted.

The immutable dataset identity is:

```text
toolwright-robustness-v1
b4f34205f9a67bdda2c50aaf31910a5f844de71d55b85a9e65c8ff4d1d511fa5
```

This is a test specification, not a model score. The existing real-model report
records one prior candidate's 4/4 valid probes and only 2/5 malformed-input
rejections; that candidate was not evaluated against this complete set. No
provider call or candidate execution is part of defining or testing these
fixtures.

The next qualification step must bind each case to the same frozen candidate,
execution policy and immutable container image, and use the ordinary per-case
inspection, explicit approval, single-use execution and receipt flow. Scoring
must distinguish clean rejection from traceback, timeout, infrastructure
failure and missing receipt. Until that receipt-bound runner exists, do not
report these fixtures as executed robustness results or compare them as a model
score.
