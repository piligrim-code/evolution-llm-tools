# Reuse-or-Generate Policy (Groundwork)

Step D of the [adaptive-skills roadmap](roadmap-adaptive-skills.md). Given a
request (a description plus one example input and expected output), decide
whether an existing catalog version can serve it or a new tool must be
generated. Nothing here generates, approves or executes.

## Policy

1. **Contract signature.** A version's signature is its input field names with
   coarse JSON types plus the coarse result type, for example
   `data{values:array}->integer`. Element types and nested keys are left out on
   purpose: they depend on the data (a word count has different keys for every
   text), not on the contract. `bool`, integer and number stay distinct.
2. **Retrieval.** Unretired versions with exactly the same signature, ranked by
   word overlap between descriptions.
3. **Verify, then reuse.** A match leads to `verify_reuse`, not to reuse:
   `prepare_reuse_check()` copies the best version into a pending proposal bound
   to the requester's example. After the usual inspection, approval and one
   execution, the version is reused only if that example passes; otherwise the
   request falls back to generation.
4. **No match** leads to `generate`.

Every decision records its reason, the ranked candidates, the signature and an
estimated cost: verifying a reuse is 1 reviewed execution and no model request,
while generating a corpus tool is 1 model request plus 8 admission executions.

## Why verification instead of a similarity threshold

A first version reused a match when word similarity was at least 0.5. On the 10
admitted catalog versions, requests that repeated the task instruction scored
1.0, but paraphrases written as a person would ask scored only 0.06 to 0.29, so
the threshold would have sent every paraphrase to generation. The contract
signature, by contrast, narrowed every paraphrase to exactly one version, and it
was the right one each time. Signatures can still collide (`run-length` and
`stable-unique` share `data{values:array}->array`), so the requester's own
example acts as the final check.

## End-to-end check (October 28, 2026)

Run against the local catalog of the 10 versions admitted in the
[admission qualification](qualification/admission-qualification-2026-10-28.md). Each request
used a public example case (never a held-out one); 10 requests were
paraphrased. Docker only, no model requests.

| Requests | Decision | Check on requester's example | Final |
| --- | --- | --- | --- |
| 10 paraphrased, admitted tasks | verify_reuse (own version) | 10 passed | reuse |
| run-length | verify_reuse (`stable-unique`, shared contract) | failed (`invalid`) | generate |
| 5 other non-admitted tasks | generate (no contract match) | n/a | generate |

Result: 10 tasks were served with 11 reviewed executions and no model request.
The one wrong candidate was caught by its check.

## Limits

- Signatures only cover the corpus shape (`data` object in, `result` out).
- One example per request is a weak check; a version that passes it can still be
  wrong for the requester's other inputs. Reuse inherits the version's admission
  evidence, which covers the corpus task it was admitted for, not every paraphrase.
- Ranking by word overlap is crude. It matters only when several versions share
  a signature.
