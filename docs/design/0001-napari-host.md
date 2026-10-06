# Design note 0001: the napari host

Status: proposed, not built. Design notes say how something unbuilt will work;
a choice that carries cost graduates into [`decisions.md`](../decisions.md)
(and [`adr/`](../adr/) when it should outlive the conversation).

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

    {'step': 'smoothed', 'handle': '<a store handle>', 'run': '<a run id>'}

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
