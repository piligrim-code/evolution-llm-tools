# User Tasks

A user task is your own tool request with its own evidence. You describe the
task, give a few example cases that the model may see, and add held-out cases
that it never sees. The held-out cases then decide whether the generated tool
enters the catalog, exactly as for the [evaluation corpus](evaluation-corpus-v2.md)
under [evidence-gated admission](admission.md).

## Task file

```json
{
  "format": "toolwright-user-task-v1",
  "id": "duration-seconds",
  "instruction": "Convert a duration such as \"1h30m\" into whole seconds.",
  "examples": [
    {"id": "hours-minutes", "data": {"text": "1h30m"}, "result": 5400}
  ],
  "held_out": [
    {"id": "all-units", "data": {"text": "2h5m7s"}, "result": 7507},
    {"id": "hours-only", "data": {"text": "3h"}, "result": 10800},
    {"id": "zero", "data": {"text": "0s"}, "result": 0}
  ]
}
```

- `id` and case IDs use lowercase letters, digits and hyphens.
- `data` is the JSON object the tool receives as `data`. `result` is the exact
  value it must print as `{"result": ...}`.
- 1–10 examples and 3–20 held-out cases. Held-out inputs must be distinct and
  must not repeat an example input.
- The task hash covers the instruction and every case. Changing anything makes
  it a different task with its own candidate budget.

A complete example is in [`examples/duration-seconds.json`](../examples/duration-seconds.json).

## Flow

```sh
evolution-tools task check task.json         # counts and hash, never the cases
evolution-tools task prompt task.json        # what the model will see
evolution-tools task generate task.json --out candidate.json
evolution-tools task prepare task.json --scripts candidate.json --container-image <image-id> > manifest.json
# inspect, approve and execute every proposal in the manifest with `evolution-tools review ...`
evolution-tools task admit task.json manifest.json
evolution-tools task promote task.json <attempt> --yes
```

- `generate` makes one model request and writes unreviewed source. It never
  approves or runs anything.
- `prepare` creates one pending proposal per case and prints the manifest
  (proposal IDs only).
- `admit` scores the finished receipts and records the attempt in the admission
  ledger. Each distinct candidate uses one of the task's slots (3 by default).
  The result reports how many held-out cases passed, never which.
- `promote` adds an admitted candidate to the catalog through its first example
  receipt, under the name `task_<id>`.

## Rules

- The prompt contains the instruction and the examples only. It is built with
  the prompt-v7 source rules and refused if any held-out input appears in it.
- Replies are bound to the exact prompt and request settings, and must be one
  fenced Python block.
- Held-out cases are yours: you wrote them, and the task file holds them. Keep
  them out of anything you later paste into a prompt, or they stop being
  held out.
- Repair for user tasks is not available yet.
