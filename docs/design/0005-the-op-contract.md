# Design note 0005: one op contract, and where it lives

Status: ours is settled, theirs is not. We declare ops with opspec's `@op`
(decision 40) and do not bridge anything. Unifying the two contracts is a
change to scikit-ops, and theirs to make.

## What we use

`demo/demo_ops.py` declares its ops with `from opspec.op import op` and types
them with `ImageOf` / `LabelsOf`, and `skop_core` reads them with
`OpSpec.from_op`. An op's parameters, their roles, and which of them are arrays
are therefore read off its own signature rather than restated beside it — which
is the whole point of decision 40, and why `array_params=` and `roles=` are
gone.

One consequence to know before building anything that lists ops: `is_op`
checks for the `__opspec__` attribute, so **a function decorated with
scikit-ops' `@op` is not an op to us**. The Record panel can list opspec ops —
today, the demo's three — and nothing else, until the two contracts are one.

## The two contracts, compared

They are the same module, implemented twice. `opspec/src/opspec/op.py` and
`scikit-ops/src/skop/_spec.py` both define `Role`, `Slot`, `Axes`, `WILDCARD`,
`CANONICAL`, `ALIASES`, `canonical`, `Choice`, `TypeSpec`, `ParamSpec`,
`OutputSpec`, `OpSpec`, `type_spec`, `_is_ndarray`, `_wire_default` and the
`role_of` / `axes_of` accessors — with the same values. Both say the same thing
about why they must stay dependency-free, in almost the same words: scikit-ops'
copy is "imported inside every worker environment, so it must depend on nothing
beyond the standard library", and opspec's README says the same. That is also
why swapping one for the other is cheap: opspec adds nothing to an environment.

They have drifted, in both directions:

| | opspec `op.py` | scikit-ops `_spec.py` |
|---|---|---|
| marker the decorator sets | `fn.__opspec__` | `fn.__skop__` |
| spec from a function | `OpSpec.from_op(fn)` | `spec(fn)`, cached in `fn.__skop_spec__` |
| what the decorator carries | `env` | `env`, `main_thread`, `exclusive` |
| `Role` members | includes `boxes` | no `boxes`; boxes map to `Role.shapes` |
| computation forms (`Out`, `Mut`, `Choices`, `ParamsFor`, `direction_of`, `choices_of`, `params_for_of`) | absent | present |
| axis and wire vocabulary | present | present, the same |
| discovery | none | `discovery.py`: walk a package, read live signatures |

Because the marker attribute differs, neither package recognises the other's
ops: `is_op` in either returns `False` for a function decorated by the other.

## What would have to change, and where

1. **scikit-ops deletes `_spec.py` and depends on opspec.** That is the
   direction, because opspec is the dependency-free package whose stated job is
   to be shared by plugins, runners and hosts, and because two copies of a
   shared contract drift by construction — as the table shows they already
   have. It is the deletion of a module, not a rewrite: the vocabulary matches.
2. **First, fold scikit-ops' extras into opspec**, deciding each one's side:
   - `Out`, `Mut`, `Choices`, `ParamsFor` and their accessors are
     *declarations* — annotated markers, exactly like `Role` and `Axes` — so
     they belong in opspec with the rest of the vocabulary.
   - `main_thread` and `exclusive` are *execution* hints: they say how a runner
     should call an op, not what the op is. opspec already owns the `Runner`
     protocol, so they belong beside it, with `env` as the precedent.
3. **`Role.boxes` goes the other way.** opspec has it; scikit-ops folds boxes
   onto `Role.shapes`. A box is not a shape with arbitrary vertices — a front
   end draws one as a rectangle and the other as a polygon — so `boxes` should
   win, and it is a one-line change in whichever package survives.
4. **Discovery stays in scikit-ops, and should.** opspec says nothing about
   finding ops, and should not: discovery is a fact about *a collection* —
   which package, which modules, and the rule that heavy imports live inside
   the function body, which discovery is what enforces. None of that is part
   of the contract an op declares.
5. **One accessor name.** `spec(fn)` builds a cached spec; `OpSpec.from_op(fn)`
   builds one. Pick one name. The cache is worth keeping, and is an
   implementation detail the contract need not mention.

## What we do meanwhile

Nothing here. We do **not** write a bridge that builds an opspec `OpSpec` from
a scikit-ops `OpSpec`, or the other way round: that is reimplementing the merge
locally, and it would rot the day the merge lands (decision 43). So the
collection appears in the Record panel when scikit-ops adopts opspec, and not
before.

## What is verified

The table was read from `scikit-ops/src/skop/_spec.py` and
`opspec/src/opspec/op.py` on 2026-10-06, on scikit-ops' `main`. The
consequence for the panels — that a scikit-ops op is invisible to
`opspec.op.is_op` — follows from the attribute check in each, and is the one
claim here worth re-checking when either package moves.
