# The demo: the definition of done

The contract for the whole system, in ten steps. One 2-D image is opened, a
workflow is built, a result is chosen, then the workflow is exported and
replayed — first on one image, then over a folder.

1. Open a 2-D image in napari. It is imported into a store as root `image`.
2. Run `percentile` (`minimal` env) into layer `normalized`.
3. Run `gaussian` (`skimage` env), sigma 2, into `smoothed`. Handles cross
   two environments.
4. Re-run with sigma 17 then 18 into the same layer. Done when `smoothed`
   shows the latest result and the log holds three sibling runs.
5. Run `otsu` into `labels`. Change sigma back to 2. Done when `labels` is
   **stale** and the update is manual.
6. Paint on `labels`. Done when it shows **edited** and nothing downstream
   silently recomputes.
7. Choose `labels` as the target and open the graph view. Done when the
   recipe is exactly the steps feeding `labels`, the sigma 17 and 18 runs are
   absent because they are not current, and the edit is flagged.
8. Run a small host-side demo workflow op `smooth_then_threshold` (calls
   `gaussian` then `otsu` via the ambient runner) on another layer. Done when
   parent and leaf runs are both recorded.
9. Export the recipe. Done when it contains no handles, paths or callables.
10. In a fresh Python process with no napari, replay the recipe on a
    different image, then batch it over a folder. Done when each file gets
    its own result and a failure on one file does not stop the rest.

## What runs today

`demo/headless.py` asserts the headless parts, against three numpy-only ops
that stand in for the scikit-ops ones (34 checks; exits non-zero on failure):

- a root declared rather than assumed, and an undeclared array refused with a
  clear message
- three sibling runs of one step with the latest current; a step going stale
  when its input moves on, and nothing auto-running
- a hand edit marked without touching the log, and a step downstream of it
  marked affected
- an abandoned branch kept out of the exported recipe; a recipe with no
  handle in it and a shape hint on its root
- the target closure drawn as a Mermaid graph, the abandoned branch absent,
  the edit flagged, the root drawn once
- JSON containers accepted as parameters, numpy scalars recorded as plain
  Python, and default leaves taken from current runs
- replay on a second image running exactly the steps the target needs, and
  being recorded like any other run
- a batch that carries on past a wrong-shaped file and says why; a parameter
  override

Not yet built: the nested workflow op (step 8), the environments and worker
dispatch (steps 3–4 in their real form), Icechunk, and the napari surface —
including showing the graph view there (step 7; the model, the Mermaid
render and the marimo app exist).

## The graph app

`notebooks/graph.py` is a marimo app that records the demo scenario into a
temporary store and draws it: the Mermaid diagram — each node titled by step,
op and an emoji signal — beside a panel for one step, with tiny previews of
the arrays its current run consumed and produced, and a table of its runs.
A target picker prunes the diagram to the chosen closure, the rule export
uses.

    uv run marimo run notebooks/graph.py

## Honest caveats

- Replay reproduces the workflow, not necessarily identical pixels: GPU and
  some model ops are not bit-reproducible.
- A recorder works only for functions declared as ops (`@op`). Any array
  computed outside one breaks lineage silently unless declared as a root.
