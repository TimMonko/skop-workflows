# Verified facts about the surrounding projects

Read from the local checkouts on 2026-10-04: `C:\Users\Tim\scikit-ops`, a
worktree of its branch `recorder_and_icechunk`, `C:\Users\Tim\appose-python`,
and `C:\Users\Tim\napari`.

**These facts drift: re-verify before relying on any of them.**

## Icechunk

- Snapshots have one `parent_id`. `create_branch(name, snapshot_id)` forks
  from any snapshot. No merge or cherry-pick of branches was found.
- `rebase` only resolves concurrent-session conflicts at chunk level.
- Commits take arbitrary JSON `metadata`. `amend` replaces only the tip.
  `flush()` makes an anonymous snapshot with no branch, collected unless a
  branch or tag reaches it.
- `repo.transaction(branch, message=..., metadata=...)` commits on a clean
  exit.
- `LocalFileSystemStorage` is not safe for concurrent commits (a release is
  said to fix this).
- Checked again 2026-10-05, against icechunk 2.2.2 and zarr 3.4.0:
  - `icechunk.local_filesystem_storage(path)` then `Repository.open_or_create`
    (or `.open`). A fresh repo already has one snapshot, "Repository
    initialized", whose metadata carries `__icechunk.is_root`.
  - Writes: `repo.writable_session(branch)`, then `zarr.create_array(
    session.store, name='arrays/<name>/v<N>', data=...)` for nested paths,
    then `session.commit(message=..., metadata={...}, allow_empty=True)`,
    which returns the snapshot id. **After a commit the session's store is
    read-only**, so the next write needs a new session. A metadata-only
    commit is refused unless `allow_empty=True`.
  - Reads: `repo.readonly_session(branch='main')` or `readonly_session(
    snapshot_id=...)`. `repo.ancestry(branch='main')` walks newest first;
    each commit exposes `.id`, `.message`, `.metadata`.
  - Opening a repo prints Rust warnings: local-filesystem storage is unsafe
    for concurrent commits, and conditional-PUT readback wants
    `unsafe_use_metadata` (a lost-response caveat, not an error).

## opspec (now inside scikit-ops)

- A prototype that implemented the same op contract a second time, standard
  library only: `@op(env=...)` set `__opspec__` and returned the function, and
  `OpSpec.from_op` read it back.
- **Back, as scikit-ops' spec layer** (decision 45): it lives in
  `scikit-ops/opspec` and `skop` re-exports it. Earlier, it was dropped
  (decision 44): The specification is tracked in
  scikit-ops, where the ops are; the two copies had drifted, and the survivor
  is scikit-ops' `_spec.py`. `../opspec` is not a dependency of anything here.
- Its `Runner` was an interface only (`run(fn, args, *, axes, plans, position,
  on_progress, on_start, **kwargs)`, plus `close()`), with a `Builder` for
  environments. scikit-ops' runner is the one that runs now.
- What it had that scikit-ops does not, and what we gave up by dropping it
  (`Role.boxes`), is in [design note 0005](design/0005-the-op-contract.md).

## scikit-ops

- Ops are plain functions, discovered by import into a minimal env, so heavy
  imports must live inside function bodies. Environments live in
  `envs/<id>/pixi.toml`, keyed by id.
- **The op contract lives here** (decision 44): `@op(...)`, `OpSpec` /
  `ParamSpec` / `OutputSpec` (from opspec, read with `OpSpec.from_op(fn)`), `Role`,
  `Axes` and the wire vocabulary. `_spec.py` is standard library only,
  because it is imported in every worker.
- `OpSpec.outputs` is a tuple of `OutputSpec`s, each with a name, type and
  role. `Role.boxes` exists again (boxes are no longer drawn as `shapes`), and
  `skop.boxes` holds the converters.
- An op with no `env` is a **workflow** (`OpSpec.is_workflow`): it runs on
  the host and calls other ops through an ambient runner. Host-side leaf ops
  and workflows look the same in the spec; only observed nested runs tell
  them apart.
- **Workers are kept warm by scikit-ops**: `Runner.service()` caches one
  service per `(env, variant, exclusive)`, and ops sharing an environment
  share a worker. `Runner.release()` returns cached GPU memory; `close=True`
  shuts a worker down. Appose provides the worker primitive underneath.
- The ambient mechanism (checked 2026-10-07, branch `skop-workflows` of the
  scikit-ops checkout): `skop.ambient(runner, on_progress, on_start)`
  installs a runner for nested calls, and `_run_here` leaves an installed
  ambient alone, so the outermost installer wins (commit `9f83fe5`). The
  module-level `skop.run()` dispatches through it. **Uncommitted on top:**
  `_run_here` also reuses the installed ambient's task instead of making
  one nobody holds, so a workflow's own `progress()` and
  `cancel_requested()` reach the caller (decision 54; tested in
  `tests/test_nested_calls.py`).
- A cooperative cancel leaves no trace on the task: an op that sees
  `cancel_requested()` returns early, and Appose reports the task COMPLETE.
  Only a cancel that ends in an exception (an iterated plan, for one) is
  visible as such. Hence the recorder's watch on the handle (decision 56).
- `Runner.run` returns a NamedTuple only when the op's return type is one
  with those fields; `tuple[...]` comes back as a plain tuple, and a
  computer-form op returns its caller's buffer. `skop_core.outputs_of`
  labels all three.
- Plain arrays are copied to shared memory by `_codec` (two copies at peak).
  `lazy-array.md` is a proposal; nothing is built.
- Workflow docs list "saving a configured workflow as a re-runnable recipe"
  as deliberately not designed.
- `host.INIT` puts the checkout `src` at `sys.path[0]`, so a checkout
  shadows the pinned version in each env; the env lock digest alone does not
  identify op code.

## The recorder branch (to be replaced)

Branch `recorder_and_icechunk` of scikit-ops: `src/skop/record.py`,
`src/skop/icechunk_recorder.py`, and `Runner._record`.

- Hooks inside `Runner.run` after success. Commit metadata
  `{name, op, params, inputs}` on branch `main`; inputs look like
  `coins@<snapshot>`.
- Weaknesses: `identify` returns `None` for plain arrays (silent lineage
  break); one protocol mixes identity, storage and query; a single
  `original` tag allows one input per repo; failed or cancelled runs are not
  recorded; everything commits to `main`; no op version or lock digest;
  params stored as a Python dict.
- Strength: records on the host, never in the op's environment.

## Appose

- Environments via pixi, uv or mamba; workers; shared memory; tasks with
  progress, cooperative cancel and failure responses.

## napari

- No hook around app-model command execution, no macro or command history;
  only Labels has undo. `layer.source` records the widget object but not its
  arguments. Widgets return data through fixed processor callbacks in
  `_qprocessors.py`.
- Image and Labels can be lazy (dask, zarr). Points, Shapes, Surface, Tracks
  and Vectors are in-memory arrays plus a `features` DataFrame, or meshes.
- Checked again 2026-10-05:
  - `napari.qt.thread_worker` / `create_worker` (`src/napari/_qt/qthreading.py`)
    give `started` / `returned` / `errored` / `warned`, plus `yielded` and
    `paused` / `resumed` for generators; `progress=True` wires a progress bar;
    `worker.quit()` cancels.
  - `layer.metadata` is a live dict, copied at creation and included in
    `as_layer_data_tuple`; assigning a key emits nothing, replacing the whole
    dict emits `events.metadata`.
  - Data events: `events.data` on assignment, **`events.paint` on Labels
    painting** (not `data`), `events.set_data` on `refresh()`; in-place
    mutation emits nothing.
  - `layer.source` is a frozen `Source`; `_set_source` raises if it is already
    populated, so provenance must be attached during creation, with the
    `layer_source(...)` context manager.
  - `viewer.layers.events` emits `inserting(index)`, `inserted(index, value)`,
    `removing`, `removed`, `moving`, `moved`, `reordered`, `renamed`, plus
    `selection.events.changed` and `selection.events.active`.
  - Plugin widget results become layers through type-keyed entries in the
    injection store (`src/napari/_qt/_qapp_model/injection/_qprocessors.py`);
    magicgui's `return_callback`s call the same functions, and the new layer
    records `source.widget`. No event announces the call.
  - `napari.plugins._npe2.get_widget_contribution(plugin, widget)` returns
    `(callable, display_name)`; `pm.iter_widgets()` enumerates contributions.
  - No "file opened" event: drag/drop and `viewer.open` both go through
    `_add_layers`, so a watcher uses `layers.events.inserted` plus
    `layer.source.path` / `source.reader_plugin`.

## ndv

- Checked 2026-10-05. A viewer, not a renderer: it shows arrays in Qt, wx or
  Jupyter, with no browser-native frontend. The Jupyter frontend requires an
  IPython `ZMQInteractiveShell` and is built on `jupyter_rfb` + `ipywidgets`,
  so it does not render in marimo (tested: the app stays blank). `ndv.imshow`
  also calls `run_app()`, which assumes a GUI event loop. The Qt frontend
  (`ndv[qt]`) is the candidate for the future napari host; the marimo app
  keeps its matplotlib thumbnails.

## Older approaches (not carried over)

- ndev-workflows' graph is a dask-style task dict executed by
  `dask.threaded.get`; networkx is used only to draw the inspector.
- Recording came from `napari-workflows.WorkflowManager`; its YAML loader
  needed placeholders for unknown callables.
