# skop-workflows

Recordable, replayable, batchable bioimage-analysis workflows built from ops, usable from napari and from scripts.

## Language

**Op**:
A function declared as capturable, callable identically from a script or from a napari widget. The only unit of capture.
_Avoid_: Action, step, task, node (when meaning the function itself)

**Run**:
One invocation of an op, with the data it consumed, its parameters, and the data it produced. A run of a workflow op contains the runs of the ops it called.
_Avoid_: Call, execution, record (record is the stored form of a run)

**Data handle**:
An opaque string, issued by the store, that names one stored version of one array. A run refers to its inputs and outputs by handle. Nothing outside the store parses one; the only requirement is that it resolves back to an array. Handles exist only in the local log, never in a recipe.
_Avoid_: Layer (a layer is napari's mutable view, not the data), reference, pointer, snapshot id (an Icechunk implementation detail)

**Store**:
Where arrays and run records live, and what issues handles. A directory of zarr arrays beside a JSON Lines log is one; Icechunk is another.
_Avoid_: Repository (Icechunk's word), backend, cache

**Log**:
The append-only set of every run, including discarded trials.
_Avoid_: History, session

**Graph**:
The steps and their current runs, derived on demand from the log; what a host
shows and what a replay selects from.
_Avoid_: DAG, flowchart

**Step**:
A position in a recipe, keyed by an op ID together with its output names, that successive runs of that op fill. Re-running with new parameters adds a run to the log and moves the step to it.
_Avoid_: Node (ambiguous between step and run), task

**Stale**:
A step whose input changed after its current run was made, so its output no longer matches its inputs.
_Avoid_: Dirty, outdated

**Edited**:
A step whose output data was changed by hand after its run, so a replay would not reproduce it. Changing a step's parameters or op is a new run, not an edit. A warning, not a block: unedited data may still flow through it.
_Avoid_: Detached, modified, tainted

**Affected**:
A step that consumed, directly or indirectly, the output of an edited step, so a replay would not reproduce it either.
_Avoid_: Tainted, downstream

**Paused**:
A mode of a whole recipe in which stale steps do not rerun automatically and the user steps through them deliberately, for example to hand-edit a result before continuing.
_Avoid_: Manual mode, frozen

**Recipe**:
The portable description of the steps that lead to the chosen targets, with inputs left as roots. Shareable with a colleague; carries no data handles and no absolute paths.
_Avoid_: Workflow (overloaded with the retired napari-workflows), pipeline

**Target**:
A step whose output a replay has been asked to produce. Replay runs the backward closure of the targets and nothing else.
_Avoid_: Deliverable (fine in prose, not in code), output (an output is a step's data; a target is a step you asked for)

**Pruning**:
Taking the backward closure of the targets: the steps, at their current runs, that producing them needs. Everything else in the log is simply not on the path.
_Avoid_: Cherry-picking, rebasing, filtering

**Host**:
The program driving ops and presenting their inputs and outputs: napari, a notebook, CellProfiler. A host decides nothing about what a recipe contains.
_Avoid_: Front end, GUI, client

**Root**:
A named input of a recipe, an image or a file such as a model path, that holds no value in the recipe and must be supplied at replay. Every other parameter keeps its recorded value as an editable default.
_Avoid_: Source, input file

**Replay**:
Running a recipe with every root bound to supplied data.
_Avoid_: Re-run (re-running an op in the viewer is not replay)

**Batch**:
Replaying one recipe over many input files.
_Avoid_: Sweep (one image, many parameter sets, is a different activity)
