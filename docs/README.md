# Documentation

## Reference

Execution and review:

- [Reviewed lifecycle](reviewed-lifecycle.md): propose, inspect, approve, execute.
- [Container execution](container-execution.md): containment controls and cleanup.
- [Output contracts](output-contracts.md): expected-output checks bound to approval.
- [Typed outcomes](typed-outcomes.md): per-attempt result types, no automatic retries.
- [Version catalog](version-catalog.md): immutable promoted versions.
- [Retention](retention.md): pruning previews and permanent retirement.
- [Demos](demos.md): packaged deterministic examples.

Model interface and evaluation:

- [Ollama contract](ollama-contract.md): bounded HTTP and output validation.
- [Generation measurements](generation-measurements.md): measured requests and their limits.
- [Source transformations](source-transformations.md): prompt versions v2–v7 and the fence rule.
- [Evaluation](evaluation.md): the frozen v1 corpus and receipt scoring.
- [Evaluation corpus v2](evaluation-corpus-v2.md): fresh held-out cases.
- [Robustness evaluation](robustness-evaluation.md): invalid-input probes.
- [CI qualification](ci-qualification.md): installed-wheel CI gate.

Adaptive skills:

- [Roadmap](roadmap-adaptive-skills.md): direction and principles.
- [Admission](admission.md): evidence-gated catalog entry.
- [Repair](repair.md): repair from example failures.
- [Reuse policy](reuse-policy.md): reuse-or-generate decisions.

## Qualification reports

Dated records of what was run, on which commit, and what it showed, including
negative results. Newest first:

- [Prompt v7 and model comparison](qualification/model-comparison-2026-11-01.md) (Nov 1)
- [Prompt v6](qualification/prompt-v6-qualification-2026-10-28.md) (Oct 28)
- [Prompt v5 baseline](qualification/prompt-v5-qualification-2026-10-28.md) (Oct 28)
- [First live repair](qualification/repair-qualification-2026-10-28.md) (Oct 28)
- [First admission run](qualification/admission-qualification-2026-10-28.md) (Oct 28)
- [Prompt v4](qualification/prompt-v4-qualification-2026-10-21.md) (Oct 21)
- [First whole-corpus live generation](qualification/live-generation-qualification-2026-10-21.md) (Oct 21)
- [Robustness of the integer-sum candidate](qualification/robustness-qualification-2026-10-21.md) (Oct 21)
- [Real-model assessment](qualification/real-model-assessment-2026-10-19.md) (Oct 19)
- [Input-contract remediation](qualification/input-contract-remediation-2026-10-19.md) (Oct 19)
- [Hosted qualification](qualification/hosted-qualification-2026-10-07.md) and [checkpoint](qualification/checkpoint-2026-10-07.md) (Oct 7)
- October 3 stage reports: [overall](qualification/qualification-2026-10-03.md),
  [hosted](qualification/hosted-qualification-2026-10-03.md),
  [CI gate](qualification/ci-gate-qualification-2026-10-03.md),
  [catalog](qualification/catalog-qualification-2026-10-03.md),
  [outcomes](qualification/outcomes-qualification-2026-10-03.md),
  [output contracts](qualification/output-contract-qualification-2026-10-03.md),
  [retention](qualification/retention-qualification-2026-10-03.md),
  [evaluation](qualification/evaluation-qualification-2026-10-03.md),
  [generation](qualification/generation-qualification-2026-10-03.md),
  [prompt v2](qualification/prompt-v2-qualification-2026-10-03.md),
  [source transformation](qualification/source-transformation-qualification-2026-10-03.md)
