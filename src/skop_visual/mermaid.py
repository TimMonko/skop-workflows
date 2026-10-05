"""Draw a GraphView as a Mermaid flowchart.

The static renderer: what survives in a README, a pull request or a markdown
cell. GitHub and VS Code render it as a diagram, and so does marimo, which is
the interactive home for it.
"""

from __future__ import annotations

from .model import SIGNALS, GraphView

_CLASS_DEFS = (
    'classDef fresh fill:#e6f4ea,stroke:#137333,color:#137333',
    'classDef stale fill:#fef7e0,stroke:#b06000,color:#b06000',
    'classDef affected fill:#f3e8fd,stroke:#8430ce,color:#8430ce',
    'classDef edited fill:#fce8e6,stroke:#a50e0e,color:#a50e0e',
    'classDef failed fill:#f1f3f4,stroke:#5f6368,color:#5f6368',
    'classDef root fill:#e8f0fe,stroke:#1967d2,color:#1967d2',
)


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
    lines.extend(f'    {definition}' for definition in _CLASS_DEFS)
    return '\n'.join(lines)
