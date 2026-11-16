# 0008 — Stores, handles and the graph

**Status:** implemented (`oprecorder.store`, `oprecorder.icechunk_store`,
`oprecorder.graph`). Becomes `oprecorder/docs/design/0003` when the
package moves. Condenses decisions 1, 3, 5, 8, 9, 21, 22, 37, 48, 49, 57,
58, 62 and ADRs 0001 and 0003.

## Stores and handles

A `Store` holds arrays and the log, and issues **handles**: opaque strings,
each naming one stored version of one array. Nothing outside the store
parses a handle; `Store.describe(handle)` names it for a recipe. Handles live
only in the local log, never in a recipe.

| Store | What it is | When |
|---|---|---|
| `SimpleStore` | a directory of zarr arrays beside a JSON Lines log | the default |
| `IcechunkStore` | an Icechunk repository; extra `[icechunk]` | atomic commits, tags, garbage collection, sharing over S3 |

Both are safe to use from two threads. A store takes any name (`ch1: DAPI`,
`a/b`, `Image` beside `image`) and encodes it into one path segment every
filesystem keeps apart; the handle keeps the name as given. A value numpy can
hold only as Python objects is refused rather than pickled; a scalar output
is stored as a 0-d array.

**Roots are held by reference, results are written.** `Recorder.root` calls
`Store.refer`, which keeps the object and what it looked like (name, ndim,
dtype) and writes nothing, so a lazy array is never read in full and
identity survives. What an op makes is written (`Store.put`), which is what
lets a deleted result be drawn again and a step rerun from where it was. The
price: data changed in place is changed for every version that refers to it,
and a root's data does not outlive the session (a recipe asks for it at
replay anyway).

## The graph is derived

`Graph` is the steps and their current runs, derived on demand from the log.
Lineage comes from each run's input and output handles, not from Icechunk's
history, which is a tree and cannot express a join.

What a step can be, all derived, none stored as state:

| | Meaning |
|---|---|
| **stale** | an input is not where it is now (`Graph.now(handle)`): a root moved, or an upstream step ran again |
| **edited** | its output was changed by hand after its run; a warning, not a block |
| **affected** | it read, directly or not, the output of an edited step |
| **kept** | an edit the user chose to keep: the pixels are stored and stand for the output; its readers are stale; nothing reruns it; a recipe asks for it as a root |
| **reverted** | an edit undone; the edit stays in the log |
| **missing** | an input's layer was deleted; nothing to catch up with, but it cannot be reproduced from this session |

Staleness waits for the user: bringing a step up to date is a deliberate
`update`, `rerun` or `produce(targets)`, which walks the closure in order.
Run durations are recorded so a host can decide what is cheap enough to
redo automatically; ops declare no cost.

The recorder and the graph know nothing about layers. A host supplies inputs
and accepts outputs; deleting a layer excludes nothing from the log.

## The picture

`oprecorder.view` turns a graph into nodes, edges and badges, and
`oprecorder.mermaid` renders that as Mermaid text. A renderer takes the view
and nothing else: no store, no Qt, no numpy.
