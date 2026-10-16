"""Export positioned NetworkX graphs as standalone TikZ picture contents."""
from __future__ import annotations

from pathlib import Path
import platform
import subprocess

import networkx as nx

from graph_builder_lib import (
    _edge_curve_points,
    _interpolating_curve_samples,
    colormap_1,
)

def _color_index(attributes):
    try:
        return max(0, int(attributes.get('col', 0)))
    except (TypeError, ValueError):
        return 0


def _rgb(color_index):
    return ','.join(str(channel) for channel in colormap_1(color_index))


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
        f'\\tikzstyle{{vertex_{color_index}}}=[circle, draw=vertexcolor{color_index}, fill=vertexcolor{color_index}, minimum size=5pt, inner sep=0pt]'
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

    for node in nodes:
        style = 'vertex_origin' if node == 0 or node == '0' else f"vertex_{_color_index(graph.nodes[node])}"
        x, y = tikz_position(positions[node])
        lines.append(
            f'    \\node[style={style}] ({node_ids[node]}) at ({x:.6f},{y:.6f}) {{}};'
        )
    lines.extend([
        r'  \end{pgfonlayer}',
        r'  \begin{pgfonlayer}{edgelayer}',
    ])

    for source, target, attributes in edges:
        color_index = _color_index(attributes)
        edge_style = f'edge_{color_index}'
        arrow = '->' if directed else '-'
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
        else:
            lines.append(
                f'    \\draw[style={edge_style},{arrow}] '
                f'({node_ids[source]}) to ({node_ids[target]});'
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


def _macos_save_path(default_path):
    """Ask macOS for a destination using its native Save As dialog."""
    escaped_name = default_path.name.replace('\\', '\\\\').replace('"', '\\"')
    result = subprocess.run(
        [
            '/usr/bin/osascript',
            '-e',
            'POSIX path of (choose file name with prompt "Save graph as TikZ:" '
            f'default name "{escaped_name}")',
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()) if result.stdout.strip() else None


def _portable_save_path(default_path):
    """Ask for a destination with Tk's native dialog on Windows and Linux."""
    from tkinter import Tk, filedialog

    root = Tk()
    try:
        root.withdraw()
        root.attributes('-topmost', True)
        selected = filedialog.asksaveasfilename(
            title='Save graph as TikZ',
            initialdir=str(default_path.parent),
            initialfile=default_path.name,
            defaultextension='.tex',
            filetypes=[('TikZ files', '*.tex'), ('All files', '*.*')],
        )
    finally:
        root.destroy()
    return Path(selected) if selected else None


def save_tikz_dialog(graph, default_path='graph.tex'):
    """Ask where to save TikZ, with a safe non-interactive fallback.

    macOS uses its familiar native dialog. Other desktop systems use Tk's
    cross-platform file dialog. If the required dialog cannot be opened (for
    example in a headless session), the export is written to ``default_path``.
    Cancelling a working dialog does not write a file.
    """
    default_path = Path(default_path)
    try:
        if platform.system() == 'Darwin':
            destination = _macos_save_path(default_path)
        else:
            destination = _portable_save_path(default_path)
    except Exception:
        # Tk can raise TclError when no graphical display is available. The
        # fallback also covers systems where Tk is not installed.
        destination = default_path

    if destination is None:
        return None
    if not destination.suffix:
        destination = destination.with_suffix('.tex')
    return write_tikz(graph, destination)
