# 0007 — Recipes, replay and batch

**Status:** implemented (`oprecorder.recipe`, format 2). Becomes
`oprecorder/docs/design/0002` when the package moves. Condenses decisions
2, 4, 6, 7, 9, 18, 19, 28–31, 34, 52, 53, 57, 60, 63, 64 and ADRs 0002 and
0004.

## What a recipe is

The portable description of the steps that lead to chosen **targets**, with
inputs left as named **roots**. JSON, pretty-printed for diffs. It holds op
IDs and JSON parameters, never callables, data handles or absolute paths, so
it can be sent to a colleague and read on any machine.

A two-step recipe, as `export` writes it (from the demo's ops; compacted):

```json
{
  "format": 2,
  "targets": ["labels"],
  "roots": {"image": {"ndim": 2, "dtype": "float64"}},
  "steps": {
    "smoothed": {"op": "demo_ops:gaussian",
                 "inputs": {"image": {"root": "image"}},
                 "params": {"sigma": 2.0}},
    "labels":   {"op": "demo_ops:otsu",
                 "inputs": {"image": {"step": "smoothed", "output": "result"}},
                 "params": {}}
  },
  "caution": {"edited": [], "affected": [], "kept": []}
}
```

An op ID is `module:function`. `caution` lists the targets a replay will not
reproduce exactly (below).

Each input says where it comes from, `{"root": name}` or `{"step": name,
"output": name}`: a root and a step may share a name, and a step may have
several outputs. A recipe of another format is refused on load.

## Export: the closure of the targets

`export(graph, targets, store)` writes the steps the targets need, at their
current runs, and nothing else; the default targets are the graph's leaves.
An abandoned branch never travels; every intermediate a target needs is
present and may be named as a target later.

- A **file parameter** (wire type `path`) becomes a root of its own,
  `step.param`, with only the file's name as a hint.
- A **workflow** is one step (0006).
- An **edited** step (painted by hand) exports with a warning: replay
  recomputes it without the edit. A step whose edit was **kept** is not a
  step: its pixels cannot be recomputed, so the recipe asks for them as a
  root named after the step.

## Replay: prepare, check, run

1. `prepare(recipe, registry, targets)` says what a replay needs before any
   data is at hand: its steps, each root (axes, dtype, the role its readers
   give it, a path's hint), and the ops that do not resolve. A host builds
   its form from this.
2. `check(roots)` refuses missing or unsuitable roots.
3. `run(roots, recorder, ...)` binds the roots, records each step as an
   ordinary run (named as in 0006), tells the host before and after each
   step, and stops between steps when cancelled. Parameters can be
   overridden per step.

Ops resolve through a **registry** of op IDs; an unknown ID is reported, not
imported. A recorded **axis plan** is reused when it fits the data handed
in; otherwise the data is planned afresh from the axis names the host gives,
so a recipe made on one plane runs plane by plane over a stack
(`Replayed.planned` says what was planned).

`replay()` is the three in one call.

## Batch

`batch(recipe, files, ...)` is many input files through one recipe (one
image with many parameter sets would be a sweep, a different thing). It
continues past a failure and reports per file, or stops at the first if
asked.

## Not decided

- Who allocates an `Out` buffer for a computer-form op at replay (shape and
  dtype rule).
- Pinning op versions in a recipe (0006).
- Paused mode: a recipe-wide mode in which stale steps never rerun on their
  own. Specified (decision 8), not built.
