# Verified facts about the surrounding projects

Read from the local checkouts on 2026-10-04: `C:\Users\Tim\scikit-ops`, a
worktree of its branch `recorder_and_icechunk`, `C:\Users\Tim\opspec`,
`C:\Users\Tim\appose-python`, and `C:\Users\Tim\napari`.

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

## opspec

- Standard library only. `@op(env=...)` sets an attribute and returns the
  function: a direct call is unaffected, and `@op` is **not** a recording
  hook.
- `OpSpec`: `name="module:function"`, `env`, `params` (`ParamSpec`: name,
  wire type, default, role, axes, ui), `outputs` (from a `NamedTuple`
  return), JSON round-trip. Wire types: `int, float, str, bool, ndarray,
  path, enum, unknown`.
- `Role`: boxes, image, labels, masks, points, shapes, surface, tracks,
  vectors. `Axes`: names are hints, arity binds.
- `Runner` protocol: `run(fn, args, *, axes, plans, position, on_progress,
  on_start, **kwargs)`, blocking, plus `close()`. `Builder` builds
  environments.
- No op version, no cost hint, no determinism flag, no recording.

## scikit-ops

- Ops are plain functions, discovered by import into a minimal env, so heavy
  imports must live inside function bodies. Environments live in
  `envs/<id>/pixi.toml`, keyed by id.
- An op with no `env` is a **workflow** (`OpSpec.is_workflow`): it runs on
  the host and calls other ops through an ambient runner. Host-side leaf ops
  and workflows look the same in the spec; only observed nested runs tell
  them apart.
- **Workers are kept warm by scikit-ops**: `Runner.service()` caches one
  service per `(env, variant, exclusive)`, and ops sharing an environment
  share a worker. `Runner.release()` returns cached GPU memory; `close=True`
  shuts a worker down. Appose provides the worker primitive underneath.
- The ambient mechanism: `_run_here` does `_current.set(_Ambient(self,
  task))` — unconditionally — and the module-level `skop.run()` dispatches
  through `_current.get()`. **A wrapper runner is therefore bypassed for
  nested calls** until decision 16's patch lands.
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

## Older approaches (not carried over)

- ndev-workflows' graph is a dask-style task dict executed by
  `dask.threaded.get`; networkx is used only to draw the inspector.
- Recording came from `napari-workflows.WorkflowManager`; its YAML loader
  needed placeholders for unknown callables.
