"""The workflow graph, inspectable.

Run it with:

    uv run marimo run notebooks/graph.py

A demo session is recorded into a temporary store, then the graph view is
drawn: the Mermaid diagram, a target picker (empty shows the whole session;
choosing steps keeps only their closure, the rule export uses), and a panel
for one step's runs, parameters and handles.
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

    from skop_visual import to_mermaid, view

    work = Path(tempfile.mkdtemp(prefix='skop-graph-'))
    recorder = build(work)
    everything = view(recorder.graph(), store=recorder.store)
    return (everything, recorder, to_mermaid, view)


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
    diagram
    return (picture,)


@app.cell
def _(mo, picture):
    picker = mo.ui.dropdown(
        options=[node.step for node in picture.nodes],
        label='inspect a step',
    )
    picker
    return (picker,)


@app.cell
def _(mo, picture, picker):
    import json

    node = next(
        (n for n in picture.nodes if n.step == picker.value),
        picture.nodes[0],
    )
    current = next((r for r in node.runs if r.current), None)
    lines = [
        f'### {node.step}',
        (
            f'`{node.op}` · badge **{node.badge}** · '
            f'flags: {", ".join(node.flags) or "none"}'
        ),
    ]
    if current is not None:
        params = ', '.join(f'{k}={v}' for k, v in current.params.items())
        lines.append(f'params: {params or "none"}')
        for edge in current.inputs:
            origin = (
                f'root {edge.root or edge.param}'
                if edge.source is None
                else edge.source
            )
            lines.append(f'- `{edge.param}` ← {origin}')
        for name, handle in current.outputs.items():
            lines.append(f'- {name} → `{handle}`')
    facts = mo.md('\n'.join(lines))
    runs = mo.ui.table(
        [
            {
                'run': r.id,
                'current': r.current,
                'status': r.status,
                'params': json.dumps(r.params),
                'error': r.error or '',
            }
            for r in node.runs
        ],
        selection=None,
    )
    mo.vstack([facts, runs])
    return
