# Skill Generalization (Groundwork)

Step A of the [adaptive-skills roadmap](roadmap-adaptive-skills.md). Several
tasks that share an input and output contract may be served by one documented
tool with options, instead of one tool each. This stage builds and checks the
prompt, the documentation and the evidence path. It has not been run against a
model yet; whether a generalized tool beats keeping specific tools is still the
open question the roadmap names.

## Family

A family is two to four member tasks: corpus v2 tasks or [user tasks](user-tasks.md).
Every member's example cases must share one contract signature (as in the
[reuse policy](reuse-policy.md)), and all members must share it.

```sh
evolution-tools general families --member sum=corpus:integer-sum --member max=max.json --member med=corpus:median
```

`families` groups members by signature and reports instruction similarity. A
member whose own examples have more than one signature (`median` returns both
integers and numbers) is listed under `skipped`. A family is a proposal for a
person; nothing is generated.

## Generalized tool

The tool receives `{"data": <member input>, "options": <object>}`. The options
select a member's behaviour. The reply is one ```python block (the v6/v7 format)
whose source contains one top-level literal:

```python
TOOLWRIGHT_DOC = {"name": "reduce_values",
                  "description": "Reduce integer values with the selected operation.",
                  "options": [{"name": "operation", "type": "string", "description": "sum or max"}],
                  "bindings": {"max": {"operation": "max"}, "sum": {"operation": "sum"}}}
```

- The literal is read with `ast.literal_eval`. Nothing in the source is executed;
  an expression or call in its place is refused.
- Documentation is required (roadmap principle 4): a name, a description, one to
  eight typed options, each with a description, and a binding for exactly the
  family's members, with a value for every option. Bindings must differ between
  members; `bool` is not accepted for integer or number options.
- The prompt holds every member's instruction and example cases only. It is
  refused if any held-out input of any member appears in it, and the reply is
  bound to the exact prompt and request settings.

## Evidence

```sh
evolution-tools general generate --member ... --out general.json --record record.json
evolution-tools general prepare record.json sum --member ... --scripts general.json --container-image <id> > sum.json
# inspect, approve and execute every proposal with `evolution-tools review ...`; same for max
evolution-tools general admit record.json sum sum.json --member ...
evolution-tools general decide record.json --member ... --attempt sum=<n> --attempt max=<m>
evolution-tools general promote record.json --member ... --attempt sum=<n> --attempt max=<m> --yes
```

- `prepare` creates one pending proposal per case of one member, with that
  member's binding as `options`. It refuses a candidate whose `TOOLWRIGHT_DOC`
  differs from the record, and a record whose members (task, hash) changed.
- `admit` is ordinary [admission](admission.md) on the member's example and
  held-out cases. The attempt spends a slot of **the member's own** held-out
  budget: the generalized view reports the member's task hash, so trying a
  generalization never opens a fresh budget for the same held-out cases.
- `decide` reads the attempts from the ledger, checks that each attempt's
  candidate carries this record's spec and documentation, and admits the
  family only if one identical candidate was admitted on every member. Like
  admission, it reports pass counts only.
- `promote` adds a family-admitted tool to the catalog as `general_<name>`,
  through the first member's example receipt. Retiring the specific member
  versions stays a separate, human decision.

## Limits

- Not yet run against a model. The first live run needs the GPU and a family
  worth generalizing; the frozen corpus has few same-signature tasks with clearly
  related behaviour.
- One generalized candidate per member attempt. Generalization competes with
  repair and generation for each member's three candidate slots.
- Reuse retrieval (`task reuse`) matches signatures of `data`-only contracts; a
  `general_` version, which also takes `options`, is not offered for reuse yet.
