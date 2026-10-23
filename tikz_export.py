"""Export positioned NetworkX graphs as standalone TikZ picture contents."""
from __future__ import annotations

from pathlib import Path

from graph_builder_lib import (
    _edge_curve_points,
    _interpolating_curve_samples,
    colormap_1,
    labels_visible,
)

def _color_index(attributes):
    try:
        return max(0, int(attributes.get('col', 0)))
    except (TypeError, ValueError):
        return 0


def _rgb(color_index):
    return ','.join(str(channel) for channel in colormap_1(color_index))


def _tikz_label(value):
    """Render an editor label as literal LaTex text, rather than source code."""
    replacements = {
        '\\': r'\textbackslash{}', '&': r'\&', '%': r'\%', '$': r'\$',
        '#': r'\#', '_': r'\_', '{': r'\{', '}': r'\}', '~': r'\textasciitilde{}',
        '^': r'\textasciicircum{}',
    }
    return ''.join(replacements.get(character, character) for character in str(value))


def graph_to_tikz(graph, max_width_cm=14.0, max_height_cm=9.0):
    """Return TikZ source scaled to fit a predictable page-sized area."""
    nodes = list(graph.nodes)
    node_ids = {node: f'v{index}' for index, node in enumerate(nodes)}
    positions = {
        node: graph.nodes[node].get('position', (0.0, 0.0))
        for node in nodes
    }

    if positions:
        min_x = min(position[0] for position in positions.values())
        max_x = max(position[0] for position in positions.values())
        min_y = min(position[1] for position in positions.values())
        max_y = max(position[1] for position in positions.values())
    else:
        min_x = max_x = min_y = max_y = 0.0
    graph_width = max(max_x - min_x, 1.0)
    graph_height = max(max_y - min_y, 1.0)
    coordinate_scale = min(max_width_cm / graph_width, max_height_cm / graph_height)

    vertex_colors = sorted({_color_index(graph.nodes[node]) for node in nodes})
    edges = []
    seen_undirected = set()
    directed = graph.graph.get('graph_type') != 'graph'
    for source, target, attributes in graph.edges(data=True):
        if not directed:
            logical_edge = frozenset((source, target))
            if logical_edge in seen_undirected:
                continue
            seen_undirected.add(logical_edge)
        edges.append((source, target, attributes))
    edge_colors = sorted({_color_index(attributes) for _, _, attributes in edges})

    lines = [
        r'\pgfdeclarelayer{edgelayer}',
        r'\pgfdeclarelayer{nodelayer}',
        r'\pgfsetlayers{background,edgelayer,nodelayer,main}',
        '',
    ]
    for color_index in vertex_colors:
        lines.append(f'\\definecolor{{vertexcolor{color_index}}}{{RGB}}{{{_rgb(color_index)}}}')
    for color_index in edge_colors:
        lines.append(f'\\definecolor{{edgecolor{color_index}}}{{RGB}}{{{_rgb(color_index)}}}')

    styles = [
        r'\tikzstyle{vertex_origin}=[circle, draw=black, fill=white, minimum size=5pt, inner sep=0pt]',
    ]
    styles.extend(
        f'\\tikzstyle{{vertex_{color_index}}}=[circle, draw=vertexcolor{color_index}, fill=vertexcolor{color_index}, text=white, minimum size=5pt, inner sep=0pt]'
        for color_index in vertex_colors
    )
    styles.extend(
        f'\\tikzstyle{{edge_{color_index}}}=[draw=edgecolor{color_index}, line width=1pt, fill=none]'
        for color_index in edge_colors
    )
    lines.extend(styles)
    lines.extend([
        '',
        f'\\begin{{tikzpicture}}[x={coordinate_scale:.6f}cm,y={coordinate_scale:.6f}cm]',
        r'  \begin{pgfonlayer}{nodelayer}',
    ])

    def tikz_position(position):
        return position[0] - min_x, max_y - position[1]

    show_labels = labels_visible(graph)
    for node in nodes:
        style = 'vertex_origin' if node == 0 or node == '0' else f"vertex_{_color_index(graph.nodes[node])}"
        x, y = tikz_position(positions[node])
        label = _tikz_label(graph.nodes[node].get('label', node)) if show_labels else ''
        lines.append(
            f'    \\node[style={style}] ({node_ids[node]}) at ({x:.6f},{y:.6f}) '
            f'{{{label}}};'
        )
    lines.extend([
        r'  \end{pgfonlayer}',
        r'  \begin{pgfonlayer}{edgelayer}',
    ])

    for source, target, attributes in edges:
        color_index = _color_index(attributes)
        edge_style = f'edge_{color_index}'
        arrow = '->' if directed else '-'
        label = _tikz_label(attributes.get('label', '')) if show_labels else ''
        controls = _edge_curve_points(graph, source, target)
        if controls:
            samples = _interpolating_curve_samples(
                positions[source], positions[target], controls
            )
            coordinates = ' '.join(
                f'({x - min_x:.6f},{max_y - y:.6f})'
                for x, y in samples
            )
            lines.append(
                f'    \\draw[style={edge_style},{arrow}] plot coordinates {{{coordinates}}};'
            )
            label_position = samples[len(samples) // 2]
        else:
            lines.append(
                f'    \\draw[style={edge_style},{arrow}] '
                f'({node_ids[source]}) to ({node_ids[target]});'
            )
            label_position = (
                (positions[source][0] + positions[target][0]) / 2,
                (positions[source][1] + positions[target][1]) / 2,
            )
        if label:
            x, y = tikz_position(label_position)
            lines.append(
                f'    \\node[fill=white, inner sep=1pt] at ({x:.6f},{y:.6f}) {{{label}}};'
            )

    lines.extend([
        r'  \end{pgfonlayer}',
        r'\end{tikzpicture}',
        '',
    ])
    return '\n'.join(lines)


def write_tikz(graph, file_path, max_width_cm=14.0, max_height_cm=9.0):
    """Write a TikZ picture to ``file_path`` and return the resulting path."""
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        graph_to_tikz(graph, max_width_cm, max_height_cm),
        encoding='utf-8',
    )
    return path
