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

This dataset is a test specification, not a model score. The existing real-model
report records one prior candidate's 4/4 valid probes and only 2/5 malformed-input
rejections; that candidate was not evaluated against this complete set. Defining
and unit-testing these fixtures does not call a provider or execute a candidate.

## Reviewed Runs

List probes without exposing their arguments or expected answers:

```sh
evolution-tools eval robustness-cases
```

Prepare every case independently with the same source and immutable image. Each
command creates a pending proposal only:

```sh
evolution-tools eval robustness-prepare empty-values --scripts candidate.json --container-image <sha256-image-id> --store private/reviews.sqlite3
```

Inspect, explicitly approve, and execute each proposal through the normal review
commands. Do not batch approvals or execution. For invalid cases the output
contract is a sentinel that cannot pass on the expected nonzero exit; the scorer
also requires an exited container, empty stdout with matching byte evidence, and
a short one-line stderr message without traceback. All seven invalid probes
must produce exactly the same stderr message. The message itself is never
included in the score.

The manifest contains the corpus hash returned by `robustness-cases` and one
case/proposal assignment per prepared receipt:

```json
{
  "robustness_sha256": "<toolwright-robustness-v1 sha256>",
  "assignments": [
    {"case_id": "empty-values", "proposal_id": "<actual-proposal-id>"}
  ]
}
```

```sh
evolution-tools eval robustness-score manifest.json --store private/reviews.sqlite3 --details
```

Scoring is read-only. It verifies each proposal's case binding and receipt,
requires the same source and full execution policy/image across observed cases,
and counts missing assignments. A pass requires all 4 valid outputs and all 7
clean invalid-input rejections. Partial manifests are not qualification. A
receipt is evidence from the trusted local journal, not proof of provider
identity or resistance to a hostile operator.
