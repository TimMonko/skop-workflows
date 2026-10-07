# Design note 0003: hand edits and staleness

Status: built. The bracket and the marks are in skop-napari `_host.py`;
keeping an edit is decision 57, and the graph side of it is `Graph.now`.

## The bracket

Our writer brackets its own writes:

    with host.writing():
        layer.data = result

Anything that changes layer data outside the bracket is a user edit. Decision
24 named `layer.events.data`, and checking napari showed that is only half the
story (verified):

- assigning `layer.data = ...` emits `events.data`;
- painting in a Labels layer emits `events.paint`, **not** `events.data`;
- mutating in place (`layer.data[...] = ...`) emits nothing at all.

So the host listens to `data`, `paint` and `set_data`, and treats any of them
outside the bracket as a hand edit. In-place mutation stays undetectable — the
same blind spot that breaks handle identity — and the remedy is the same one
the glossary gives: an array changed outside an op must be declared, or it is
an edit that has to be marked.

## What a mark does

A mark is an appended `Event`; a run is never touched. `mark_edited` gives the
step the **edited** badge, and everything downstream is **affected**, derived
on read rather than stored (decision 9). Replay recomputes an edited step
without the edit, and export warns about the targets that will not reproduce.

## Accept and revert

- **Revert to run** copies the recorded output back over the layer, inside the
  bracket.
- **Accept edit** keeps the pixels and detaches the step from its op: the host
  puts the painted array in the store under the step name and appends the
  accepted mark, so the step becomes a root in every recipe that follows
  (decision 34). The host can do this because it is the one holding the array;
  nothing above the store changes.

## Refreshing

The dock recomputes badges when one of these happens: a run finishes, a data
event lands outside the bracket, layers are inserted or removed, the selection
changes, a parameter form changes, or the paused toggle flips. One refresh
path, no polling, and never a comparison of arrays.
