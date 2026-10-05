"""The workflow graph, inspectable.

Run it with:

    uv run marimo run notebooks/graph.py

A demo session is recorded into a temporary store, then drawn: the Mermaid
diagram beside a panel for the chosen step, with tiny previews of the arrays
its current run consumed and produced. Targets prune the diagram to their
closure, the rule export uses.
"""

import marimo

app = marimo.App(width='medium')


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _():
    import sys
    from pathlib import Path

    demo = Path(__file__).resolve().parents[1] / 'demo'
    if str(demo) not in sys.path:
        sys.path.insert(0, str(demo))
    return (Path,)


@app.cell
def _(Path):
    import tempfile

    from scenario import build

    from skop_visual import SIGNALS, to_mermaid, view

    work = Path(tempfile.mkdtemp(prefix='skop-graph-'))
    recorder = build(work)
    everything = view(recorder.graph(), store=recorder.store)
    return (SIGNALS, everything, recorder, to_mermaid, view)


@app.cell
def _(mo):
    from io import BytesIO

    import matplotlib
    import numpy as np

    matplotlib.use('Agg')

    from matplotlib import pyplot as plt

    def thumbnail(array):
        """A tiny image of one 2-D array; stacks show their middle plane."""
        data = np.asarray(array)
        while data.ndim > 2:
            data = data[data.shape[0] // 2]
        step = max(1, max(data.shape) // 256)
        data = data[::step, ::step]
        if np.issubdtype(data.dtype, np.floating):
            colormap = 'magma'
        elif np.issubdtype(data.dtype, np.bool_):
            colormap = 'gray'
        else:
            colormap = 'turbo'
        figure, axes = plt.subplots(figsize=(1.4, 1.4), dpi=90)
        axes.imshow(data, cmap=colormap, interpolation='nearest')
        axes.set_axis_off()
        buffer = BytesIO()
        figure.savefig(buffer, format='png', bbox_inches='tight', pad_inches=0)
        plt.close(figure)
        return mo.image(buffer.getvalue(), width=96)

    return (thumbnail,)


@app.cell
def _(everything, mo):
    targets = mo.ui.multiselect(
        options=[node.step for node in everything.nodes],
        label='targets (empty = whole session; chosen = their closure)',
    )
    targets
    return (targets,)


@app.cell
def _(mo, recorder, targets, to_mermaid, view):
    picture = view(
        recorder.graph(),
        store=recorder.store,
        targets=targets.value or None,
    )
    diagram = mo.mermaid(to_mermaid(picture))
    return (diagram, picture)


@app.cell
def _(mo, picture):
    picker = mo.ui.dropdown(
        options=[node.step for node in picture.nodes],
        label='inspect a step',
    )
    picker
    return (picker,)


@app.cell
def _(SIGNALS, mo, picture, picker):
    node = next(
        (n for n in picture.nodes if n.step == picker.value),
        picture.nodes[0],
    )
    flags = (
        ' · '.join(SIGNALS[flag] for flag in node.flags) or SIGNALS['fresh']
    )
    count = len(node.runs)
    header = mo.md(
        f'### {node.step}\n'
        f'`{node.op}`\n\n'
        f'{flags} · {count} run{"" if count == 1 else "s"}'
    )
    return (header, node)


@app.cell
def _(header, mo, node, recorder, thumbnail):
    current = next((run for run in node.runs if run.current), None)
    previews = []
    if current is not None:
        for edge in current.inputs:
            if edge.handle is not None:
                previews.append(
                    mo.vstack(
                        [
                            thumbnail(recorder.store.get(edge.handle)),
                            mo.md(f'`{edge.param}` · in'),
                        ],
                        align='center',
                    )
                )
        for name, handle in current.outputs.items():
            previews.append(
                mo.vstack(
                    [
                        thumbnail(recorder.store.get(handle)),
                        mo.md(f'`{name}` · out'),
                    ],
                    align='center',
                )
            )
    row = (
        mo.hstack(previews, gap=1, justify='start') if previews else mo.md('')
    )
    panel = mo.vstack([header, row], align='start')
    return (panel,)


@app.cell
def _(mo, node):
    import json

    table = mo.ui.table(
        [
            {
                'run': run.id,
                'current': run.current,
                'status': run.status,
                'params': json.dumps(run.params),
                'error': run.error or '',
            }
            for run in node.runs
        ],
        selection=None,
    )
    return (table,)


@app.cell
def _(diagram, mo, panel, table):
    mo.hstack(
        [diagram, mo.vstack([panel, table], align='stretch')],
        widths=[1, 1],
        align='start',
    )
    return
