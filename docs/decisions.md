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
    only on opspec; storage sits behind the `Store` protocol.
11. **Workflow ops are recorded as parent plus leaf runs.** The recipe expands
    a workflow into its leaf steps; the parent is a grouping for the graph
    view. (For the nested-call mechanics, see 16.)
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
    ambient one, and opspec's runner contract gains the line "nested calls go
    through the runner the caller used". The alternative — subclassing
    scikit-ops' `Runner` — records nested calls with no patch but couples the
    recorder to scikit-ops. Still to build.
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
24. **Edit detection is a flag around the plugin's own writes.** Any
    `layer.events.data` outside that bracket is a user edit; the event always
    fires for layer edits, and detection never compares arrays.
25. **Three packages, not seven:** `core` (records, graph, pruning, state
    machine, replay), `store` (simple and Icechunk backends), `napari`
    (plugin and UI).
26. **The fork is scikit-ops only**, keeps the module name `skop`, is
    consumed by git URL and never published under that name; new libraries
    use the `skop_*` import prefix. Anything needed in opspec is vendored or
    carried as a patch until accepted.
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
    until then `accept_edit` only clears the edited mark.
