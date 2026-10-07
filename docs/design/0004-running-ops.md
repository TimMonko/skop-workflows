# Design note 0004: running ops without freezing napari

Status: built for the napari host. The dock does not run ops: the Ops and
Workflows panels do, through a session's `RecordingRunner` (skop-napari
`_session.py`), over scikit-ops' own `Runner`, so environments, progress and
Cancel work as they always did. `cancelled` runs and durations are recorded
(decision 56).

## Off the GUI thread

An op run blocks, possibly for minutes (Cellpose, in a worker process), so it
must not run on the Qt main thread — napari's own rule. Napari ships the tool
for it: `napari.qt.thread_worker` (verified), a decorator giving a worker with
`started` / `returned` / `errored` / `aborted` signals, `yielded` for
progress, an optional progress bar (`progress=True`), and `quit()` to cancel.

(Superseded: the panel that runs the op already has the worker; the recorder
is pointed at it. What follows is the original proposal.)

The dock wraps each `recorder.run(...)` in such a worker and keeps it on the
step's row while it runs, so the row can show progress and a Cancel button.
Results come back on the main thread through the worker's signals; that is
where layers are added and the graph is refreshed.

## Progress and cancellation

scikit-ops' `Runner.run` already takes `on_progress` and `on_start`, relays
sub-op progress and hands back a task for cancelling (see
[upstream.md](../upstream.md)). The recorder forwards both: the dock turns
events into a row's progress and uses the task to cancel. A cancelled run
leaves a record with `status='cancelled'` (decision 56): the recorder watches
the cancel handle as it passes, because an op that honours a cancel simply
returns early and the task says nothing afterwards.

## One inner runner, many recorders

The inner runner is long-lived: scikit-ops keeps a warm worker per
environment, and rebuilding an environment per image is the thing to avoid.
Batch therefore makes one recorder per file (each with its own store) over the
*same* inner runner. The inner runner is now scikit-ops' `Runner`, and a
workflow's nested calls are recorded as child runs (`Run.parent`).

## Durations

The recorder times every call and records the duration with the run. That is
what decision 8 leans on: expense is measured rather than declared, so the
runs expander can show "sigma 2 · 1.8 s", and a batch can estimate its own
total before it starts.
