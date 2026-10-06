# Design note 0002: what becomes a run

Status: proposed, not built.

A run is a *call* the recorder made, of a declared op. Nothing else is a run:
not an event, not a layer appearing, not a selection changing. The recorder
already refuses an array the store never issued a handle for, which is the
same rule from the other side — a call it can replay, or nothing.

## The ladder

Napari records nothing today: there is no hook around app-model command
execution, no macro recorder and no command history (verified in napari). So
capture is staged, most reliable first.

**1. Ops the dock runs.** The dock lists ops from the registry, builds a form
from the spec (magicgui, or magic-class for a richer one), and calls
`recorder.run(fn, step, args)` itself. Full fidelity: op id, parameters,
handles, replay. This is the first thing to build and it covers the demo.

**2. Other plugins' widgets, observed.** When a magicgui widget runs, its
result is turned into layers by napari's injected `return_callback`s, and the
new layer carries `layer.source.widget`; nothing announces it as an event.
The host can notice the layer appear and record a **placeholder run**: an op
id like `npe2:<plugin>:<widget>`, the widget's current parameter values read
off the `FunctionGui` as a best effort, and the output stored as a handle. The
id does not resolve in the registry, so the recipe carries a step that cannot
run (ADR 0002) — honest, and still useful, because the data is in the store
and downstream steps can consume it.

Doing this precisely means wrapping napari's type-keyed `return_callback`
entries (or the injected processors they call) so the moment is observed
rather than inferred. That is delicate, so it comes after 1.

**3. Napari actions.** There is nothing to hang a listener on. An action
becomes recordable the day a caller wraps it as an op and routes the call
through the recorder; until then the honest answer is "cannot be replayed".
If it matters enough, propose a hook upstream.

## What is never a run

Viewer state, a layer being deleted, a selection change, a plugin loading.
These can be *shown* by the host, but they are not calls, cannot be replayed,
and never enter the log.
