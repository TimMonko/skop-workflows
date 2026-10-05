# skop-workflows: design handoff

Status as of 2026-10-04. Written so another reader (human or LLM) can continue without the conversation. Terms are defined in [../GLOSSARY.md](../GLOSSARY.md); decisions with lasting cost are in [adr/](adr/). Source brief: [../OUTLINE.md](../OUTLINE.md).

## Goal

Recordable, replayable, batchable workflows made of **ops**, usable from napari and from plain scripts. A user runs ops (in napari widgets or a script), the system records what ran, the user keeps the outputs they care about, and the resulting **recipe** can be shared and **replayed** on other images, singly or in **batch**, in a fresh process with no napari. A task-graph view is a first-class requirement.

Hackathon context: I2K, with colleagues working on Appose, scikit-ops, Icechunk, Fiji and CellProfiler. Nothing upstream is fixed, including the op spec, the runner and the prototype recorder. The author is a napari developer and can change napari upstream.

## Scope

- In: capturing ops (anything that could equally be called from a script); arrays (Image and Labels first); recipes; replay; batch; graph view.
- Out: napari viewer state (serialized separately), manual annotation as an op, non-array layer types for now (points, shapes, tracks), backward compatibility with napari-workflows or ndev-workflows (a converter is someone else's job).
- Future: zarr-vectors-py and geff could hold points, shapes and tracks. Handles keep that open.

## Settled decisions

1. **Lineage is derived from run metadata, not icechunk's branches.** Icechunk history is a tree (one parent per snapshot, no merge of branches). Each run's commit carries input and output handles and parameters as metadata, and the graph is derived from those. See [ADR 0001](adr/0001-lineage-from-commit-metadata.md).
2. **Recipes hold op IDs and JSON parameters only, never importable callables.** Ops resolve through a registry of installed packages. Unknown IDs load as placeholders. Environment specs are a separate explicit consent. See [ADR 0002](adr/0002-recipes-hold-op-ids-not-callables.md).
3. **The log is append-only; the graph is what the user works in.** Re-running an op with new parameters adds a run to the log and makes that run the step's current one; every sigma tried stays as a sibling run and is never deleted. **Napari layers are not the model**: they are one host's way of presenting an op's inputs and outputs, and the recorder speaks only in ops and handles.
4. **Replay is driven by an explicit target set.** A **target** is a step whose output a replay has been asked to produce. Replay runs the backward closure of the targets and nothing else, so "only run what is needed" is the same rule as "return these". The default target set is the graph's leaves, and any intermediate may be named instead. There is no keep mark: what to return is decided when replaying or exporting, not marked in the log.
5. **Data handle = icechunk snapshot id plus array path.** Handles exist only in the local log, never in a recipe. A recipe names steps locally and leaves inputs as **roots**.
6. **Roots are named inputs supplied at replay.** This covers images and `path` parameters such as model files. Every other parameter keeps its recorded value as an editable default. A recipe stores a path root's basename only, as a hint.
7. **Batch means many files through one recipe.** Many parameter sets on one image is a different activity ("sweep"), not batch.
8. **Staleness is per-op.** Cheap ops may auto-run; expensive ops (Cellpose) go stale and wait for a one-click update. Default is stale-and-wait. **Paused** is a recipe-wide mode: stale steps do not auto-run and the user steps through.
9. **Hand edits are marked, not blocked.** A step whose output was changed by hand is **edited**; steps downstream of it are **affected**. Replay recomputes an edited step without the edit, so the export warns loudly and lists exactly which targets would not reproduce.
10. **Recording is a wrapper runner in its own generic library**, not `Runner(recorder=...)` inside scikit-ops. It depends only on opspec. Storage sits behind a protocol, with icechunk as a separate backend package. (Caveat in "Open decisions", Q30.)
11. **Workflow ops are recorded as parent plus leaf runs.** The recipe expands a workflow into its leaf steps. The parent is a grouping for the graph view.
12. **Op version is not added upstream yet.** Record, per run, the version (and git commit for checkouts) of the Python package that provided the op, plus a digest of the environment lock. Revisit an upstream `version` when opspec leaves prototype.
13. **A monorepo (uv workspace) of separate libraries**, with dependency direction enforced by import-linter.
14. **The graph view is its own library** (`*-visual`), one graph model with three renderers: napari widget, notebook, static text or Mermaid export. View-and-select unless editing is requested.
15. **Scope for the first spec:** the author's own small op contract for the recorder, proposed back to scikit-ops and opspec authors rather than waited on.
16. **Nested workflow calls go through the outermost runner.** Since a workflow op calls its leaves through an ambient runner, a wrapper around the runner would see only the outer call. scikit-ops gets a small patch that lets the outermost runner install itself as the ambient one, and opspec's runner contract gains the line "nested calls go through the runner the caller used". The alternative, subclassing scikit-ops' `Runner`, records nested calls with no patch but couples the recorder to scikit-ops. (Q30)
17. **The demo script below is the definition of done**, including the host-side demo workflow op in step 8 and the headless replay and batch in step 10. (Q31)
18. **Recipes are JSON**, with a pretty-printed form for humans and diffs. (Q32)
19. **Batch continues on failure and reports per file, with an option to stop at the first failure**, the way nbatch does. (Q33)
20. **scikit-ops is forked, not merely adapted.** The fork lives in this monorepo, is consumed by git URL, and keeps a written record of every divergence so each can be proposed upstream. Env pins point at the fork. (Q35)
21. **Icechunk is optional, and not first.** The recorder writes run records; Icechunk is one place they can land, not the thing that does the recording. A plain store (a directory of zarr arrays plus a JSONL, actually JSON Lines, log) comes first behind the same `Store` protocol. Icechunk is then the second backend, chosen for atomic commits, tags, garbage collection and sharing over S3. (Q36)
22. **A handle is an opaque string issued by the store**, not "snapshot id plus path". Icechunk issues a snapshot id; a simple store issues whatever it likes. Nothing outside the store parses a handle; the only requirement is that a handle resolves back to an array. (Q36)
23. **A step is keyed by its op ID together with its output names.** A parameter change is a new run of the same step; an op change starts a new step. (Q38)
24. **Edit detection is a flag around the plugin's own writes.** Any `layer.events.data` outside that bracket is a user edit, and that event always fires for layer edits. (Q39)
25. **Three packages, not seven:** `core` (records, graph, pruning, state machine, replay), `store` (simple and Icechunk backends), `napari` (plugin and UI). (Q40)
26. **The fork is scikit-ops only**, keeps the module name `skop`, is consumed by git URL and never published under that name; new libraries use the `skop_*` import prefix. Anything needed in opspec is vendored or carried as a patch until accepted. (Q41)
27. **The recorder and the log know nothing about layers.** A host supplies an op's inputs and accepts its outputs; napari does this with layers, a script with arrays. Deleting a layer therefore excludes nothing from the log; it only stops a host drawing it. (Q44)
28. **A session may hold several chains, and replay names the one it wants.** Replaying a session with two unrelated chains runs only the closure of the chosen targets. (Q45)
29. **Export writes the closure of the chosen targets**, so an abandoned branch never travels in a recipe file, while every intermediate a target needs is present and may itself be named as a target later. (Q46)
30. **A target is a (step, output name) pair**, named by the step alone when the op has one output. (Q47)
31. **Replay may name any step the recipe contains**, intermediates included, and nothing outside it. "The full thing" means naming every step; "just the deliverables" means the defaults. (Q48)
32. **The concept is a Target**, in code, in the glossary and in this document. (Q49)
33. **A step is named by the host, and the op belongs to its run.** In the prototype a step is the name the host gives the output (`normalized`, `labels`), and re-running that name with a different op adds a run rather than starting a step. This refines decision 23: the op is a property of the run, not of the step's identity, so an op swap on one output name is iteration rather than a new node. Two unrelated outputs that share a name still merge, and the answer to that is to name them differently. (Q50)

## Built so far

A headless prototype, `src/skop_core/`, with no napari, no Appose, no Icechunk and no scikit-ops. It exists to test the design rather than the integrations.

| File | Holds |
|---|---|
| `src/skop_core/op.py` | The small op contract: id, env, outputs, array params, cost. Stands in for `opspec.OpSpec` and shows what it would have to gain (`cost`, at least) |
| `src/skop_core/record.py` | `Run` and `Event`, and the JSON shape of each |
| `src/skop_core/store.py` | `Store` protocol and `SimpleStore`: `.npy` files plus a JSON Lines log |
| `src/skop_core/graph.py` | The derived graph: current run, staleness, edits, closure, leaves, roots |
| `src/skop_core/runner.py` | `Runner` protocol, `InProcess`, and `RecordingRunner`, which refuses an array the store never issued a handle for |
| `src/skop_core/recipe.py` | Export, plan, pre-flight check, replay, batch |
| `demo/headless.py` | The demo's steps 1 to 10, asserted: 24 checks |

Run it with any interpreter that has numpy:

```
python demo/headless.py
```

What it demonstrates, all passing: a root declared rather than assumed; three sibling runs of one step; a step going stale when its input moves on and nothing auto-running; a hand edit marked without touching the log; an undeclared array refused with a clear message; an abandoned branch kept out of the exported recipe; a recipe with no handle in it and a shape hint on its root; replay on a second image running exactly the steps the target needs and being recorded like any other run; a batch that carries on past a wrong-shaped file and says why; and an intermediate named as a target, which runs fewer steps than the default.

What it deliberately does not do: build an environment, dispatch to a worker, use Icechunk, record a nested workflow call, or touch napari. Those are the next four things, in that order.

## Verified facts about the surrounding projects

All read from the repos (local clones: `C:\Users\Tim\scikit-ops`, `scikit-ops-recorder` (a worktree of branch `recorder_and_icechunk`), `opspec`, `appose-python`, `ndev-workflows`, `napari`).

### Icechunk
- Snapshots have one `parent_id`. `create_branch(name, snapshot_id)` can fork from any snapshot. `ancestry_graph()` renders the tree. No merge or cherry-pick of branches was found in the docs.
- `rebase` only resolves concurrent-session conflicts at chunk level.
- Commits take arbitrary JSON `metadata`. `amend` replaces only the tip. `flush()` makes an anonymous snapshot with no branch, which `garbage_collect` deletes unless a branch or tag reaches it.
- `repo.transaction(branch, message=..., metadata=...)` commits only on a clean exit.
- `LocalFileSystemStorage` is not safe for concurrent commits (the author says a release fixes this).

### opspec (`True-North-Intelligent-Algorithms/opspec`, prototype)
- Standard library only. `@op(env=...)` sets an attribute and returns the same function, so a direct call is unaffected and `@op` is **not** a recording hook.
- `OpSpec`: `name="module:function"`, `env`, `params` (`ParamSpec`: name, wire type, default, role, axes, ui), `outputs` (`OutputSpec`, from a `NamedTuple` return), `to_dict` and `from_dict` as JSON.
- Wire types: `int, float, str, bool, ndarray, path, enum, unknown`. So array inputs are exactly the `ndarray` params, and JSON-only params are nearly free.
- `Role`: boxes, image, labels, masks, points, shapes, surface, tracks, vectors. `Axes`: names are hints, arity binds.
- `Runner` protocol: `run(fn, args, *, axes, plans, position, on_progress, on_start, **kwargs)`, blocking. `Builder` protocol builds environments.
- No op version, no cost hint, no determinism flag, no recording.

### scikit-ops (`apposed/scikit-ops`)
- Ops are plain functions, discovered by import into a minimal env, so heavy imports go inside the body. Environments live in `envs/<id>/pixi.toml` and are keyed by id. Ops in one env share a warm worker.
- Op with no `env` = a **workflow** (`OpSpec.is_workflow`): runs on the host and calls other ops via an ambient runner. A host-side leaf op looks the same in the spec.
- Demo-ready ops with no new env: `skop.ops.normalize:percentile` (env `minimal`, numpy only), `skop.ops.smooth:gaussian` and `skop.ops.threshold:otsu` (env `skimage`), `skop.ops.labels:connect` (`skimage`, scipy).
- Workflow docs list "saving a configured workflow as a re-runnable recipe" as deliberately not designed.
- `Runner._run_here` binds `_Ambient(self, task)`, where `self` is the inner `Runner`. **A wrapper runner is bypassed for nested calls.**
- `host.INIT` puts the checkout `src` at `sys.path[0]`, so a **checkout shadows the pinned version in each env**. The env lock digest alone does not identify op code.
- Plain arrays are copied to shared memory by `_codec` (two copies at peak). `lazy-array.md` is a proposal and nothing is built; for the demo, use the existing numpy shared-memory path.

### Prototype recorder (branch `recorder_and_icechunk`, to be replaced)
Files: `src/skop/record.py`, `src/skop/icechunk_recorder.py`, and `Runner._record` in `runner.py`.
- Hooks inside `Runner.run` after success. `Recorder` protocol: `identify`, `save`, `log`. Commit metadata: `{name, op, params, inputs}` on branch `main`; `inputs` look like `coins@<snapshot>`.
- Weaknesses: `identify` returns `None` for plain arrays (silent lineage break); one protocol mixes identity, storage and query (`log` is a name-filtered linear scan); a single `original` tag allows one input per repo; failed or cancelled runs are not recorded; everything commits to `main`; no op version or lock digest; params stored as a Python dict.
- Strength: records on the host, never in the op's environment. Nested workflow calls are recorded for free because they share the runner.

### Appose (`appose-python`)
- Environments via pixi, uv or mamba; workers; shared memory; tasks with progress, cooperative cancel and failure responses.

### ndev-workflows / napari-assistant (old approach, not carried over)
- ndev-workflows graph is a dask-style task dict `{name: (func, *args)}` executed by `dask.threaded.get`. networkx is used only to draw the graph in the inspector widget, and is in the dependency list because scikit-image already brings it.
- Recording came from `napari-workflows.WorkflowManager`, not from ndev-workflows itself.
- Legacy YAML load used a restricted SafeLoader with placeholders for unknown callables.

### napari (`C:\Users\Tim\napari`)
- No hook around app-model command execution, no macro or command history; only Labels has undo.
- `layer.source` records the widget object but not the arguments it was called with.
- Image and Labels can be lazy (dask, zarr). Points, Shapes, Surface, Tracks and Vectors are in-memory arrays plus a `features` DataFrame, or meshes.
- Widgets return data through fixed processor callbacks in `_qprocessors.py`.

## Demo script (the definition of done)

1. Open a 2D image in napari. It is imported into a store as root `image`.
2. Run `percentile` (`minimal`) into layer `normalized`.
3. Run `gaussian` (`skimage`), sigma 2, into `smoothed`. Handles cross two environments.
4. Re-run with sigma 17 then 18 into the same layer. Done when `smoothed` shows the latest result and the log holds three sibling runs.
5. Run `otsu` into `labels`. Change sigma back to 2. Done when `labels` is **stale** and the update is manual (paused).
6. Paint on `labels`. Done when it shows **edited** and nothing downstream silently recomputes.
7. Choose `labels` as the target and open the graph view. Done when the recipe is exactly the steps feeding `labels`, the sigma 17 and 18 runs are absent because they are not current, and the edit is flagged.
8. Run a small host-side demo workflow op `smooth_then_threshold` (calls `gaussian` then `otsu` via the ambient runner) on another layer. Done when parent and leaf runs are both recorded.
9. Export the recipe. Done when it contains no handles, paths or callables.
10. In a fresh Python process with no napari, replay the recipe on a different image, then batch it over a folder. Done when each file gets its own result and a failure on one file does not stop the rest.

## Planned packages (prefix undecided)

| Package | Owns | Depends on |
|---|---|---|
| `*-core` | Run, Step, Recipe types; op registry protocol; graph derivation; pruning; step state machine | opspec |
| `*-recorder` | `RecordingRunner` wrapper; `Store` protocol | core |
| `*-icechunk` | `Store` backend; handle identity | recorder, icechunk |
| `*-replay` | replay and batch executor | core, any opspec `Runner` |
| `*-skop` | scikit-ops registry adapter; ambient-runner shim | core, recorder, scikit-ops |
| `*-visual` | graph renderers (text, Mermaid, notebook) | core |
| `*-napari` | plugin; layer-to-handle mapping; stale and edited markers | all of the above |

## Recipe format (JSON sketch)

```json
{
  "format": 1,
  "roots": {"image": {"type": "ndarray", "role": "image"}},
  "steps": {
    "normalized": {"op": "skop.ops.normalize:percentile", "inputs": {"image": "@image"}, "params": {"low": 1.0, "high": 99.8}},
    "smoothed":   {"op": "skop.ops.smooth:gaussian", "inputs": {"image": "@normalized"}, "params": {"sigma": 2.0}},
    "labels":     {"op": "skop.ops.threshold:otsu", "inputs": {"image": "@smoothed"}, "params": {}}
  },
  "targets": ["labels"],
  "caution": {"edited": ["labels"], "affected": []}
}
```

Steps refer to each other by local name, never by handle. A multi-output reference is `@step.output`. A workflow's leaf steps carry an optional `"in": "<workflow step>"` for grouping.

## Replay and batch

- Pre-check: every op ID resolves, and every root and `path` parameter is bound. Nothing runs until the check passes.
- Run in dependency order through any opspec `Runner`. Non-root parameters default to recorded values and are overridable.
- Batch: one replay per file, report each outcome, continue after a failure, summarize at the end.
- Replay is recorded like any other run, in a per-input store.

## Step state machine

| Flag | Set when | Cleared when |
|---|---|---|
| stale | an input step got a new current run | the step reruns |
| edited | output data changed by hand | the step reruns (warn first: loses the edit) |
| running or failed | a run starts, or ends in error | next run |
| affected | derived: an upstream step is edited | never stored |

A failed run is logged, but the step keeps its last good run as current. Recording must therefore log failed and cancelled runs, which the prototype does not.

## Open decisions (asked, not yet answered; recommendation first)

- **Q50. Is a step named by the host, with the op belonging to the run?** This is what the prototype implements and it refines decision 23. Same output name plus a new op is one step, iterating; two unrelated outputs that happen to share a name merge, and the remedy is a different name. Recommendation: keep it, since it matches how a napari layer name already behaves and it keeps the op where it varies. The alternative, putting the op in the step's identity, means an op swap silently forks the graph instead of overwriting, which is likely to surprise more than it helps.

## Napari surface (sketch)

One dock widget, **Workflows**. A list of steps, not a graph by default; the graph is a toggle underneath, because a list answers "what do I do next" and a graph answers "why is this here".

**Header.** Store path, a play/pause toggle for the recipe-wide paused mode, and a session chooser.

**Step rows.** One per step, showing the output name, the op's label, and one badge:

| Badge | Meaning |
|---|---|
| fresh | the current run matches its inputs |
| stale | an input step got a newer run |
| edited | the output data was changed by hand |
| affected | it consumed an edited step, directly or indirectly |
| running | a run is in flight, with progress and Cancel |
| failed | the last run failed; the previous run is still current |

Each row offers Update (enabled when stale), Rerun anyway, Open parameters (focuses the op's own widget), a target checkbox, and a runs expander. The expander lists the sibling runs newest first, each with its parameters and time, the current one marked, and Make current on the others. This is where the sigma sweep lives: three runs, one current, nothing deleted.

**Selection is shared with the layer list.** Selecting a row selects its layer, and vice versa.

**Editing.** A layer whose data changes outside the plugin's own writes gets the edited badge, and everything downstream gets affected. The row then offers Accept edit, which keeps the pixels and detaches the step from its op so the step becomes a root, or Revert to run, which restores the recorded output.

**Graph.** A DAG of steps, colour-coded by badge, clicking a node scrolls to its row, and each node expands to its runs. Text and Mermaid renderers draw the same model, so a notebook and a pull request can show it.

**Export.** A recipe preview with the warning list first: which targets will not reproduce, and which roots must be supplied. Nothing is written until that is read.

## Risks to keep in view

- A recorder that works only for functions someone opted in to is acceptable, but any array computed outside an op breaks lineage silently. Treat it as an explicit root, never a silent one.
- In-place mutation breaks handle identity; **edited** exists for this reason.
- Host-side leaf ops and workflows are indistinguishable in the spec; only observed nested runs tell them apart.
- Everything upstream is in flux: the lazy-array proxy, the op spec, the runner. Pin versions and record what ran.
- GPU and some model ops are not bit-reproducible; replay reproduces the workflow, not necessarily identical pixels.
- Allowlist or registry design must stay JSON-only for params; arbitrary Python objects cannot be recipe parameters.
- **Icechunk may be doing no work in the demo.** See Q36. Adopting the heaviest dependency before anything needs it is the largest avoidable cost here.
- **Nothing in this design has been written down as code.** The vocabulary, decisions and demo script are complete enough to build against, but the demo's steps 1 to 6 should be running headless before any of the libraries are split out.
- **The fork changes op IDs' meaning without changing their spelling.** Same import name, same function path, possibly different code than upstream. Recipes cannot tell the two apart, so a record of the revision that ran matters more, not less.
- **Edit detection must not read whole arrays.** A flag around the plugin's own writes is cheap; a comparison against the stored handle is not.
- **Nothing in the log says which output is the point.** That is deliberate, and the cost is that a published workflow cannot state its author's intent. If it matters, put it on the exported file as a default target set, never in the log.
- **The design is host-neutral now.** Any code that reaches for a napari layer to decide what a recipe contains is a bug.

## Suggested next steps

1. Answer Q50.
2. Swap `RecordingRunner`'s inner runner for the real scikit-ops one, behind the fork, and see what the wrapper cannot reach (the nested-workflow problem in decision 16).
3. Add the `Store` backend for Icechunk and check that nothing above `store.py` changes.
4. Put the napari dock widget from the sketch in front of the prototype.
5. Reconcile the contract in `op.py` with `opspec.OpSpec`, and propose `cost` upstream.
