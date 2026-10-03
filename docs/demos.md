# Deterministic Demos

These packaged examples use hand-written standard-library code and synthetic
inputs. They demonstrate review, execution, output validation and explicit catalog
reuse, not model generation quality or a performance benchmark. No account, live
model, private file, external dataset or network access is needed by a fixture.

| Name | Example |
| --- | --- |
| `text-summary` | Count whitespace-separated tokens and distinct tokens. |
| `table-totals` | Validate synthetic integer amounts and sum them by group. |
| `json-projection` | Validate selected JSON fields and return a projection with summed integer scores. |

## Prepare, Inspect, Approve

Use a trusted immutable local image as described in
[container execution](container-execution.md). From a private working directory:

```sh
evolution-tools demo list
evolution-tools demo prepare text-summary --container-image <local-sha256-image-id>
evolution-tools review inspect <returned-proposal-id> --json
evolution-tools review approve <proposal-id> --digest <inspected-digest>
evolution-tools review execute <proposal-id> --structured
```

Replace `text-summary` with either other listed name to prepare that example.
Preparation creates only a pending v2 proposal with literal independently supplied
expected JSON. It never starts Docker, contacts a provider, installs dependencies,
approves the proposal or executes the code. Inspect the full source, arguments,
image/policy and expectation before approval. The normal confirmation defaults to
no. An unapproved structured execution returns `refused`.

The default review journal is `.mcp/reviews.sqlite3` relative to your current
directory. `demo prepare --store /private/reviews.sqlite3 ...` selects a different
journal; use the matching `review --store ...` option for subsequent commands.
The default synthetic data contains no workstation-specific values. Your own
arguments and outputs remain private data in the review journal and, if promoted,
the catalog. Do not commit those databases.

## Explicit Reuse

After a succeeded attempt, explicitly preserve and select the version:

```sh
evolution-tools catalog promote <completed-proposal-id>
evolution-tools catalog inspect demo_text_summary <returned-full-version>
evolution-tools catalog prepare demo_text_summary <full-version>
```

The returned ID is a fresh pending proposal, not the old approval. Inspect and
approve it before execution. New arguments require a new independent expectation;
see [the catalog workflow](version-catalog.md). No version is saved automatically
by execution and no demo has a shortcut that bypasses review.

The library equivalents are `list_demos()`, `get_demo(name)` and
`prepare_demo(name, policy, reviews)` in `alita.demo_fixtures`. `get_demo` returns
a detached copy for inspection. Preparation follows `ReviewStore.create` and
does not activate anything. `execute_result` returns the
[typed per-attempt outcome](typed-outcomes.md).

## Scope And Verification

Expected outputs are literal fixture data, not answers produced by the code being
tested. Actual-container tests also use separately specified alternate cases:
different token counts, negative grouped amounts, and an empty score list with
a false active flag. This guards against fixed-output examples but is not an
exhaustive correctness proof for arbitrary inputs.

Demo scripts check the nested values they use, including rejecting booleans where
an integer amount/score is required. They are small examples, not general text,
accounting or schema engines. Existing execution/resource limits still apply.

```sh
python -m pytest tests/test_demos.py tests/test_outcomes.py -q
python tools/run_container_tests.py
```

The default demo tests never execute fixture code. The explicit Docker suite runs
hand-written fixtures in owned containers and confirms cleanup, validation,
promotion and fresh approval for reuse. No model generation is tested here.
