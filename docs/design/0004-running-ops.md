# Design note 0004: running ops without freezing napari

Status: proposed, not built.

## Off the GUI thread

An op run blocks, possibly for minutes (Cellpose, in a worker process), so it
must not run on the Qt main thread — napari's own rule. Napari ships the tool
for it: `napari.qt.thread_worker` (verified), a decorator giving a worker with
`started` / `returned` / `errored` / `aborted` signals, `yielded` for
progress, an optional progress bar (`progress=True`), and `quit()` to cancel.

The dock wraps each `recorder.run(...)` in such a worker and keeps it on the
step's row while it runs, so the row can show progress and a Cancel button.
Results come back on the main thread through the worker's signals; that is
where layers are added and the graph is refreshed.

## Progress and cancellation

opspec's `Runner.run` already takes `on_progress` and `on_start`, and
scikit-ops relays sub-op progress and hands back a task for cancelling (see
[upstream.md](../upstream.md)). The recorder forwards both: the dock turns
events into a row's progress and uses the task to cancel. A cancelled run
should leave a record with `status='cancelled'`, which the recorder does not
write yet — today only failures are recorded.

## One inner runner, many recorders

The inner runner is long-lived: scikit-ops keeps a warm worker per
environment, and rebuilding an environment per image is the thing to avoid.
Batch therefore makes one recorder per file (each with its own store) over the
*same* inner runner. Until the scikit-ops swap (decision 16) the inner runner
is `InProcess` and a workflow op's nested calls are invisible, so the dock
starts with single ops.

## Durations

The recorder times every call and records the duration with the run. That is
what decision 8 leans on: expense is measured rather than declared, so the
runs expander can show "sigma 2 · 1.8 s", and a batch can estimate its own
total before it starts.
