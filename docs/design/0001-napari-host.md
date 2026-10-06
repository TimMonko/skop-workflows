# Design note 0001: the napari host

Status: moved. The host, its `Display` seam and its dock were built here and
then moved to the sibling [`skop-napari`](../../../skop-napari) repo, which is
already the napari front end for this ecosystem and already owns the npe2
manifest. **This repo imports no napari and has no Qt**: what stays here is the
napari-free library -- the log, the graph, the recipes -- and the notes below
still describe the host's shape, which is the shape it has there.

What moved: the `Display` seam (decision 35), the id a host issues a layer
(decision 36), the dock itself, and `interactive_tests/workflows.py`. What
stayed behind and belongs here: `update`, `rerun` and `produce` on the
recorder, which never touched a layer.

## The host owns a recorder, not a model

A dock widget, **Workflows**, holds one `Recorder` (a store and a runner) and
draws the `Graph` derived from it. The widget never decides what a recipe
contains: it draws steps and forwards gestures. Everything it does with layers
goes through the recorder, which speaks only in ops and handles (decision 27).
The recorder tells the host what an op needs and accepts what it produced; the
host is what turns those into layers.

## Where the bookkeeping lives

A layer is a *view* of one step's output, and the link is kept in
`layer.metadata['skop']`:

    {'id': '<issued once>', 'step': 'smoothed',
     'handle': '<a store handle>', 'run': '<a run id>'}

The `id` is what the host knows the layer by (decision 36), and `step` is None
when the layer is a root.

`metadata` is a live dict, copied when a layer is created, and it travels in
`as_layer_data_tuple`, so the link survives a layer copy. Assigning into it
emits nothing (verified in napari), which is what we want: our bookkeeping
must not look like a user edit. The layer *name* is only a label — renaming a
layer changes nothing, because the step name lives in the metadata.

`layer.source` is not ours to write: it is a frozen pydantic `Source`, and
`_set_source` raises once it is populated. A file's provenance must be
annotated *during* creation, with napari's `layer_source(...)` context
manager. That is where a root's path hint (decision 6) comes from.

## Reading and writing arrays

- A layer that is new to the session is a root: `recorder.root(name,
  np.asarray(layer.data))`.
- A run's result is drawn as a layer named for the step, carrying the
  metadata above, through `viewer.add_image` / `add_labels`.
- `np.asarray(layer.data)` materializes, so v1 hands the store numpy. Lazy
  layers (dask, zarr) work but are read eagerly; a store that can hold a lazy
  array without materializing is a later concern and would not change this
  interface.

## Keeping in step with the viewer

Napari has no "file opened" event (verified), so the host watches
`viewer.layers.events.inserted` / `removed` / `reordered`, and
`selection.events.active`. Opening a file arrives as layers being inserted
with `layer.source.path` set, which is enough to name a root.

Deleting a layer excludes nothing from the log: the step stays and is simply
not drawn any more (decision 27). Showing it again re-adds the layer from its
stored handle.

## The widget

A list of steps, not a graph by default; the graph is a toggle underneath,
because a list answers "what do I do next" and a graph answers "why is this
here".

**Header.** Store path, a play/pause toggle for the recipe-wide paused mode,
and a session chooser.

**Step rows.** One per step: output name, the op's label, and one badge.

| Badge | Meaning |
|---|---|
| fresh | the current run matches its inputs |
| stale | an input step got a newer run |
| edited | the output data was changed by hand |
| affected | it consumed an edited step, directly or indirectly |
| running | a run is in flight, with progress and Cancel |
| failed | the last run failed; the previous run is still current |

Each row offers Update (enabled when stale), Rerun anyway, Open parameters
(focuses the op's own form), a target checkbox, and a runs expander. The
expander lists the sibling runs newest first, each with its parameters and
time, the current one marked, and Make current on the others — where the
sigma sweep lives: three runs, one current, nothing deleted.

**Selection is shared with the layer list.** Selecting a row selects its
layer, and vice versa.

**Editing.** A layer whose data changes outside our own writes gets the
edited badge, and everything downstream gets affected; the row then offers
Accept edit or Revert to run (see [0003](0003-edits-and-staleness.md)).

**Graph.** The same model the marimo app draws, rendered in the widget;
clicking a node scrolls to its row.

**Export.** A recipe preview with the warning list first: which targets will
not reproduce, and which roots must be supplied. Nothing is written until
that is read.

## What to build first

1. A `Recorder` over a chosen store, and imported layers declared as roots.
2. One op run from a generated form, recorded, drawn back as a layer.
3. Rows and badges read from the graph, including stale and edited.
4. The edit bracket and its marks ([0003](0003-edits-and-staleness.md)).
5. Export and replay buttons.
6. Batch over a folder.
7. The graph toggle.
8. Observing other plugins' widgets ([0002](0002-capturing-actions.md)).

Until the scikit-ops swap lands, step 2 runs through `InProcess`, which is
enough for everything above except nested workflow calls.

## What is built

In the sibling repo the host is `skop_napari/host.py`, and it imports no
napari: a *display* is the viewer, behind a two-method protocol -- list the
layers, and show one -- create it, or move the layer already drawing that step.
The napari adapter is `skop_napari/viewer.py`, which is deliberately not
re-exported from the
package root, so importing `skop_napari` cannot drag napari in. What the host
decides — what a root is, what gets drawn, what counts as a hand edit — is
asserted against a fake display in `_tests/test_host.py`; only the facts that
need napari are asserted against `make_napari_viewer` in `_tests/test_viewer.py`.

Built, from the list above: roots declared from the layers a viewer holds, on
`layers.events.inserted` (`watch`); one op run and drawn back, with the op's
role choosing an image or a labels layer; the `metadata['skop']` link; badges
read from `skop_visual`; the edit bracket, so the host's own writes are not
read as edits; and Revert to run (decision 37).

Three details the seam ended up carrying, all worth knowing:

- **A layer is known by an id the host issues, not by its name** (decision
  36). Renaming a layer changes nothing and does not make a second one. A
  layer's `source` cannot serve as the id: `Source` has no identity field and
  is frozen.
- **Edit detection compares identity.** Handing the same array back to
  `layer.data` is not an edit, so a paint that reports twice marks once. That
  is not a comparison of array *contents* — decision 24 still stands — but it
  is a comparison, and it is how a no-op assignment is told from a real one.
- **A hand edit to a root is the root moving, not a mark** (decision 38): a
  new version is stored and whoever read the old one goes stale.

## The dock

`src/skop_napari/widget.py` is the Workflows dock, attached with
`add_workflows(viewer, host)`, which wires the watch and the redraw in one
place. It draws what `Host.view()` says and nothing else: a row a step, with
its op, its badge and its run count; Update, Rerun anyway and Revert to run on
the selected row (Update enabled only when stale, Revert only when edited); a
form generated from the op's own parameters — a layer picker for an array, the
editor its wire type asks for otherwise (decision 39); and the graph as a
picture, drawn with `QGraphicsScene` in the very colours `skop_visual` gives
the Mermaid renderer.

`interactive_tests/workflows.py` opens a viewer on the demo session with the
dock attached and every step's current run drawn as a layer. It is the thing
to run when changing any of this.

Still to build: running off the GUI thread with progress and cancellation
(`thread_worker`), Accept edit (decision 34), the runs expander with its
make-current gesture, Paused and the session chooser, and multi-output steps
(the host refuses a step with more than one output rather than drawing it
wrongly).

## Setting up to run it

The napari being developed against is the sibling checkout, so the venv is
Python 3.13 and the `napari` dependency group takes it from `../napari` by
path, editable — machine-local, like the `tnia-dev` environment in
scikit-ops. `uv sync` builds it. `uv run pytest` runs the host tests and the
viewer tests; `uv run pytest src/skop_napari/_tests/test_host.py` runs the
part that needs no viewer, and `demo/headless.py` stays numpy-only. To look at
it, rather than test it: `uv run python interactive_tests/workflows.py`.
