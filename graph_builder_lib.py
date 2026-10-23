"""Graph data and extension API shared by the Qt editor and custom scripts.

No GUI toolkit is imported here. Graphs remain NetworkX ``DiGraph`` objects;
an undirected edge is stored as two matching arcs for compatibility with old
GraphML files and with user-defined transformations.
"""
from __future__ import annotations

import colorsys
import copy
import json
from dataclasses import dataclass, field
from math import atan2, ceil, cos, floor, hypot, pi, sin, sqrt
from pathlib import Path
from typing import Any, Callable

import networkx as nx
from networkx.readwrite import json_graph


DEFAULT_GRAPH_OPTIONS = {
    'graph_type': 'graph', 'num_edge_colors': 2,
    'num_vertex_colors': 4, 'show_labels': True,
}


def empty_graph(**options):
    graph = nx.DiGraph()
    graph.graph.update(DEFAULT_GRAPH_OPTIONS)
    graph.graph.update(options)
    return graph


def unused_label(graph):
    """Choose a new stable internal ID; visible labels may be duplicated."""
    index = 0
    while str(index) in graph:
        index += 1
    return str(index)


def colormap_1(index):
    if int(index) == 0:
        return (0, 0, 0)
    golden_ratio = (5 ** .5 - 1) / 2
    saturation = max(0, 1 - .075 * (int(index) // 5))
    return tuple(round(channel * 255) for channel in colorsys.hsv_to_rgb(
        (golden_ratio * (int(index) - 1)) % 1, 1, saturation,
    ))


def vertex_label(graph, node):
    return str(graph.nodes[node].get('label', node))


def edge_label(graph, source, target):
    return str(graph.edges[source, target].get('label', ''))


def labels_visible(graph):
    return graph.graph.get('show_labels', graph.graph.get('show_vertex_labels', True))


def logical_edges(graph):
    """Yield each visible edge once, including every directed arc."""
    directed = graph.graph.get('graph_type') != 'graph'
    seen = set()
    for source, target in graph.edges:
        key = (source, target) if directed else frozenset((source, target))
        if key not in seen:
            seen.add(key)
            yield source, target


def set_edge_label(graph, source, target, label):
    graph.edges[source, target]['label'] = label
    if graph.graph.get('graph_type') == 'graph' and graph.has_edge(target, source):
        graph.edges[target, source]['label'] = label


def flip_edge(graph, source, target, edge_color=0):
    """Toggle a logical edge using the editor's paired-arc convention."""
    if source == target:
        return
    if graph.graph.get('graph_type') == 'graph':
        if graph.has_edge(source, target) or graph.has_edge(target, source):
            graph.remove_edges_from(((source, target), (target, source)))
        else:
            graph.add_edge(source, target, col=edge_color)
            graph.add_edge(target, source, col=edge_color)
    elif graph.has_edge(source, target):
        graph.remove_edge(source, target)
    else:
        graph.add_edge(source, target, col=edge_color)


def set_directed(graph, directed):
    if not directed:
        for source, target, data in list(graph.edges(data=True)):
            if not graph.has_edge(target, source):
                graph.add_edge(target, source, **copy.deepcopy(data))
    graph.graph['graph_type'] = 'digraph' if directed else 'graph'


def _edge_curve_points(graph, source, target):
    """Read absolute curve points from current or older GraphML attributes."""
    if not graph.has_edge(source, target):
        return []
    data = graph.edges[source, target]
    relative = bool(data.get('curve_offsets'))
    value = data.get('curve_offsets') or data.get('curve_points')
    if not value:
        return []
    try:
        points = json.loads(value) if isinstance(value, str) else value
        points = [(float(x), float(y)) for x, y in points]
    except (TypeError, ValueError):
        return []
    if relative:
        start = graph.nodes[source]['position']
        end = graph.nodes[target]['position']
        midpoint = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
        return [(midpoint[0] + x, midpoint[1] + y) for x, y in points]
    return points


def _set_edge_curve_points(graph, source, target, points):
    if not graph.has_edge(source, target):
        return
    start = graph.nodes[source]['position']
    end = graph.nodes[target]['position']
    midpoint = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
    offsets = [(x - midpoint[0], y - midpoint[1]) for x, y in points]
    graph.edges[source, target]['curve_offsets'] = json.dumps(offsets)
    graph.edges[source, target].pop('curve_points', None)
    if graph.graph.get('graph_type') == 'graph' and graph.has_edge(target, source):
        graph.edges[target, source]['curve_offsets'] = json.dumps(list(reversed(offsets)))
        graph.edges[target, source].pop('curve_points', None)


def _circular_arc_samples(start, through, end, steps=48):
    x0, y0 = start
    x1, y1 = through
    x2, y2 = end
    determinant = 2 * (x0 * (y1 - y2) + x1 * (y2 - y0) + x2 * (y0 - y1))
    if abs(determinant) < 1e-8:
        return [start, through, end]
    center_x = ((x0*x0+y0*y0)*(y1-y2) + (x1*x1+y1*y1)*(y2-y0) + (x2*x2+y2*y2)*(y0-y1)) / determinant
    center_y = ((x0*x0+y0*y0)*(x2-x1) + (x1*x1+y1*y1)*(x0-x2) + (x2*x2+y2*y2)*(x1-x0)) / determinant
    radius = hypot(x0 - center_x, y0 - center_y)
    start_angle = atan2(y0 - center_y, x0 - center_x)
    via_angle = atan2(y1 - center_y, x1 - center_x)
    end_angle = atan2(y2 - center_y, x2 - center_x)
    positive = (end_angle - start_angle) % (2*pi)
    sweep = positive if (via_angle - start_angle) % (2*pi) <= positive else positive - 2*pi
    return [(center_x + radius*cos(start_angle + sweep*i/steps),
             center_y + radius*sin(start_angle + sweep*i/steps)) for i in range(steps + 1)]


def _interpolating_curve_samples(start, end, points, steps=32):
    if not points:
        return [start, end]
    if len(points) == 1:
        return _circular_arc_samples(start, points[0], end)
    path = [start, *points, end]
    samples = [start]
    for segment in range(len(path) - 1):
        p0, p1 = path[max(0, segment - 1)], path[segment]
        p2, p3 = path[segment + 1], path[min(len(path) - 1, segment + 2)]
        for step in range(1, steps + 1):
            t = step / steps
            t2, t3 = t*t, t*t*t
            samples.append(tuple(.5 * (
                2*p1[axis] + (-p0[axis]+p2[axis])*t
                + (2*p0[axis]-5*p1[axis]+4*p2[axis]-p3[axis])*t2
                + (-p0[axis]+3*p1[axis]-3*p2[axis]+p3[axis])*t3
            ) for axis in (0, 1)))
    return samples


def edge_samples(graph, source, target):
    return _interpolating_curve_samples(
        graph.nodes[source]['position'], graph.nodes[target]['position'],
        _edge_curve_points(graph, source, target),
    )


def radial_grid_divisions(ring, main_divisions):
    """Increase spoke density on outer rings to keep grid cells useful."""
    if ring <= 0:
        return main_divisions
    cell_threshold = 1 / sqrt(2)
    minimum_ring = max(1, ceil(cell_threshold / (2*sin(pi/main_divisions)) - 1e-12))
    if ring < minimum_ring:
        return 0
    divisions = main_divisions
    while 2*ring*sin(pi/(2*divisions)) >= cell_threshold - 1e-9:
        divisions *= 2
    return divisions


def triangular_grid_point(i, j, center=(0, 0), unit=30):
    """A triangular-lattice vertex in the horizontal-row basis."""
    return (center[0] + unit * (i + j / 2),
            center[1] + unit * sqrt(3) * j / 2)


def triangular_grid_coordinates(position, center=(0, 0), unit=30):
    """Inverse of ``triangular_grid_point`` for continuous lattice indices."""
    j = (position[1] - center[1]) / (unit * sqrt(3) / 2)
    return (position[0] - center[0]) / unit - j / 2, j


def triangular_grid_lines(bounds, center=(0, 0), unit=30, minor_step=1,
                          major_step=1):
    """Yield clipped (family, index, start, end) lines of the same lattice.

    Families are the constant-j, constant-i, and constant-(i+j) lines.
    The optional strides omit visually overcrowded minor lines, while always
    retaining integer-coordinate-unit lines via ``major_step``.
    """
    left, top, right, bottom = bounds
    corners = ((left, top), (left, bottom), (right, top), (right, bottom))
    coordinates = []
    for corner in corners:
        i, j = triangular_grid_coordinates(corner, center, unit)
        coordinates.append((j, i, i + j))
    directions = ((1.0, 0.0), (0.5, sqrt(3) / 2),
                  (-0.5, sqrt(3) / 2))
    for family, direction in enumerate(directions):
        first = floor(min(value[family] for value in coordinates)) - 1
        last = ceil(max(value[family] for value in coordinates)) + 1
        indices = (set(range(first - first % minor_step, last + 1, minor_step)) |
                   set(range(first - first % major_step, last + 1, major_step)) |
                   {0})
        dx, dy = direction
        for index in sorted(indices):
            x0, y0 = triangular_grid_point(0 if family == 0 else index,
                                           index if family == 0 else 0,
                                           center, unit)
            low, high = float('-inf'), float('inf')
            for coordinate, delta, minimum, maximum in (
                    (x0, dx, left, right), (y0, dy, top, bottom)):
                if abs(delta) < 1e-12:
                    if coordinate < minimum or coordinate > maximum:
                        break
                else:
                    one, two = (minimum - coordinate) / delta, (maximum - coordinate) / delta
                    low, high = max(low, min(one, two)), min(high, max(one, two))
            else:
                if low <= high:
                    yield (family, index, (x0 + low * dx, y0 + low * dy),
                           (x0 + high * dx, y0 + high * dy))


def nearest_grid_point(position, mode, center=(0, 0), unit=30, radial_divisions=5):
    if mode == 'square':
        return tuple(center[i] + round((position[i] - center[i]) / unit)*unit for i in (0, 1))
    if mode == 'triangular':
        i, j = triangular_grid_coordinates(position, center, unit)
        best, best_distance = None, float('inf')
        # The closest point in this 60-degree basis is among the four corners
        # of the lattice-coordinate cell. Iterate j, then i for stable ties.
        for row in (floor(j), floor(j) + 1):
            for column in (floor(i), floor(i) + 1):
                candidate = triangular_grid_point(column, row, center, unit)
                distance = ((candidate[0] - position[0]) ** 2 +
                            (candidate[1] - position[1]) ** 2)
                if distance < best_distance - 1e-12 * unit * unit:
                    best, best_distance = candidate, distance
        return best
    if mode != 'radial':
        return position
    dx, dy = position[0] - center[0], position[1] - center[1]
    radius = hypot(dx, dy)
    base_ring = round(radius / unit)
    best, best_distance = center, radius
    minimum_ring = max(1, ceil((1/sqrt(2)) / (2*sin(pi/radial_divisions)) - 1e-12))
    for ring in range(max(minimum_ring, base_ring - 1), max(minimum_ring, base_ring + 2) + 1):
        divisions = radial_grid_divisions(ring, radial_divisions)
        angle = atan2(dy, dx)
        index = round(((angle + pi/2) % (2*pi)) / (2*pi/divisions)) % divisions
        candidate_angle = -pi/2 + 2*pi*index/divisions
        candidate = (round(center[0] + ring*unit*cos(candidate_angle), 12),
                     round(center[1] + ring*unit*sin(candidate_angle), 12))
        distance = hypot(position[0]-candidate[0], position[1]-candidate[1])
        if distance < best_distance:
            best, best_distance = candidate, distance
    return best


def snap_unselected_vertices(graph, selected_nodes, mode, center=(0, 0), unit=30,
                             radial_divisions=5):
    """Snap vertices outside the active selection, returning changed positions."""
    if mode not in ('square', 'triangular', 'radial'):
        return {}
    changed = {}
    for node, attributes in graph.nodes(data=True):
        if node in selected_nodes:
            continue
        old = attributes['position']
        new = nearest_grid_point(old, mode, center, unit, radial_divisions)
        if hypot(old[0] - new[0], old[1] - new[1]) > 1e-9:
            attributes['position'] = new
            changed[node] = new
    return changed


def convert_position(graph):
    """Create a GraphML-safe graph with x/y attributes and graph settings."""
    output = nx.DiGraph()
    output.graph.update(copy.deepcopy(graph.graph))
    for node, data in graph.nodes(data=True):
        attributes = copy.deepcopy(data)
        if 'position' in attributes:
            x, y = attributes.pop('position')
            attributes.update(position_x=float(x), position_y=float(y))
        output.add_node(str(node), **attributes)
    for source, target, data in graph.edges(data=True):
        output.add_edge(str(source), str(target), **copy.deepcopy(data))
    return output


def convert_from_file(graph_file, kwargs=None):
    """Read old and new editor GraphML into a normalized NetworkX graph."""
    options = dict(DEFAULT_GRAPH_OPTIONS)
    if kwargs:
        options.update(kwargs)
    if not Path(graph_file).exists():
        return empty_graph(**options)
    loaded = nx.read_graphml(graph_file)
    graph = nx.DiGraph()
    graph.graph.update(options)
    graph.graph.update(loaded.graph)
    if 'show_labels' not in loaded.graph and 'show_vertex_labels' in loaded.graph:
        graph.graph['show_labels'] = str(loaded.graph['show_vertex_labels']).lower() != 'false'
    else:
        graph.graph['show_labels'] = str(graph.graph['show_labels']).lower() != 'false'
    for key in ('num_edge_colors', 'num_vertex_colors'):
        graph.graph[key] = max(1, int(graph.graph[key]))
    for node, data in loaded.nodes(data=True):
        attributes = dict(data)
        x = float(attributes.pop('position_x', 0))
        y = float(attributes.pop('position_y', 0))
        attributes['position'] = (x, y)
        attributes['col'] = int(attributes.get('col', 0))
        graph.add_node(str(node), **attributes)
    for source, target, data in loaded.edges(data=True):
        attributes = dict(data)
        attributes['col'] = int(attributes.get('col', 0))
        graph.add_edge(str(source), str(target), **attributes)
    if graph.graph['graph_type'] == 'graph':
        for source, target, data in list(graph.edges(data=True)):
            if not graph.has_edge(target, source):
                graph.add_edge(target, source, **copy.deepcopy(data))
                points = _edge_curve_points(graph, source, target)
                if points:
                    _set_edge_curve_points(graph, source, target, points)
    for source, target in list(graph.edges):
        if graph.edges[source, target].get('curve_points'):
            _set_edge_curve_points(graph, source, target, _edge_curve_points(graph, source, target))
    return graph


def write_graph_file(graph, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    nx.write_graphml(convert_position(graph), path)
    return path


def _serialize_graph(graph):
    return json_graph.node_link_data(graph)


def _deserialize_graph(data):
    return json_graph.node_link_graph(data)


@dataclass(frozen=True)
class EdgeRef:
    source: Any
    target: Any
    directed: bool

    def __hash__(self):
        return hash((self.directed, (self.source, self.target) if self.directed else frozenset((self.source, self.target))))

    def __eq__(self, other):
        if not isinstance(other, EdgeRef) or self.directed != other.directed:
            return False
        return ((self.source, self.target) == (other.source, other.target) if self.directed
                else frozenset((self.source, self.target)) == frozenset((other.source, other.target)))


@dataclass
class SelectionState:
    nodes: set = field(default_factory=set)
    edges: set = field(default_factory=set)

    def clear(self):
        self.nodes.clear()
        self.edges.clear()

    def single_node(self):
        return next(iter(self.nodes)) if len(self.nodes) == 1 and not self.edges else None

    def prune(self, graph):
        self.nodes.intersection_update(graph.nodes)
        self.edges = {edge for edge in self.edges if graph.has_edge(edge.source, edge.target)}


@dataclass
class GraphClipboard:
    nodes: tuple
    node_attributes: dict
    internal_edges: tuple
    boundary_edges: tuple


def copy_graph_selection(graph, selected_nodes=None):
    selected = set(graph.nodes) if selected_nodes is None else set(selected_nodes) & set(graph)
    nodes = tuple(node for node in graph if node in selected)
    internal, boundary = [], []
    for source, target, data in graph.edges(data=True):
        if source in selected and target in selected:
            internal.append((source, target, copy.deepcopy(data)))
        elif source in selected or target in selected:
            boundary.append((source, target, copy.deepcopy(data)))
    return GraphClipboard(nodes, {node: copy.deepcopy(dict(graph.nodes[node])) for node in nodes},
                          tuple(internal), tuple(boundary))


def paste_graph_selection(graph, clipboard, offset=(20, 20)):
    output = copy.deepcopy(graph)
    mapping = {}
    for old in clipboard.nodes:
        new = unused_label(output)
        data = copy.deepcopy(clipboard.node_attributes[old])
        x, y = data.get('position', (0, 0))
        data['position'] = (x + offset[0], y + offset[1])
        output.add_node(new, **data)
        mapping[old] = new
    for source, target, data in (*clipboard.internal_edges, *clipboard.boundary_edges):
        if source in mapping or target in mapping:
            new_source, new_target = mapping.get(source, source), mapping.get(target, target)
            if new_source in output and new_target in output:
                output.add_edge(new_source, new_target, **copy.deepcopy(data))
    return output, set(mapping.values())


def cut_edges_to_rest(graph, selected_nodes):
    selected = set(selected_nodes)
    edges = [(source, target) for source, target in graph.edges
             if (source in selected) != (target in selected)]
    graph.remove_edges_from(edges)
    return len(edges)


@dataclass
class EditorContext:
    graph: nx.DiGraph
    selection: SelectionState
    box: Any
    interaction: Any = None
    pointer_position: tuple = (0, 0)

    def replace_graph(self, graph):
        self.graph = graph


@dataclass
class Action:
    id: str
    name: str | Callable[[EditorContext], str]
    shortcut: str | None
    handler: Callable[[EditorContext], Any]
    available: Callable[[EditorContext], bool]
    library: bool = False
    group: str = 'custom'
    checked: Callable[[EditorContext], bool] | None = None
    pair_label: str | Callable[[EditorContext], str] | None = None
    pair_id: str | None = None

    def is_available(self, context):
        return bool(self.available(context))

    def display_name(self, context):
        return self.name(context) if callable(self.name) else self.name


def execute_action(action, context):
    if not action.is_available(context):
        return False
    result = action.handler(context)
    if isinstance(result, nx.Graph):
        context.replace_graph(result)
    return True


def ContextAction(function, shortcut=None, available=lambda context: True, name=None, group='custom'):
    def invoke(context):
        result = function(context)
        if isinstance(result, nx.Graph):
            context.replace_graph(result)
    return Action(f'custom:{shortcut or name or function.__name__}', name or function.__name__,
                  shortcut, invoke, available, group=group)


def GraphAction(function, shortcut=None, name=None, group='custom'):
    return ContextAction(lambda context: function(context.graph), shortcut, name=name or function.__name__, group=group)


def VertexAction(function, shortcut=None, name=None, group='custom'):
    return ContextAction(lambda context: function(context.graph, context.selection.single_node()),
                         shortcut, lambda context: context.selection.single_node() is not None,
                         name or function.__name__, group)


def VertexGroupAction(function, shortcut=None, name=None, group='custom'):
    return ContextAction(lambda context: function(context.graph, set(context.selection.nodes)),
                         shortcut, lambda context: bool(context.selection.nodes), name or function.__name__, group)


def EdgeAction(function, shortcut=None, name=None, group='custom'):
    def invoke(context):
        edge = next(iter(context.selection.edges))
        return function(context.graph, (edge.source, edge.target))
    return ContextAction(invoke, shortcut,
                         lambda context: len(context.selection.edges) == 1 and not context.selection.nodes,
                         name or function.__name__, group)


def main(actions=(), graph_file=None, **options):
    """Launch the Qt editor with custom Python actions."""
    from graph_builder_qt import launch
    return launch(actions=actions, graph_file=graph_file, **options)
