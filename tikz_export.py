"""Export positioned NetworkX graphs as standalone TikZ picture contents."""
from __future__ import annotations

from pathlib import Path

from graph_builder_lib import (
    _edge_curve_points,
    _interpolating_curve_samples,
    colormap_1,
    labels_visible,
)
from graph_styles import contrast_text_color, effective_style
from graph_styles import vertex_boundary_distance

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
    styled = any(graph.graph.get(key) for key in ('vertex_styles', 'edge_styles',
                                                  'vertex_presets', 'edge_presets')) or any(
        data.get('style_overrides') or data.get('style_preset')
        for _, data in graph.nodes(data=True)) or any(
        data.get('style_overrides') or data.get('style_preset')
        for _, _, data in edges)
    vertex_appearances = {node: effective_style(graph, 'vertex', graph.nodes[node])
                          for node in nodes} if styled else {}
    edge_appearances = {(source, target): effective_style(graph, 'edge', attributes)
                        for source, target, attributes in edges} if styled else {}
    custom_colors = {}
    if styled:
        for style in vertex_appearances.values():
            custom_colors.update((value.lower(), None) for value in
                                 (style['fill'], style['outline'], style['text'])
                                 if isinstance(value, str) and value.startswith('#'))
        for style in edge_appearances.values():
            value = style['stroke']
            if isinstance(value, str) and value.startswith('#'):
                custom_colors[value.lower()] = None
        custom_colors = {value: f'graphstyle{index}'
                         for index, value in enumerate(sorted(custom_colors))}

    def color_name(value):
        return custom_colors.get(str(value).lower(), value)

    lines = [
        r'\pgfdeclarelayer{edgelayer}',
        r'\pgfdeclarelayer{nodelayer}',
        r'\pgfsetlayers{background,edgelayer,nodelayer,main}',
        '',
    ]
    if styled and any(style['shape'].removeprefix('hollow_') in ('diamond', 'triangle')
                      for style in vertex_appearances.values()):
        lines.insert(0, r'\usetikzlibrary{shapes.geometric}')
    for color_index in vertex_colors:
        lines.append(f'\\definecolor{{vertexcolor{color_index}}}{{RGB}}{{{_rgb(color_index)}}}')
    for color_index in edge_colors:
        lines.append(f'\\definecolor{{edgecolor{color_index}}}{{RGB}}{{{_rgb(color_index)}}}')
    for value, name in custom_colors.items():
        lines.append(f'\\definecolor{{{name}}}{{HTML}}{{{value[1:]}}}')

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
        appearance = vertex_appearances.get(node)
        label_value = graph.nodes[node].get('label', node)
        label = (str(label_value) if appearance and appearance['latex_label'] else
                 _tikz_label(label_value)) if show_labels else ''
        options = f'style={style}'
        if appearance:
            shape = appearance['shape']
            fill = appearance['fill']
            if shape.startswith('hollow_'):
                shape, fill = shape[7:], 'none'
            shape_options = {'circle': 'circle', 'square': 'rectangle',
                             'diamond': 'diamond', 'triangle': 'regular polygon, regular polygon sides=3',
                             'none': 'draw=none, fill=none'}.get(shape, 'circle')
            text_color = appearance['text']
            if text_color == 'auto':
                text_color = contrast_text_color(fill)
            options = (f'{shape_options}, draw={color_name(appearance["outline"]) if shape != "none" else "none"}, '
                       f'fill={color_name(fill) if shape != "none" else "none"}, '
                       f'text={color_name(text_color)}, '
                       f'minimum size={float(appearance["size"])*5/34:.3f}pt, '
                       f'line width={float(appearance["outline_width"])*.5:.3f}pt, inner sep=0pt')
            if appearance['tikz_options'].strip():
                options += ', ' + appearance['tikz_options'].strip()
        lines.append(
            f'    \\node[{options}] ({node_ids[node]}) at ({x:.6f},{y:.6f}) '
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
        appearance = edge_appearances.get((source, target))
        label_value = attributes.get('label', '')
        label = (str(label_value) if appearance and appearance['latex_label'] else
                 _tikz_label(label_value)) if show_labels else ''
        options = f'style={edge_style},{arrow}'
        if appearance:
            dash = {'solid': 'solid', 'dash': 'dashed', 'dot': 'dotted',
                    'dashdot': 'dash dot'}.get(appearance['pattern'], 'solid')
            options += (f',draw={color_name(appearance["stroke"])}, '
                        f'line width={float(appearance["width"])/2.6:.3f}pt, '
                        f'opacity={float(appearance["opacity"]):.3f}, {dash}')
            if appearance['tikz_options'].strip():
                options += ', ' + appearance['tikz_options'].strip()
        controls = _edge_curve_points(graph, source, target)
        if controls:
            samples = _interpolating_curve_samples(
                positions[source], positions[target], controls
            )
            if appearance and len(samples) > 1:
                # Convert the fixed TikZ point size back into graph-coordinate
                # units before trimming curved paths at the node boundaries.
                point_cm = 2.54 / 72.27
                def trimmed_endpoint(node, neighbor):
                    vertex = vertex_appearances[node]
                    dx = neighbor[0] - positions[node][0]
                    dy = neighbor[1] - positions[node][1]
                    distance = vertex_boundary_distance(vertex, dx, dy)
                    distance *= (5 / 34) * point_cm / coordinate_scale
                    length = (dx*dx + dy*dy) ** .5
                    if not length:
                        return positions[node]
                    distance = min(distance, length * .9)
                    return (positions[node][0] + dx*distance/length,
                            positions[node][1] + dy*distance/length)
                samples = list(samples)
                samples[0] = trimmed_endpoint(source, samples[1])
                samples[-1] = trimmed_endpoint(target, samples[-2])
            coordinates = ' '.join(
                f'({x - min_x:.6f},{max_y - y:.6f})'
                for x, y in samples
            )
            lines.append(
                f'    \\draw[{options}] plot coordinates {{{coordinates}}};'
            )
            label_position = samples[round((len(samples)-1) * float(appearance['label_t']))] if appearance else samples[len(samples) // 2]
            tangent_before = samples[max(0, round((len(samples)-1) * float(appearance['label_t']))-1)] if appearance else samples[max(0, len(samples)//2-1)]
            tangent_after = samples[min(len(samples)-1, round((len(samples)-1) * float(appearance['label_t']))+1)] if appearance else samples[min(len(samples)-1, len(samples)//2+1)]
        else:
            lines.append(
                f'    \\draw[{options}] '
                f'({node_ids[source]}) to ({node_ids[target]});'
            )
            t = float(appearance['label_t']) if appearance else .5
            label_position = ((1-t)*positions[source][0] + t*positions[target][0],
                              (1-t)*positions[source][1] + t*positions[target][1])
            tangent_before, tangent_after = positions[source], positions[target]
        if label:
            if appearance and appearance['label_offset']:
                from math import hypot
                dx = tangent_after[0] - tangent_before[0]
                dy = tangent_after[1] - tangent_before[1]
                length = hypot(dx, dy)
                if length:
                    offset = float(appearance['label_offset'])
                    label_position = (label_position[0] - dy*offset/length,
                                      label_position[1] + dx*offset/length)
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
