# Settled decisions

Numbered so they can be cited from code and reviews ("see decision 16").
Promoted decisions move into [`adr/`](adr/); their numbers stay here.

1. **Lineage is derived from run metadata, not from Icechunk's branches.**
   Each run's record carries input and output handles and parameters, and the
   graph is derived from those. Icechunk history is a tree — one parent per
   snapshot — so it cannot express a join. See
   [ADR 0001](adr/0001-lineage-from-commit-metadata.md).
2. **Recipes hold op IDs and JSON parameters only, never importable
   callables.** Ops resolve through a registry; an unknown ID is a
   placeholder. Environment specs are a separate, explicit consent. See
   [ADR 0002](adr/0002-recipes-hold-op-ids-not-callables.md).
3. **The log is append-only; the graph is what the user works in.** Re-running
   an op adds a run and the previous ones stay. Napari layers are not the
   model: the recorder speaks only in ops and handles.
4. **Replay is target-driven.** A target is a step whose output the caller
   asked for; replay runs the backward closure of the targets and nothing
   else. The default targets are the graph's leaves. There is no keep mark in
   the log. See [ADR 0004](adr/0004-replay-is-target-driven.md).
5. **A handle is one stored version of one array**, as the store chooses to
   represent it. Handles live only in the local log, never in a recipe.
   (Refined by 22.)
6. **Roots are named inputs supplied at replay**, covering images and `path`
   parameters such as model files. Every other parameter keeps its recorded
   value as an editable default; a path root stores only its basename, as a
   hint.
7. **Batch means many files through one recipe.** Many parameter sets on one
   image is a "sweep", a different activity.
8. **Staleness is derived, and the default is stale-and-wait for every
   step.** There is no per-op cost declaration: expense depends on the
   machine, the data and the environment, so it is measured (run durations
   are recorded) rather than declared. Updating a stale step is a deliberate
   gesture; automatic updating, if ever wanted, is a host affordance informed
   by those measurements. **Paused** is a recipe-wide mode in which stale
   steps never rerun automatically and the user steps through them.
9. **Hand edits are marked, not blocked.** A hand-edited step is **edited**;
   steps downstream are **affected**. Replay recomputes an edited step
   without the edit, so export warns and lists the targets that will not
   reproduce.
10. **Recording is a layer around a runner, in its own generic library.** A
    `Recorder` holds a store and an executor; it is not itself a Runner, and
    it is never built into scikit-ops as `Runner(recorder=...)`. It depends
    only on scikit-ops' op contract; storage sits behind the `Store`
    protocol.
11. **Workflow ops are recorded as parent plus leaf runs.** The recipe expands
    a workflow into its leaf steps; the parent is a grouping for the graph
    view. (For the nested-call mechanics, see 16. The recipe half is
    superseded by 53: a workflow is exported as one step.)
12. **No upstream op version yet.** Each run records the providing package's
    version (and git commit for a checkout) plus a digest of the environment
    lock.
13. **A monorepo (uv workspace) of separate libraries**, with dependency
    direction enforced by import-linter. (See 25 for the package list.)
14. **The graph view is its own library**, one model with three renderers:
    napari widget, marimo/notebook, static Mermaid or text. View-and-select
    unless editing is requested.
15. **Scope for the first spec:** our own small op contract for the recorder,
    proposed back to scikit-ops and opspec rather than waited on.
16. **Nested workflow calls go through the outermost runner.** scikit-ops gets
    a small patch that lets the outermost runner install itself as the
    ambient one, and its runner contract gains the line "nested calls go
    through the runner the caller used". **Built** as `skop.ambient(runner)`
    in the scikit-ops working tree (not yet committed there), and used by
    `RecordingRunner`, which is how a panel, a script or a workflow is
    recorded by being pointed at it: the recorder stands where the runner
    stands, and never launches an op itself. (The patch is committed in
    scikit-ops; refined by 54.)
17. **The demo contract in [demo.md](demo.md) is the definition of done**,
    including the host-side workflow op (step 8) and the headless replay and
    batch (step 10).
18. **Recipes are JSON**, with a pretty-printed form for humans and diffs.
19. **Batch continues on failure and reports per file**, with an option to
    stop at the first failure, the way nbatch does.
20. **scikit-ops is forked, not merely adapted.** The fork lives in this
    monorepo, is consumed by git URL, and keeps a written record of every
    divergence so each can be proposed upstream. Env pins point at the fork.
21. **Icechunk is optional, and not first.** A plain store (a directory of
    arrays plus a JSON Lines log) comes first behind the same `Store`
    protocol; Icechunk is the second backend, chosen for atomic commits,
    tags, garbage collection and sharing over S3.
22. **A handle is an opaque string issued by the store.** Nothing outside the
    store parses one; `Store.describe(handle)` names it for a recipe. See
    [ADR 0003](adr/0003-store-is-optional-handles-are-opaque.md).
23. **A step is keyed by its op ID together with its output names.** A
    parameter change is a new run of the same step; an op change starts a new
    step. (Refined by 33.)
24. **Edit detection is a flag around the plugin's own writes.** Any data
    event outside that bracket is a user edit: `layer.events.data` on
    assignment, `layer.events.paint` when a Labels layer is painted (napari
    does not emit `data` there), `set_data` on refresh. In-place mutation
    emits nothing and stays undetectable. Detection never compares arrays.
    (Updated after checking napari, 2026-10-05.)
25. **Three packages, not seven:** `core` (records, graph, pruning, state
    machine, replay), `store` (simple and Icechunk backends), `napari`
    (plugin and UI).
26. **The fork is scikit-ops only**, keeps the module name `skop`, is
    consumed by git URL and never published under that name; new libraries
    use the `skop_*` import prefix. Anything needed in scikit-ops is carried
    as a patch until it is accepted upstream.
27. **The recorder and the log know nothing about layers.** A host supplies an
    op's inputs and accepts its outputs; deleting a layer excludes nothing
    from the log, it only stops that host drawing it.
28. **A session may hold several chains, and replay names the one it wants.**
29. **Export writes the closure of the chosen targets**, so an abandoned
    branch never travels in a recipe file, while every intermediate a target
    needs is present and may itself be named later.
30. **A target is a (step, output name) pair**, named by the step alone when
    the op has one output.
31. **Replay may name any step the recipe contains**, intermediates included,
    and nothing outside it.
32. **The concept is a Target**, in code, in the glossary, and in the docs.
33. **A step is named by the host, and the op belongs to its run.** Re-running
    an output name with a different op adds a run rather than starting a
    step; two unrelated outputs that share a name merge, and the remedy is to
    name them differently.
34. **Accepting an edit detaches the step: it is stored, and replay treats
    it as a root.** The host hands the accepted pixels to the recorder, which
    puts them under the step name; the step then has no producing op in a
    recipe, and its consumers list it as a root to supply at replay. Not
    built yet: it waits for the napari host that can pass the painted array;
    until then `accept_edit` only clears the edited mark. (Built: see 57.)
35. **The napari host keeps its bookkeeping in a module that imports no
    napari, behind a two-method protocol.** A host owns a recorder and a
    *display*; a display lists its layers and shows one. The napari adapter is
    `skop_napari/viewer.py` and the second adapter is a fake in the tests, so
    what the host decides is asserted without a viewer. It is called a
    *display* because "surface" is already a napari `Role` and layer type, and
    "staged" already means the buffered writes of the Icechunk store.
36. **A host knows a layer by an id it issues into the layer's metadata, not
    by the layer's name.** A name is a label: renaming must change nothing,
    and two layers may share a name. The id is written to
    `layer.metadata['skop']['id']`, so it survives a rename and travels with a
    layer copy. A layer's `source` cannot serve instead — `Source` has no
    identity field and is frozen, so there is nothing on a layer to borrow.
37. **Reverting an edit is a mark of its own.** A `reverted` event supersedes
    the `edited` one, so the step stops being edited and nothing downstream is
    affected any more, while the edit itself stays in the log. A revert is not
    a run: the output is already stored.
38. **A root declaration is a record in the log.** A root is not a step — it
    has no op, and a recipe supplies it at replay — but each version of it is
    recorded, so a root that moves under its consumers makes them stale.
    Without the record the question is unanswerable from the log, because root
    versions exist only in the store.
39. **An op's parameters are read off its function signature.**
    `OpInfo.params` is built from `inspect.signature` when the op is declared,
    in the shape scikit-ops calls `ParamSpec` (name, wire type, default,
    required): one less thing to keep in step with the function. (Superseded
    by 40.)
40. **opspec is the op contract; this library declares none of its own.**
    `@op`, `OpSpec`, `ParamSpec`, `Role` and the `Runner` protocol come from
    opspec, and the stand-in that mirrored them is gone. Two things opspec
    decides that were hand-written here: what an op's parameters are, and
    which of them are arrays -- a wire type, not a role, because an array may
    declare no role and a run still needs a handle for it. What stayed is the
    one rule opspec does not have: a parameter must be JSON to be recordable,
    in `params.py`. (Supersedes 15. Superseded by 44: opspec was a prototype,
    and the specification is tracked in scikit-ops.)
41. **The napari host lives in the sibling [`skop-napari`](../../../skop-napari)
    repo.** That is the front end this ecosystem already has: it owns the npe2
    manifest, op discovery, the axis mapping and the off-thread running. This
    repo imports no napari and has no Qt, and the seam between the two stays
    narrow so the host could be lifted out again. (Supersedes the napari
    package in 25.)
42. **Bringing a selection up to date is a recorder method, not a host's.**
    `update(fn, step)` re-runs a step taking each input from where it now is;
    `rerun(fn, step)` from where it was, and adds a run rather than moving the
    step; `produce(targets, registry)` walks the closure in order and updates
    whatever is stale. All three are about runs and stores rather than layers,
    and each takes the op, because a recorder resolves no IDs (decision 2).
43. **We do not bridge the two op contracts.** opspec's `@op` and scikit-ops'
    `@op` set different markers (`__opspec__`, `__skop__`), so neither
    recognises the other's ops. Building one spec from the other would be
    reimplementing the merge locally and would rot the day it lands, so we use
    opspec's and wait — see
    [design note 0005](design/0005-the-op-contract.md) for what scikit-ops
    would have to change. (Superseded by 44: there is no merge to wait for
    now — opspec is dropped and scikit-ops is the contract.)
44. **scikit-ops is the op contract; opspec is dropped.** opspec was a
    prototype that implemented a second copy of the same module, and the two
    copies drifted. We track the specification where the ops live, so `@op`,
    `OpSpec`, `ParamSpec`, `OutputSpec`, `spec()`, `Role`, `Axes`, the wire
    vocabulary and the `Runner` protocol come from `skop`, and each op is
    declared the scikit-ops way: `@op()` for a workflow, `@op(env=...)` for an
    op that names an environment. The one rule scikit-ops does not have stays
    here — a parameter must be JSON to be recordable, in `params.py`. Nothing
    bridges the old contract; what we gave up by dropping opspec, and the
    divergence we now live with, is recorded in
    [design note 0005](design/0005-the-op-contract.md). (Supersedes 40 and
    43.)
45. **opspec is back as scikit-ops' spec layer; we still import `skop`.**
    scikit-ops moved opspec into its own repo (`opspec/`, a workspace
    package) and takes `OpSpec`, `ParamSpec`, `Role` and the wire vocabulary
    from it, re-exported by `skop`. So nothing here imports `opspec`
    directly, and a spec is read with `OpSpec.from_op(fn)` rather than
    `spec(fn)`. Outputs are `OutputSpec`s (`spec.outputs`, each with a
    `name` and a `role`), and `Role.boxes` exists again. (Refines 44.)
46. **An op given as a parameter is recorded as its ID.** A workflow may take
    the op to use as a parameter (`psf_op`, `decon_op`). The recorder writes
    it as the op's ID, which is JSON, and `Recorder.run` turns an ID back
    into the function from the parameter's own choices, then from the
    recorder's registry. A recipe still holds no callable (decision 2).
47. **An optional array that was not given is not an input.** It is recorded
    as the parameter it is, `None`; an `Out` buffer is never an input.
48. **An input that loses its layer is *missing*, not stale.** Deleting the
    layer behind a root appends a `Detached` record. Steps that read it wear a
    `missing` badge: nothing newer exists to catch up with and the data is
    still in the store, so Produce has nothing to do, but the step can no
    longer be reproduced from the session it was made in. Declaring the name
    again undoes it, and moves the root, which does make its readers stale.
49. **An input is a name, and any layer can stand behind it.** Choosing
    another layer for an input stores that layer's pixels under the same name,
    so the steps that read it are stale and Produce brings them up to date on
    the new one. A root keeps its name when its layer is renamed.
50. **A step is an op applied to particular inputs.** `RecordingRunner` reuses
    a step only when the call reads the same sources (a root's name, a step's
    name) as the step's last run; the same op on other inputs is a new step,
    `smooth_2`. Other parameters on the same inputs are another run. A root
    that moved is still the same source. (Refines 23 and 33.)
51. **Enums and paths are recorded as JSON and revived by declared type.** An
    enum member is written as its value and a path as its string;
    `Recorder.run` turns them back from the parameter's declared type.
52. **A recipe says where each input comes from** (format 2). An input is
    `{'root': name}` or `{'step': name, 'output': name}`, never a bare
    `@name`: a root and a step may share a name (a layer called `smoothed`
    beside the step that made it), and a step may have several outputs, so
    neither may be left to a reader to guess. A recipe of another format is
    refused on load; there is no reader for format 1. (Refines 18 and 30.)
53. **A workflow is exported and replayed as one step, never expanded into
    its leaves.** A workflow may do work on the host between its calls that
    no leaf run records, so replaying its leaves would not reproduce it. Its
    nested runs stay detail in the graph. A step outside the workflow that
    read a nested output exports that nested run as a step of its own, since
    it is a run like any other. (Supersedes the recipe half of 11.)
54. **A recorder routes a workflow's calls back through itself, whoever
    started it.** `Recorder.run` makes a `RecordingRunner` ambient while a
    workflow runs, so replay, update, rerun and produce record nested calls
    and run them on the recorder's inner runner -- never on scikit-ops'
    default runner, which nobody configured. Naming nested steps
    (`step_for`) belongs to the recorder. scikit-ops' `_run_here` reuses the
    installed ambient's task, so a workflow's own `progress()` and
    `cancel_requested()` reach the handle the caller holds. (Refines 16; the
    `ambient` patch is committed in scikit-ops, the task reuse is not yet.)
55. **A run records the runner options that say how it ran.** `variant`,
    `axes`, `plans` and `position` go into `Run.options` as JSON, and
    update, rerun, produce and replay pass them back, so a step a panel ran
    plane by plane is run plane by plane again. `InProcess` honours plans
    the way scikit-ops' worker does. Progress and cancel handles are not
    recorded: they say who to tell, not how to run.
56. **A cancelled run is recorded as `cancelled`, and never becomes
    current.** An op that sees a cancel returns what it has so far, which
    looks exactly like a result. The recorder watches the cancel handle on
    its way to the caller, keeps what came back for inspection, and leaves
    the step on its last finished run. Every run also records when it
    started and how long it took (decision 8's measurement).
57. **Keeping an edit is built** (decision 34). `accept_edit(step, pixels)`
    stores the pixels; from then on they are the step's output. What read
    the old output is stale; a closure stops at the kept step; Produce never
    runs it again; a recipe asks for the pixels as a root named after the
    step (`step.output` for one of several outputs). Running the step again,
    or reverting, lets the kept pixels go, and whatever read them is stale.
    Underneath is one question, `Graph.now(handle)`: where the data a handle
    stood for is now. A run is stale when an input is not where it is now.
58. **A store takes any name, and refuses what it cannot write portably.**
    A step's or layer's name is encoded into one path segment that every
    filesystem keeps apart (`ch1: DAPI`, `a/b`, `Image` beside `image`,
    `con`); the handle keeps the name as given. A value numpy can only hold
    as Python objects is refused rather than pickled, and a scalar output is
    stored as a 0-d array. Both stores are safe to use from two threads.
59. **The core has a pytest suite beside the demo.** `demo/headless.py`
    stays the contract for the ten steps; `tests/` holds the edge cases, and
    runs each against every `Store` backend installed. (Amends 17.)
60. **A file parameter is a root of its own, never a recipe value** (decision
    6, built). A parameter whose wire type is `path` is recorded in
    `Run.paths`, apart from `params`; a recipe asks for it as the root
    `step.param` with only the file's name as a hint, and a replay must be
    handed a path for it. The log keeps the full path, since it is local.
61. **`scikit-ops/opspec` is the only opspec.** The standalone `../opspec`
    checkout (True-North) is retired: nothing reads it, nothing is ported to
    or from it, and its drift from scikit-ops' copy no longer matters.
    (Settles the question decision 45 left open.)
62. **A root is held by reference, never copied.** `Recorder.root` calls
    `Store.refer`, which keeps the object itself and what it looked like
    (name, ndim, dtype) and writes nothing; `get` hands back that very
    object, so identity survives and a lazy array is never read in full.
    The newest version of each name is held strongly, older ones weakly.
    Kept pixels (57) are held the same way. What an op makes is still
    written (`Store.put`), since that is what lets a deleted result be drawn
    again and a step be rerun from where it was. The price: data changed in
    place is changed for every version that refers to it, and a root's data
    does not survive the session (a recipe asks for it at replay anyway).
63. **Replay is prepare, check, run.** `prepare(recipe, registry, targets)`
    says what a replay needs before any data is at hand: its steps, each
    root (axes, dtype, the role its readers give it, a path's hint, the step
    kept pixels stood in for) and the ops that do not resolve. `run` binds
    the roots, names each session step (decision 50: same op on the same
    inputs is the same step, other inputs get `step_2`), tells the host
    before and after each step, and stops between steps when cancelled. An
    array the recorder already knows is used as it is, never declared again
    under the recipe's name, so a layer keeps its identity and a recipe can
    chain onto a step's output. `replay()` is a thin wrapper.
64. **A replay fits each step's axis plan to the data it is handed.** A
    recorded plan is kept when it was made for data with as many axes as the
    data at hand; otherwise the data is planned afresh by scikit-ops'
    planner, which iterates the axes an op does not consume, using the
    axis names the host passes for each root and the output axes of earlier
    plans. So an input read only by ops that declare `Axes` accepts data
    with more axes than were recorded (`RootNeed.plannable`): a recipe made
    on one plane runs plane by plane over a stack. What was planned is
    reported (`Replayed.planned`) and recorded with the run. Caveat:
    scikit-ops' `Runner` applies plans only to ops that name an
    environment, so a host-side op declaring `Axes` is handed the whole
    stack there (see review item 6).
