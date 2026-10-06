"""Draw a GraphView as a Mermaid flowchart.

The static renderer: what survives in a README, a pull request or a markdown
cell. GitHub and VS Code render it as a diagram, and so does marimo, which is
the interactive home for it.
"""

from __future__ import annotations

from .model import COLOURS, ROOT_COLOURS, SIGNALS, GraphView


def _class_defs() -> tuple[str, ...]:
    """One Mermaid class per badge, coloured the way every renderer does."""
    defs = [
        f'classDef {badge} fill:{fill},stroke:{stroke},color:{stroke}'
        for badge, (fill, stroke) in COLOURS.items()
    ]
    fill, stroke = ROOT_COLOURS
    defs.append(f'classDef root fill:{fill},stroke:{stroke},color:{stroke}')
    return tuple(defs)


def _label(text: str) -> str:
    return text.replace('&', '&amp;').replace('"', '#quot;')


def to_mermaid(view: GraphView) -> str:
    """The view as a Mermaid flowchart, top to bottom."""
    ids = {node.step: f'n{i}' for i, node in enumerate(view.nodes)}
    lines = ['flowchart TB']
    roots: dict[str, str] = {}
    for node in view.nodes:
        signal = SIGNALS[node.badge]
        count = len(node.runs)
        if count > 1:
            signal = f'{signal} · {count} runs'
        short = node.op.rsplit(':', 1)[-1]
        label = f'{_label(node.step)}<br/>{_label(short)}<br/>{signal}'
        lines.append(f'    {ids[node.step]}["{label}"]:::{node.badge}')
    for edge in view.edges:
        if edge.target not in ids:
            continue
        if edge.source is None:
            key = edge.root or edge.param
            if key not in roots:
                roots[key] = f'r{len(roots)}'
                lines.append(
                    f'    {roots[key]}(["root {_label(key)}"]):::root'
                )
            source = roots[key]
        elif edge.source in ids:
            source = ids[edge.source]
        else:
            continue
        lines.append(
            f'    {source} -->|{_label(edge.param)}| {ids[edge.target]}'
        )
    lines.extend(f'    {definition}' for definition in _class_defs())
    return '\n'.join(lines)
