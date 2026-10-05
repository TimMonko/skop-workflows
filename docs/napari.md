# Napari surface (sketch)

One dock widget, **Workflows**. A list of steps, not a graph by default; the
graph is a toggle underneath, because a list answers "what do I do next" and
a graph answers "why is this here". Nothing here is built yet.

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
(focuses the op's own widget), a target checkbox, and a runs expander. The
expander lists the sibling runs newest first, each with its parameters and
time, the current one marked, and Make current on the others — where the
sigma sweep lives: three runs, one current, nothing deleted.

**Selection is shared with the layer list.** Selecting a row selects its
layer, and vice versa.

**Editing.** A layer whose data changes outside the plugin's own writes gets
the edited badge, and everything downstream gets affected. The row then
offers Accept edit (keep the pixels, detach the step from its op so it
becomes a root) or Revert to run (restore the recorded output).

**Graph.** A DAG of steps, colour-coded by badge; clicking a node scrolls to
its row, and each node expands to its runs. The same model renders as
Mermaid for a notebook or a pull request.

**Export.** A recipe preview with the warning list first: which targets will
not reproduce, and which roots must be supplied. Nothing is written until
that is read.
