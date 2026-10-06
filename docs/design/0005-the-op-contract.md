# Design note 0005: one op contract, and where it lives

Status: settled. scikit-ops is the op contract (decision 44). opspec was a
prototype carrying a second copy of the same module; it is dropped, and this
note records what that costs and where the two had drifted.

## What we use

`demo/demo_ops.py` declares its ops with `skop.op` -- `@op()` for a workflow,
`@op(env=...)` for an op that names an environment -- and types them with
`skop.types` (`ImageOf`, `LabelsOf`). `skop_core` reads them with `skop.spec`,
which caches the spec on the function. An op's parameters, their roles, and
which of them are arrays are read off its own signature rather than restated
beside it (decision 40), which is why `array_params=` and `roles=` are gone.

`is_op` checks for the `__skop__` attribute, so a scikit-ops op is an op to us
and nothing else is; there is no second marker to check.

## Why opspec went

opspec and scikit-ops each implemented the same module -- `Role`, `Slot`,
`Axes`, `Choice`, `TypeSpec`, `ParamSpec`, `OutputSpec`, `OpSpec`,
`type_spec`, the wire vocabulary, the axis aliases -- with the same values and
the same "standard library only" rule. Two copies of a shared contract drift,
and these had, in both directions.

The design note that used to live here argued the opposite: delete scikit-ops'
`_spec.py` and have it depend on opspec. That is the right *shape* -- one
copy -- and the wrong *home*. The ops, their discovery, their runner and their
environments are scikit-ops', and a front end must offer Cellpose before its
environment exists, which is a fact about a collection of ops. So the
specification is tracked where the collection is.

The cost is a heavier dependency than the leaf opspec was: `skop` pulls
numpy and declares appose. Neither reaches skop-workflows at import -- the
spec module is standard library only, and `skop.runner` imports appose lazily
-- but scikit-ops is not the zero-dependency package opspec was.

## What the two had diverged on, and which side won

scikit-ops' survivor answers, and therefore ours:

| | opspec `op.py` | scikit-ops `_spec.py` |
|---|---|---|
| marker the decorator sets | `fn.__opspec__` | `fn.__skop__` |
| how it is spelled | `@op` or `@op(env=...)` | `@op(...)`, always called |
| the inputs a form builds from | `params` (all) | `inputs` (`params` minus `Out`) |
| results | `outputs`, as `OutputSpec`s | `outputs` (names), `output_specs` (roles) |
| spec from a function | `OpSpec.from_op(fn)` | `spec(fn)`, cached on `fn.__skop_spec__` |
| what the decorator carries | `env` | `env`, `main_thread`, `exclusive` |
| computation forms (`Out`, `Mut`, `Choices`, `ParamsFor`) | absent | present |
| `Role` members | includes `boxes` | no `boxes`; a box is a `Role.shapes` |
| discovery | none | `discovery.py`: walk a package, read live signatures |

Three of these changed code, and are worth naming:

1. **`@op` is always called.** A workflow writes `@op()`, not `@op`: the
   keyword-only signature would otherwise take the function as `env`.
2. **`outputs` are names; `output_specs` carry the roles.** `Recorder._save`
   needs only the names, so a single unnamed output is the string `'result'`
   rather than an `OutputSpec`.
3. **`Role.boxes` is gone.** A box is drawn as a `Role.shapes` everywhere in
   this ecosystem; `skop.boxes` holds the converters.

One rule did not travel: a parameter must be JSON to be recordable, in
`params.py`. scikit-ops has no such rule, because it records nothing.

## What is verified

Read from `scikit-ops/src/skop/_spec.py`, `scikit-ops/src/skop/types.py` and
`scikit-ops/src/skop/__init__.py` on 2026-10-06, on scikit-ops' `main`. The
demo asserts the consequences in `demo/headless.py` (section 7e-bis): the demo
ops are `skop.is_op`, an op naming no environment is a workflow, an op naming
one is not, and the `Role` vocabulary has no `boxes`. Re-check the table when
scikit-ops moves.
