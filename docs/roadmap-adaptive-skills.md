# Roadmap: Adaptive Skills

Date: October 28, 2026.
Status: proposal. Nothing in this document is implemented, qualified, or a
release commitment. It records a direction so later work can start from shared
reasoning.

## Purpose

Toolwright generates small tools with a local model, runs them only after
explicit review, and reuses approved tools through a registry and a validated
version catalog. The plumbing is well tested. The evidence for generation quality
is thin; see the [real-model assessment](qualification/real-model-assessment-2026-10-19.md)
and the [live-generation qualification](qualification/live-generation-qualification-2026-10-21.md).

The proposed direction is to make the system improve from its own recorded
experience without weakening any review guarantee. Four abilities are in scope:

1. accumulate skills from successful runs;
2. generalize a skill so it works on new variants of a familiar task;
3. repair a skill from typed failures;
4. decide when to reuse an existing skill and when to generate a new one.

In product terms this is skill acquisition and transfer to variants. It is
narrow by design. No claim about general intelligence is made.

## Design principles

1. **Admission needs evidence the generator did not see.** A candidate enters
   the catalog only after passing held-out cases. A finite held-out set is a
   consumable resource: selecting the best of K candidates on the same cases
   inflates the measured gain (for pure noise of standard deviation sigma the
   expected maximum grows roughly like sigma times sqrt(2 ln K)). Reused held-out
   cases need accounting, refreshing, or a sequentially valid acceptance test.
   Today the frozen corpus has only two held-out cases per task, so the binding
   risk is sample size; a candidate limit per task and a held-out usage counter
   are enough to start.
2. **Improvement steps never see held-out cases.** Repair, generalization and
   prompt changes may use only example (development) cases and their failures.
   If a repair is driven by a held-out failure and the same cases then admit the
   result, they are no longer held out. Held-out cases serve admission only.
3. **The admission check lives outside what it judges.** Neither the generator
   nor any repair or generalization step may modify the admission logic, the
   held-out cases, or the receipts.
4. **Abstractions are documented.** A generalized tool carries a name, a
   description, and a contract. Library-learning work (for example LILO, ICLR
   2024) reports that anonymous abstractions can hurt a language-model
   synthesizer and that automatic documentation recovers part of the loss.
5. **Failures are first-class data.** Typed outcomes already distinguish failure
   classes; repair should consume them rather than retry blindly.
6. **Every skill carries its provenance.** Source, contract, evidence, lineage,
   and the assumptions it relies on stay attached to the version.
7. **Control is cost-aware.** Reuse, generate, repair, and ask-a-human have
   different costs; the policy should see tokens, time, and review burden.
8. **Review stays the authority.** Automation may propose. It never approves
   and never executes unreviewed code.

## Candidate capabilities

Each capability produces new *pending proposals*. None runs anything by itself.

| ID | Capability | What it does | Constraint |
| --- | --- | --- | --- |
| B | Evidence-gated admission | Promotes a version only if it passes held-out cases, with a record of how often those cases were used. Replaces today's `catalog promote` check, which validates a single input | Held-out use is budgeted; the gate is not editable by generation steps |
| C | Failure-driven repair | From a typed failure on an example case, proposes a patch as a new pending proposal and re-evaluates it; keeps lineage to the failing version | One bounded attempt per failure; no automatic retries; never driven by held-out failures; stderr from generated code is untrusted text, truncated and passed as data, not instructions |
| D | Reuse-or-generate policy | Retrieves catalog candidates by contract, falls back to generation, records the outcome and its cost | Policy decisions are logged and explainable; needs a contract index, since the catalog is listed by name only today |
| A | Skill generalization | Finds near-duplicate tools and proposes one parameterized tool covering them | Highest risk; result must be documented and evidence-gated before use |
| E | Variant families in the offline corpus | Adds example and held-out cases and task variants so A to D can be checked inside the product | Supporting tool only; not a general benchmark effort; a minimal version is a prerequisite for B |

## Product signals

These are internal signals for judging the capabilities above, not a benchmark
program:

- success rate on new variants of previously solved task families;
- tokens and elapsed time per accepted task;
- share of tasks completed without a human edit;
- false admissions (versions admitted that later fail on fresh cases);
- catalog size relative to the number of task families served.

## Non-goals

- No claim or pursuit of general intelligence as a deliverable.
- No automatic approval or automatic execution.
- No standalone general benchmark, leaderboard, or measurement stand.
- No weight fine-tuning in the first phase; work stays at the prompt, registry,
  and policy level. Weight adaptation can be reconsidered later, noting the
  limits of local hardware (the reference machine has 8 GB of VRAM).

## Suggested order

0. **Baseline.** Record a live run of the current best prompt (v5, not yet run
   live) so later changes have something to be compared with.
1. **B, evidence-gated admission,** together with a minimal **E**: enough
   example and held-out cases per task family that admission means something.
   Smallest step; protects everything after it.
2. **C, failure-driven repair.** Uses the existing typed outcomes and example
   cases. The October 21 live run suggests a high return: two of the five failed
   tasks only lacked `import sys`.
3. **D, reuse-or-generate policy.** Needs cost accounting from the measured
   generation API and a contract index for the catalog.
4. **A, skill generalization.** Most complex; start only after B is solid.
5. Further **E** variant families as needed to exercise A to D.

For each step: write the contract and the tests first, keep the default offline
suite model-free, and record qualification in a dated document as for earlier
stages.

## Known limits and open questions

- Real-model evidence is narrow. Improvements must show up on more than one
  task family before being described as improvements.
- Held-out cases exist only for the frozen corpus. For a tool a user requests,
  someone must supply held-out cases with the request, out of the generator's
  view; most likely the person who asked. Until that flow exists, B applies only
  to corpus tasks, and catalog versions of user tools keep the weaker
  single-input check.
- Prior art exists for skill libraries and agent memory. The intended difference
  here is review-bound execution, evidence-gated admission, and cost accounting.
  A detailed survey has not been done.
- Sequentially valid acceptance tests (e-processes) are recent preprints.
  Treat them as design inspiration, not established practice.
- Whether generalization (A) outperforms simply keeping many specific tools is
  an open question; the product signals above are meant to answer it.

## Provenance

Derived from an internal literature and theory review dated October 28, 2026
(not published). Self-improvement references were mostly preprints and were
read through abstracts and secondary summaries.
