# 0006 — Recording runs

**Status:** implemented (`oprecorder.recorder`, `oprecorder.record`).
Becomes `oprecorder/docs/design/0001` when the package moves into
scikit-ops. Condenses decisions 3, 5, 10, 11, 16, 23, 27, 33, 38, 46, 47,
50, 51, 53–56, 62, 66–67.

## What a run is

Every op called through a recorder is appended to a log as a `Run`: the op's
ID, the step it fills, its inputs as store handles, its JSON parameters, its
outputs as handles, the runner options that say how it ran, when it started,
how long it took, and its status (`ok`, `failed`, `cancelled`). The log is
append-only: running a step again adds a run, and the old ones stay. A root
(an input the user supplied) is a record too, so a root that moves makes its
readers stale; deleting its layer appends a `Detached` record.

What is recorded, and what is not:

| Recorded | Not recorded |
|---|---|
| array arguments, as the handles the store issued | the arrays themselves (they are the store's) |
| JSON parameters; enums by value, paths as strings, an op given as a parameter by its ID | anything that is not JSON: refused, not pickled |
| `variant`, `axes`, `plans`, `position` | `on_progress`, `on_start` (who to tell, not how to run) |
| | `memory`, `tiler`, `out` (this machine's limits, not what was computed) |

An optional array that was not given is the parameter `None`, not an input;
an `Out` buffer is never an input.

## Steps

A step is a position that successive runs fill: an op applied to particular
inputs. A call reuses a step when it reads the same sources (a root's name,
a step's name) as the step's last run; the same op on other inputs is a new
step (`smooth_2`); other parameters on the same inputs are another run of the
same step. The host may name a step itself (`Recorder.run(fn, step, args)`).

## Two ways in

- **`Recorder.run(fn, step, args)`**: a host that decides what to run calls
  it.
- **`RecordingRunner`**: looks like a runner. Whatever already runs ops (a
  panel, a script, a workflow calling `opspec.runtime.run`) is recorded by
  being handed it in place of the runner, and changes nothing else.

Both end in `Recorder.run`, the only place a run is written. The recorder
never runs an op itself: its inner runner does (`oprunner.Runner`, or
`oprunner.InProcess` by default), so an op that names an environment runs in
it exactly as without a recorder.

## Workflows

A workflow is recorded as its own run plus the runs of the ops it calls, each
nested step prefixed with its parent's, so the same op in two workflows is
two steps. For the duration of a workflow the recorder binds itself with
`opspec.runtime.bind_runner`; oprunner sends the workflow's calls through the
bound runner (`bound_runner()`), carrying the caller's progress, cancel and
tiler. So every call is recorded, and the caller's options still apply.

A workflow is exported and replayed as **one step**, never as its leaves: it
may do work between its calls that no leaf run records (see 0007).

## Cancelled is not ok

An op that sees a cancel returns what it has so far, which looks exactly like
a result. The recorder watches the cancel handle on its way to the caller,
records the run as `cancelled`, keeps what came back for inspection, and
leaves the step on its last finished run.

## Not decided

- What identifies an op's version. A run records the providing package's
  version (and a git commit for a checkout); see scikit-ops#3.
- Whether a workflow should be marked as one explicitly, rather than by
  having no `env`.
