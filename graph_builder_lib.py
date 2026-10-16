import networkx as nx
import pygame
import numpy as np
import time as ti
import colorsys
import json
from dataclasses import dataclass
from networkx.readwrite import json_graph
import copy
from math import atan2, ceil, cos, pi, sin
from pathlib import Path
from typing import Any, Callable

DEFAULT_GRAPH_FILE = 'graph.graphml'
RADIAL_GRID_OFFSET = -pi / 2

def dist(pos1, pos2):
    """
    Returns the euclidean distance between this vertex and the given position.
    """
    return ((pos1[0] - pos2[0]) ** 2 + (pos1[1] - pos2[1]) ** 2) ** 0.5


def _radial_grid_divisions(ring, main_divisions):
    if ring <= 0:
        return main_divisions
    minimum_ring = max(1, ceil(1 / (2 * sin(pi / main_divisions)) - 1e-12))
    if ring < minimum_ring:
        return 0
    divisions = main_divisions
    while 2 * ring * sin(pi / (2 * divisions)) >= 1 - 1e-9:
        divisions *= 2
    return divisions


def _nearest_grid_point(position, mode, center, unit, radial_divisions=4):
    if mode == 'square':
        return (
            center[0] + round((position[0] - center[0]) / unit) * unit,
            center[1] + round((position[1] - center[1]) / unit) * unit,
        )

    dx = position[0] - center[0]
    dy = position[1] - center[1]
    radius = (dx * dx + dy * dy) ** 0.5
    angle = atan2(dy, dx)
    base_ring = max(0, round(radius / unit))
    closest = center
    closest_distance = dist(position, center)
    minimum_ring = max(1, ceil(1 / (2 * sin(pi / radial_divisions)) - 1e-12))
    first_ring = max(minimum_ring, base_ring - 1)
    last_ring = max(first_ring, base_ring + 2)
    for ring in range(first_ring, last_ring + 1):
        ring_radius = ring * unit
        divisions = _radial_grid_divisions(ring, radial_divisions)
        step_angle = 2 * pi / divisions
        nearest_index = round(
            ((angle - RADIAL_GRID_OFFSET) % (2 * pi)) / step_angle
        ) % divisions
        candidate_angle = RADIAL_GRID_OFFSET + nearest_index * step_angle
        candidate = (
            center[0] + cos(candidate_angle) * ring_radius,
            center[1] + sin(candidate_angle) * ring_radius,
        )
        candidate_distance = dist(position, candidate)
        if candidate_distance < closest_distance:
            closest = candidate
            closest_distance = candidate_distance
    return closest


def snap_unselected_vertices(graph, selection, box, mode):
    if mode not in ('square', 'radial'):
        return False
    center = box.grid_origin
    unit = box.grid_unit
    changed = False
    for node, data in graph.nodes(data=True):
        if node in selection.nodes:
            continue
        snapped_position = _nearest_grid_point(
            data['position'], mode, center, unit, box.radial_divisions
        )
        if dist(data['position'], snapped_position) > 1e-9:
            data['position'] = snapped_position
            changed = True
    return changed


def toggle_grid_mode(box, interaction, graph, mode):
    if box.grid_mode == mode:
        box.grid_mode = None
        return
    if box.grid_mode is None:
        box.grid_origin = box.screen_to_real(
            (box.screen.get_width() / 2, box.screen.get_height() / 2)
        )
    box.grid_mode = mode
    interaction.cancel_gesture()
    interaction.selection.clear()
    interaction.selection.nodes.update(graph.nodes)

def colormap_1(k):
    """Map an integer color id to an RGB tuple."""
    if k==0 :
        return (0,0,0)
    else:
        phi = (np.sqrt(5)-1)/2
        eps = 0.015* 5*(k//5)
        return tuple(round(i * 255) for i in colorsys.hsv_to_rgb(phi*(k-1),1,1-eps))

def flip_edge(graph, v1, v2,edge_color=0):
    """Add or remove an edge (handles undirected as two arcs)."""
    match graph.graph["graph_type"] :
        case 'graph':
            if not v1 == v2 :
                if  (v1,v2) in graph.edges() or (v2,v1) in graph.edges():
                    if  (v1,v2) in graph.edges() :
                        graph.remove_edge(v1, v2)
                    if (v2,v1) in graph.edges() :
                        graph.remove_edge(v2, v1)
                else:
                    graph.add_edge(v1, v2)
                    graph.add_edge(v2, v1)
                    graph.edges[v1,v2]['col'] = graph.edges[v2,v1]['col'] = edge_color
        case _: #digraph
            if not v1 == v2 :
                if (v1,v2) in graph.edges():
                    graph.remove_edge(v1, v2)
                else:
                    graph.add_edge(v1, v2)
                    graph.edges[v1,v2]['col']= edge_color

def closest_vertex(graph, pos, min_distance = 30):
    """Return the vertex closest to the given screen position or None."""
    
    closest_vertex = None
    for vertex in graph.nodes:
        distance = dist(pos, graph.nodes[vertex]["position"])
        if distance < min_distance:
            min_distance = distance
            closest_vertex = vertex
    return closest_vertex


def _point_segment_distance(point, start, end):
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return dist(point, start)
    projection = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_squared
    projection = max(0, min(1, projection))
    closest = (start[0] + projection * dx, start[1] + projection * dy)
    return dist(point, closest)


def _point_in_polygon(point, polygon):
    if len(polygon) < 3:
        return False
    inside = False
    previous = polygon[-1]
    for current in polygon:
        if _point_segment_distance(point, previous, current) <= 1:
            return True
        if (current[1] > point[1]) != (previous[1] > point[1]):
            crossing_x = (previous[0] - current[0]) * (point[1] - current[1]) / (previous[1] - current[1]) + current[0]
            if point[0] < crossing_x:
                inside = not inside
        previous = current
    return inside


def _edge_curve_points(graph, source, target):
    if not graph.has_edge(source, target):
        return []
    value = graph.edges[source, target].get('curve_offsets')
    relative = bool(value)
    if not value:
        value = graph.edges[source, target].get('curve_points')
    if not value:
        return []
    try:
        points = json.loads(value) if isinstance(value, str) else value
        points = [tuple(point) for point in points]
        if relative:
            source_position = graph.nodes[source]['position']
            target_position = graph.nodes[target]['position']
            midpoint = (
                (source_position[0] + target_position[0]) / 2,
                (source_position[1] + target_position[1]) / 2,
            )
            return [(midpoint[0] + x, midpoint[1] + y) for x, y in points]
        return points
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def _set_edge_curve_points(graph, source, target, points):
    if not graph.has_edge(source, target):
        return
    source_position = graph.nodes[source]['position']
    target_position = graph.nodes[target]['position']
    midpoint = (
        (source_position[0] + target_position[0]) / 2,
        (source_position[1] + target_position[1]) / 2,
    )
    offsets = [(x - midpoint[0], y - midpoint[1]) for x, y in points]
    graph.edges[source, target]['curve_offsets'] = json.dumps(offsets)
    graph.edges[source, target].pop('curve_points', None)
    if graph.graph.get('graph_type') == 'graph' and graph.has_edge(target, source):
        graph.edges[target, source]['curve_offsets'] = json.dumps(list(reversed(offsets)))
        graph.edges[target, source].pop('curve_points', None)


def _real_to_screen_unclipped(box, position):
    x, y = position
    x1, y1, x2, y2 = box.visual_box
    return (
        int((x - x1) * box.screen.get_width() / (x2 - x1)),
        int((y - y1) * box.screen.get_height() / (y2 - y1)),
    )


def _circular_arc_samples(start, through, end, steps=48):
    x0, y0 = start
    x1, y1 = through
    x2, y2 = end
    determinant = 2 * (x0 * (y1 - y2) + x1 * (y2 - y0) + x2 * (y0 - y1))
    if abs(determinant) < 1e-9:
        return [start, through, end]

    center_x = (
        (x0 * x0 + y0 * y0) * (y1 - y2)
        + (x1 * x1 + y1 * y1) * (y2 - y0)
        + (x2 * x2 + y2 * y2) * (y0 - y1)
    ) / determinant
    center_y = (
        (x0 * x0 + y0 * y0) * (x2 - x1)
        + (x1 * x1 + y1 * y1) * (x0 - x2)
        + (x2 * x2 + y2 * y2) * (x1 - x0)
    ) / determinant
    radius = dist((center_x, center_y), start)
    start_angle = atan2(y0 - center_y, x0 - center_x)
    through_angle = atan2(y1 - center_y, x1 - center_x)
    end_angle = atan2(y2 - center_y, x2 - center_x)
    counterclockwise_sweep = (end_angle - start_angle) % (2 * pi)
    through_sweep = (through_angle - start_angle) % (2 * pi)
    if through_sweep <= counterclockwise_sweep:
        sweep = counterclockwise_sweep
        through_parameter = through_sweep / sweep if sweep else 0
    else:
        sweep = -((start_angle - end_angle) % (2 * pi))
        through_parameter = ((start_angle - through_angle) % (2 * pi)) / -sweep if sweep else 0

    parameters = sorted({step / steps for step in range(steps + 1)} | {through_parameter})
    samples = []
    for parameter in parameters:
        if abs(parameter - through_parameter) < 1e-9:
            samples.append((round(x1), round(y1)))
        else:
            angle = start_angle + sweep * parameter
            samples.append((round(center_x + radius * cos(angle)), round(center_y + radius * sin(angle))))
    return samples


def _interpolating_curve_samples(start, end, points, steps=32):
    if not points:
        return [start, end]
    if len(points) == 1:
        return _circular_arc_samples(start, points[0], end)

    path = [start, *points, end]
    samples = [path[0]]
    for segment in range(len(path) - 1):
        p0 = path[max(0, segment - 1)]
        p1 = path[segment]
        p2 = path[segment + 1]
        p3 = path[min(len(path) - 1, segment + 2)]
        for step in range(1, steps + 1):
            t = step / steps
            t2 = t * t
            t3 = t2 * t
            x = 0.5 * (
                2 * p1[0] + (-p0[0] + p2[0]) * t
                + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3
            )
            y = 0.5 * (
                2 * p1[1] + (-p0[1] + p2[1]) * t
                + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3
            )
            samples.append((round(x), round(y)))
    return samples

def _edge_screen_samples(graph, box, source, target):
    start = _real_to_screen_unclipped(box, graph.nodes[source]['position'])
    end = _real_to_screen_unclipped(box, graph.nodes[target]['position'])
    controls = [
        _real_to_screen_unclipped(box, point)
        for point in _edge_curve_points(graph, source, target)
    ]
    return _interpolating_curve_samples(start, end, controls)


class EdgeRef:
    """A logical edge, with direction included only for directed graphs."""
    def __init__(self, source, target, directed):
        self.source = source
        self.target = target
        self.directed = directed

    def __hash__(self):
        if self.directed:
            return hash((True, self.source, self.target))
        return hash((False, frozenset((self.source, self.target))))

    def __eq__(self, other):
        if not isinstance(other, EdgeRef) or self.directed != other.directed:
            return False
        if self.directed:
            return self.source == other.source and self.target == other.target
        return frozenset((self.source, self.target)) == frozenset((other.source, other.target))


class SelectionState:
    """Transient editor selection; never stored in graph attributes."""
    def __init__(self):
        self.nodes = set()
        self.edges = set()

    def clear(self):
        self.nodes.clear()
        self.edges.clear()

    def edge_ref(self, graph, source, target):
        return EdgeRef(source, target, graph.graph.get('graph_type') != 'graph')

    def has_edge(self, graph, source, target):
        return self.edge_ref(graph, source, target) in self.edges

    def select(self, graph, element, additive=False):
        if not additive:
            self.clear()
        kind, value = element
        selected = self.nodes if kind == 'node' else self.edges
        if kind == 'node':
            reference = value
        else:
            reference = self.edge_ref(graph, value[0], value[1])
        if additive and reference in selected:
            selected.remove(reference)
        else:
            selected.add(reference)

    def prune(self, graph):
        self.nodes.intersection_update(graph.nodes)
        directed = graph.graph.get('graph_type') != 'graph'
        remaining_edges = set()
        for edge in self.edges:
            source, target = edge.source, edge.target
            if source not in graph or target not in graph:
                continue
            if directed:
                candidates = ((source, target),) if edge.directed else ((source, target), (target, source))
                for start, end in candidates:
                    if graph.has_edge(start, end):
                        remaining_edges.add(EdgeRef(start, end, True))
            elif graph.has_edge(source, target) or graph.has_edge(target, source):
                remaining_edges.add(EdgeRef(source, target, False))
        self.edges = remaining_edges

    def single_node(self):
        if len(self.nodes) == 1 and not self.edges:
            return next(iter(self.nodes))
        return None


@dataclass
class GraphClipboard:
    nodes: tuple
    node_attributes: dict
    internal_edges: tuple
    boundary_edges: tuple


def copy_graph_selection(graph, selected_nodes=None):
    selected = set(graph.nodes) if selected_nodes is None else set(selected_nodes) & set(graph.nodes)
    selected_order = tuple(node for node in graph.nodes if node in selected)
    node_attributes = {
        node: copy.deepcopy(dict(graph.nodes[node]))
        for node in selected_order
    }
    internal_edges = []
    boundary_edges = []
    for source, target, attributes in graph.edges(data=True):
        source_selected = source in selected
        target_selected = target in selected
        if source_selected and target_selected:
            internal_edges.append((source, target, copy.deepcopy(dict(attributes))))
        elif source_selected or target_selected:
            boundary_edges.append((source, target, copy.deepcopy(dict(attributes))))
    return GraphClipboard(
        selected_order, node_attributes, tuple(internal_edges), tuple(boundary_edges)
    )


def paste_graph_selection(graph, clipboard, offset):
    new_graph = graph.copy()
    node_mapping = {}
    for old_node in clipboard.nodes:
        new_node = unused_label(new_graph)
        attributes = copy.deepcopy(clipboard.node_attributes[old_node])
        if 'position' in attributes:
            x, y = attributes['position']
            attributes['position'] = (x + offset[0], y + offset[1])
        new_graph.add_node(new_node, **attributes)
        node_mapping[old_node] = new_node

    for source, target, attributes in clipboard.internal_edges:
        new_graph.add_edge(node_mapping[source], node_mapping[target], **copy.deepcopy(attributes))

    for source, target, attributes in clipboard.boundary_edges:
        source_is_copied = source in node_mapping
        target_is_copied = target in node_mapping
        if source_is_copied == target_is_copied:
            continue
        new_source = node_mapping[source] if source_is_copied else source
        new_target = node_mapping[target] if target_is_copied else target
        if new_graph.has_node(new_source) and new_graph.has_node(new_target):
            new_graph.add_edge(new_source, new_target, **copy.deepcopy(attributes))

    return new_graph, set(node_mapping.values())


def cut_edges_to_rest(graph, selected_nodes):
    selected = set(selected_nodes)
    crossing_edges = [
        (source, target)
        for source, target in graph.edges
        if (source in selected) != (target in selected)
    ]
    graph.remove_edges_from(crossing_edges)
    return len(crossing_edges)


@dataclass
class EditorContext:
    graph: nx.DiGraph
    selection: SelectionState
    box: 'BOX'
    interaction: 'InteractionController'
    pointer_position: tuple = (0, 0)
    on_graph_replaced: Callable[[nx.DiGraph], None] | None = None

    def replace_graph(self, graph):
        self.graph = graph
        if self.on_graph_replaced is not None:
            self.on_graph_replaced(graph)


@dataclass
class Action:
    """A named editor command with a shortcut, handler, and availability rule."""
    id: str
    name: str | Callable[[EditorContext], str]
    shortcut: str | None
    handler: Callable[[EditorContext], Any]
    available: Callable[[EditorContext], bool]
    library: bool = False
    group: str = 'custom'
    checked: Callable[[EditorContext], bool] | None = None

    def is_available(self, context):
        return self.available(context)

    def display_name(self, context):
        return self.name(context) if callable(self.name) else self.name


def execute_action(action, context):
    if not action.is_available(context):
        return False
    result = action.handler(context)
    if isinstance(result, nx.Graph):
        context.replace_graph(result)
    return True


def _action_should_snap(action):
    return action.id not in ('undo', 'redo')


def GraphAction(function, shortcut, name=None, group='custom'):
    """Adapt ``function(graph)`` into an always-available editor action."""
    def invoke(context):
        result = function(context.graph)
        if result is not None:
            context.replace_graph(result)

    return Action(
        f'custom:{shortcut.lower()}',
        name or function.__name__,
        shortcut,
        invoke,
        lambda context: True,
        group=group,
    )


def VertexAction(function, shortcut, name=None, group='custom'):
    """Adapt ``function(graph, vertex)`` for exactly one selected vertex."""
    def invoke(context):
        result = function(context.graph, context.selection.single_node())
        if result is not None:
            context.replace_graph(result)

    return Action(
        f'custom:{shortcut.lower()}',
        name or function.__name__,
        shortcut,
        invoke,
        lambda context: context.selection.single_node() is not None,
        group=group,
    )


def VertexGroupAction(function, shortcut, name=None, group='custom'):
    """Adapt ``function(graph, vertices)`` when one or more vertices are selected."""
    def invoke(context):
        result = function(context.graph, set(context.selection.nodes))
        if result is not None:
            context.replace_graph(result)

    return Action(
        f'custom:{shortcut.lower()}',
        name or function.__name__,
        shortcut,
        invoke,
        lambda context: bool(context.selection.nodes),
        group=group,
    )


def EdgeAction(function, shortcut, name=None, group='custom'):
    """Adapt ``function(graph, edge)`` for exactly one selected edge."""
    def invoke(context):
        edge = next(iter(context.selection.edges))
        result = function(context.graph, (edge.source, edge.target))
        if result is not None:
            context.replace_graph(result)

    return Action(
        f'custom:{shortcut.lower()}',
        name or function.__name__,
        shortcut,
        invoke,
        lambda context: len(context.selection.edges) == 1 and not context.selection.nodes,
        group=group,
    )


def ContextAction(function, shortcut, available=lambda context: True, name=None, group='custom'):
    """Register a context-aware function with an optional availability predicate."""
    def invoke(context):
        result = function(context)
        if isinstance(result, nx.Graph):
            context.replace_graph(result)

    return Action(
        f'custom:{shortcut.lower()}',
        name or function.__name__,
        shortcut,
        invoke,
        available,
        group=group,
    )


def _normalize_shortcut(shortcut):
    return '+'.join(part.strip().casefold() for part in shortcut.split('+'))


def _shortcut_for_key(event, modifiers):
    primary_modifier = pygame.KMOD_CTRL | pygame.KMOD_GUI
    if modifiers & primary_modifier and event.key == pygame.K_z:
        shortcut = 'shift+ctrl+z' if modifiers & pygame.KMOD_SHIFT else 'ctrl+z'
    elif modifiers & primary_modifier and event.key in (pygame.K_c, pygame.K_v, pygame.K_s):
        shortcut = f'ctrl+{chr(event.key)}'
    elif event.key in (pygame.K_DELETE, pygame.K_BACKSPACE):
        shortcut = 'del'
    elif event.key == pygame.K_ESCAPE:
        shortcut = 'esc'
    elif event.key == pygame.K_SPACE:
        shortcut = 'space'
    elif 0 <= event.key < 128:
        shortcut = chr(event.key).casefold()
    else:
        return None
    return _normalize_shortcut(shortcut)


class InteractionController:
    """Own pointer hit-testing, selection, and in-progress mouse gestures."""
    def __init__(self):
        self.selection = SelectionState()
        self.begin_vertex = None
        self.creating_edge = False
        self.edge_sources = []
        self.gesture = None
        self.gesture_points = []
        self.gesture_additive = False
        self.gesture_moved = False
        self.gesture_started_selected = False
        self.gesture_button = None
        self.move_start_real = None
        self.move_start_positions = {}
        self.selected_curve_point = None

    def hit_node(self, graph, position, min_distance=20):
        return closest_vertex(graph, position, min_distance=min_distance)

    def hit_test(self, graph, box, screen_position, real_position):
        vertex = self.hit_node(graph, real_position)
        if vertex is not None:
            return ('node', vertex)

        closest_edge = None
        closest_distance = 8
        for source, target in graph.edges:
            samples = _edge_screen_samples(graph, box, source, target)
            for start, end in zip(samples, samples[1:]):
                distance = _point_segment_distance(screen_position, start, end)
                if distance <= closest_distance:
                    closest_distance = distance
                    closest_edge = ('edge', (source, target))
        return closest_edge

    def _hit_selected_curve_point(self, graph, box, screen_position):
        closest = None
        closest_distance = 10
        for edge in self.selection.edges:
            source, target = edge.source, edge.target
            if not graph.has_edge(source, target):
                continue
            for index, point in enumerate(_edge_curve_points(graph, source, target)):
                point_screen = _real_to_screen_unclipped(box, point)
                distance = dist(screen_position, point_screen)
                if distance <= closest_distance:
                    closest = (edge, index)
                    closest_distance = distance
        return closest

    def _start_selection_gesture(self, gesture, screen_position, additive, button=1):
        self.gesture = gesture
        self.gesture_points = [screen_position]
        self.gesture_additive = additive
        self.gesture_moved = False
        self.gesture_started_selected = bool(self.selection.nodes or self.selection.edges)
        self.gesture_button = button
        self.begin_vertex = None
        self.selected_curve_point = None

    def delete_selected_curve_point(self, graph):
        if self.selected_curve_point is None:
            return False
        edge, index = self.selected_curve_point
        if not graph.has_edge(edge.source, edge.target):
            self.selected_curve_point = None
            return False
        points = _edge_curve_points(graph, edge.source, edge.target)
        if index >= len(points):
            self.selected_curve_point = None
            return False
        points.pop(index)
        _set_edge_curve_points(graph, edge.source, edge.target, points)
        self.selected_curve_point = None
        self.gesture = None
        return True

    def delete_selection(self, graph):
        graph.remove_nodes_from(self.selection.nodes)
        for edge in tuple(self.selection.edges):
            source, target = edge.source, edge.target
            if graph.has_edge(source, target):
                graph.remove_edge(source, target)
            if not edge.directed and graph.has_edge(target, source):
                graph.remove_edge(target, source)
        self.selection.clear()
        self.selected_curve_point = None
        self.cancel_gesture()
        self.selection.prune(graph)

    def add_curve_point_to_selection(self, graph):
        selected_edges = [
            edge for edge in self.selection.edges
            if graph.has_edge(edge.source, edge.target)
        ]
        added_point = None
        for edge in selected_edges:
            source, target = edge.source, edge.target
            start = graph.nodes[source]['position']
            end = graph.nodes[target]['position']
            points = _edge_curve_points(graph, source, target)
            if points:
                samples = _interpolating_curve_samples(start, end, points)
                point = samples[len(samples) // 2]
                insertion_index = len(points) // 2
            else:
                dx = end[0] - start[0]
                dy = end[1] - start[1]
                length = (dx * dx + dy * dy) ** 0.5
                if length == 0:
                    point = start
                else:
                    point = (
                        (start[0] + end[0]) / 2 - dy / length * length * 0.2,
                        (start[1] + end[1]) / 2 + dx / length * length * 0.2,
                    )
                insertion_index = 0
            points.insert(insertion_index, tuple(point))
            _set_edge_curve_points(graph, source, target, points)
            if added_point is None:
                added_point = (edge, insertion_index)
        self.selected_curve_point = added_point if len(selected_edges) == 1 else None

    def cancel_gesture(self):
        self.gesture = None
        self.gesture_points = []
        self.gesture_moved = False
        self.gesture_started_selected = False
        self.gesture_button = None
        self.move_start_real = None
        self.move_start_positions = {}
        self.begin_vertex = None
        self.creating_edge = False
        self.edge_sources = []
        self.selected_curve_point = None
        pygame.mouse.set_cursor(pygame.cursors.arrow)

    def handle_mouse_down(self, event, graph, box, real_position, screen_position, modifiers, ctrl_activated):
        secondary_click = event.button in (2, 3)
        if secondary_click or (event.button == 1 and (ctrl_activated or modifiers & pygame.KMOD_CTRL)):
            element = self.hit_test(graph, box, screen_position, real_position)
            if element is not None and element[0] == 'node':
                vertex = element[1]
                if vertex in self.selection.nodes and len(self.selection.nodes) > 1:
                    self.edge_sources = [node for node in graph if node in self.selection.nodes]
                else:
                    self.edge_sources = [vertex]
                self.begin_vertex = vertex
                self.gesture = 'edge'
                self.gesture_button = event.button
                self.creating_edge = True
                pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_CROSSHAIR)
            else:
                self._start_selection_gesture(
                    'lasso', screen_position, bool(modifiers & pygame.KMOD_SHIFT), event.button
                )
            return

        if event.button == 1:
            curve_point = self._hit_selected_curve_point(graph, box, screen_position)
            if curve_point is not None:
                self.selected_curve_point = curve_point
                self.gesture = 'curve_point'
                self.gesture_button = event.button
                return

            element = self.hit_test(graph, box, screen_position, real_position)
            additive = bool(modifiers & pygame.KMOD_SHIFT)
            if additive and element is not None and element[0] == 'edge':
                source, target = element[1]
                edge_ref = self.selection.edge_ref(graph, source, target)
                if edge_ref in self.selection.edges:
                    points = _edge_curve_points(graph, source, target)
                    points.append(tuple(real_position))
                    _set_edge_curve_points(graph, source, target, points)
                    self.selected_curve_point = (edge_ref, len(points) - 1)
                    self.gesture = 'curve_point'
                    self.gesture_button = event.button
                    return
            if element is None:
                self._start_selection_gesture('rectangle', screen_position, additive, event.button)
            else:
                if element[0] == 'node':
                    self.selected_curve_point = None
                    vertex = element[1]
                    was_selected = vertex in self.selection.nodes
                    if additive:
                        self.selection.select(graph, element, additive=True)
                    elif not was_selected:
                        self.selection.select(graph, element)
                    if not additive and (not was_selected or vertex in self.selection.nodes):
                        self.begin_vertex = vertex
                        box.vertex_color = graph.nodes[vertex]['col']
                        self.gesture = 'move'
                        self.gesture_button = event.button
                        self.move_start_real = real_position
                        self.move_start_positions = {
                            node: graph.nodes[node]['position']
                            for node in self.selection.nodes
                        }
                else:
                    self.selection.select(graph, element, additive=additive)
                    self.selected_curve_point = None

    def _select_nodes_in_drag(self, graph, box, additive):
        if self.gesture == 'rectangle':
            start_x, start_y = self.gesture_points[0]
            end_x, end_y = self.gesture_points[-1]
            left, right = sorted((start_x, end_x))
            top, bottom = sorted((start_y, end_y))
            contains = lambda point: left <= point[0] <= right and top <= point[1] <= bottom
        else:
            polygon = self.gesture_points
            contains = lambda point: _point_in_polygon(point, polygon)

        if not additive:
            self.selection.clear()
        for node, data in graph.nodes(data=True):
            screen_position = box.real_to_screen(data['position'])
            if screen_position is not None and contains(screen_position):
                self.selection.nodes.add(node)

    def _finish_edge(self, graph, box, real_position, sources):
        end_vertex = self.hit_node(graph, real_position, min_distance=30)
        if end_vertex is not None and sources:
            if len(sources) == 1 and sources[0] == end_vertex:
                graph.remove_node(end_vertex)
            else:
                for source in sources:
                    if source != end_vertex:
                        flip_edge(graph, source, end_vertex, box.edge_color)
        self.creating_edge = False
        self.gesture = None
        self.begin_vertex = None
        self.edge_sources = []
        pygame.mouse.set_cursor(pygame.cursors.arrow)
        self.selection.prune(graph)

    def handle_mouse_up(self, event, graph, box, real_position, ctrl_activated, screen_position=None):
        if self.gesture_button is None or event.button != self.gesture_button:
            return False
        if self.gesture == 'edge':
            self._finish_edge(graph, box, real_position, self.edge_sources)
            return True
        if self.gesture == 'curve_point':
            self.gesture = None
            self.gesture_button = None
            return False
        if self.gesture in ('rectangle', 'lasso'):
            if screen_position is not None and self.gesture_points:
                self.gesture_moved = self.gesture_moved or dist(
                    self.gesture_points[0], screen_position
                ) >= 5
            if screen_position is not None:
                if not self.gesture_points or self.gesture_points[-1] != screen_position:
                    self.gesture_points.append(screen_position)
            if self.gesture_moved:
                self._select_nodes_in_drag(graph, box, self.gesture_additive)
            elif self.gesture_started_selected:
                if not self.gesture_additive:
                    self.selection.clear()
            elif self.gesture == 'rectangle':
                self.selection.clear()
                graph.add_node(unused_label(graph), position=real_position, col=box.vertex_color)
        self.gesture = None
        self.gesture_points = []
        self.gesture_moved = False
        self.gesture_started_selected = False
        self.gesture_button = None
        self.move_start_real = None
        self.move_start_positions = {}
        self.begin_vertex = None
        self.selection.prune(graph)
        return False

    def handle_mouse_motion(self, graph, box, real_position, screen_position, mouse_buttons):
        button_index = self.gesture_button - 1 if self.gesture_button is not None else -1
        button_pressed = 0 <= button_index < len(mouse_buttons) and mouse_buttons[button_index]
        if self.gesture in ('rectangle', 'lasso') and button_pressed:
            self.gesture_moved = self.gesture_moved or dist(
                self.gesture_points[0], screen_position
            ) >= 5
            if self.gesture == 'rectangle':
                self.gesture_points = [self.gesture_points[0], screen_position]
            elif dist(screen_position, self.gesture_points[-1]) >= 3:
                self.gesture_points.append(screen_position)
        elif self.gesture == 'move' and button_pressed and self.move_start_real is not None:
            delta_x = real_position[0] - self.move_start_real[0]
            delta_y = real_position[1] - self.move_start_real[1]
            for node, (start_x, start_y) in self.move_start_positions.items():
                graph.nodes[node]['position'] = (start_x + delta_x, start_y + delta_y)
            if self.begin_vertex is not None:
                graph.nodes[self.begin_vertex]['col'] = box.vertex_color
        elif self.gesture == 'curve_point' and button_pressed and self.selected_curve_point is not None:
            edge, index = self.selected_curve_point
            source, target = edge.source, edge.target
            points = _edge_curve_points(graph, source, target)
            if index < len(points):
                points[index] = tuple(real_position)
                _set_edge_curve_points(graph, source, target, points)

    def selection_preview(self):
        if self.gesture not in ('rectangle', 'lasso') or not self.gesture_points:
            return None
        return self.gesture, self.gesture_points

    def active_edge_sources(self):
        return tuple(self.edge_sources) if self.creating_edge else ()

    def cycle_selected_vertex_colors(self, graph, box):
        selected = [node for node in self.selection.nodes if node in graph]
        if not selected:
            return
        num_colors = graph.graph['num_vertex_colors']
        for node in selected:
            graph.nodes[node]['col'] = (graph.nodes[node]['col'] + 1) % num_colors
        if self.begin_vertex in selected:
            box.vertex_color = graph.nodes[self.begin_vertex]['col']
        elif len(selected) == 1:
            box.vertex_color = graph.nodes[selected[0]]['col']

    def cycle_selected_edge_colors(self, graph):
        num_colors = graph.graph['num_edge_colors']
        for edge in self.selection.edges:
            source, target = edge.source, edge.target
            if not graph.has_edge(source, target):
                continue
            color = (graph.edges[source, target]['col'] + 1) % num_colors
            graph.edges[source, target]['col'] = color
            if not edge.directed and graph.has_edge(target, source):
                graph.edges[target, source]['col'] = color

    def focus_vertex(self, graph, position):
        selected = self.selection.single_node()
        if selected is not None:
            return selected
        return self.hit_node(graph, position, min_distance=20)

def unused_label(graph):
    """Return an unused numeric string label for a new node."""
    i = 0
    while graph.has_node(str(i)):
        i += 1
    return str(i)

def convert_position(graph): 
    """Convert node 'position' tuples to separate x/y attributes for GraphML."""
    new_graph = nx.DiGraph()
    for node, data in graph.nodes(data=True):
        pos = data.get('position')
        if pos:
            new_data = dict(data)
            new_data['position_x'] = pos[0]
            new_data['position_y'] = pos[1]
            del new_data['position']
            new_graph.add_node(node, **new_data)
        else:
            new_graph.add_node(node, **data)
    for source, target, data in graph.edges(data=True):
        new_graph.add_edge(source, target, **data)
    return new_graph

def convert_from_file(graph_file, kwargs = {'graph_type' : 'graph','num_edge_colors' : 2,'num_vertex_colors' : 2} ):
    """Convert saved x/y node attributes back into a 'position' tuple."""
    
    try :
        graph = nx.read_graphml(graph_file)
    except :
        return empty_graph(**kwargs)

    new_graph = nx.DiGraph()
    for node, data in graph.nodes(data=True):
        pos_x = data.get('position_x')
        pos_y = data.get('position_y')
        if pos_x is not None and pos_y is not None:
            new_data = dict(data)
            new_data['position'] = (pos_x, pos_y)
            del new_data['position_x']
            del new_data['position_y']
            new_graph.add_node(node, **new_data)
        else:
            new_graph.add_node(node, **data)
        
        if not 'col' in data:
            new_graph.nodes[node]['col'] = 0
    for source, target, data in graph.edges(data=True):
        if not 'col' in data:
            data['col'] = 0
        new_graph.add_edge(source, target, **data)
    
    for key, value in kwargs.items():
            new_graph.graph[key] = value

    for source, target in list(new_graph.edges):
        if new_graph.edges[source, target].get('curve_points'):
            points = _edge_curve_points(new_graph, source, target)
            _set_edge_curve_points(new_graph, source, target, points)

    return new_graph


###### History / Undo helpers
def _serialize_graph(graph):
    """Serialize graph into node-link JSON-able structure."""
    return json_graph.node_link_data(graph)

def _deserialize_graph(data):
    """Deserialize node-link data back into a NetworkX graph."""
    return json_graph.node_link_graph(data)


def draw_arrow(screen, p1, p2,size=.5,arrow_tip=True,vertex_radius=15,color=(0,0,0)):
    """Draw an (optionally arrowed) edge between two screen points."""
    pygame.draw.line(screen, color, p1, p2, 2)

    # Calculate the angle and length of the line
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    angle = pygame.math.Vector2(dx, dy).angle_to(pygame.math.Vector2(1, 0))
    length = pygame.math.Vector2(dx, dy).length()

    if arrow_tip:
        # Define the points of the arrow triangle
        arrow_points = [
            (p2[0]-vertex_radius, p2[1]),
            (p2[0] - (vertex_radius+ size*20), p2[1] - 10*size),
            (p2[0] - (vertex_radius+ size*20), p2[1] + 10*size)
        ]

        # Rotate the arrow triangle around its tip (p2)

        arrow_points = [(pygame.math.Vector2(p) - p2).rotate(-angle) + p2 for p in arrow_points]

        # Draw the arrow triangle
        pygame.draw.polygon(screen, color, arrow_points)

def print_rules(actions = ()):
    """Print editor usage rules to stdout."""
    rules = """Left-click empty space to add a vertex
Left-click to select
Left-click a vertex to select/move it
Right-click a vertex and drag to add/remove edges
Right-click and release on the same vertex to delete it
Space-bar to erase everything 
[C] to change color
[Ctrl]+[C] to copy graph
[Ctrl]+[V] to paste graph
[T] to cut edges between selected vertices and the rest
[Ctrl]+[Z] to undo
[Shift]+[Ctrl]+[Z] to redo
Automatically saved when closed"""
    for action in actions:
        if action.shortcut:
            action_name = action.name if isinstance(action.name, str) else action.id
            rules += f"\n[{action.shortcut}] : {action_name}"
    
    #print(rules)
    return rules

class BOX:
    def __init__(self, screen):
        self.screen = screen
        self.visual_box = (0, 0, screen.get_width(), screen.get_height())  # Initialize visual box
        self.vertex_radius = 15  # Set the radius of the vertex
        self.font = pygame.font.Font(None, 30)  # Set the font for vertex labels
        self.toolbar_font = pygame.font.Font(None, 24)
        self.mouse_pos = (0,0) # arbitrary default position
        self.edge_color = 0
        self.vertex_color = 0
        self.color_list = colormap_1
        self.animations = [] # list of functions with end of life
        self.expanded_toolbar_groups = set()
        self.grid_mode = None
        self.grid_unit_scale = 2.0
        self.grid_base_unit = self.vertex_radius
        self.grid_origin = (screen.get_width() / 2, screen.get_height() / 2)
        self.radial_divisions = 5
        self._grid_surface_key = None
        self._grid_surface = None


    def real_to_screen(self, pos):
        # Convert the real position to the screen position
        x, y = pos
        x1, y1, x2, y2 = self.visual_box
        if x1 <= x <= x2 and y1 <= y <= y2:
            return int((x - x1) * self.screen.get_width() / (x2 - x1)), int((y - y1) * self.screen.get_height() / (y2 - y1))
        else:
            return None

    def screen_to_real(self, screen_pos):
        # Convert the screen position to the real position
        x, y = screen_pos
        x1, y1, x2, y2 = self.visual_box
        return (x1 + x * (x2 - x1) / self.screen.get_width(), y1 + y * (y2 - y1) / self.screen.get_height())

    def zoom(self, zoom_amount):
        (x1, y1, x2, y2) = self.visual_box
        (cx, cy) = self.mouse_pos

        # Compute the current width and height of the visual box
        width = x2 - x1
        height = y2 - y1

        # New width and height after zoom
        new_width = width * zoom_amount
        new_height = height * zoom_amount

        # Adjust the visual box such that the center remains stationary
        new_x1 = cx - (cx - x1) * zoom_amount
        new_y1 = cy - (cy - y1) * zoom_amount
        new_x2 = new_x1 + new_width
        new_y2 = new_y1 + new_height

        self.visual_box = (new_x1, new_y1, new_x2, new_y2)

        self.vertex_radius = 5+(self.vertex_radius-5)/zoom_amount
        self.font = pygame.font.Font(None, int(2*self.vertex_radius)) #2*vertex.v_radius

    def next_edge_color(self,graph):
        self.edge_color= (self.edge_color+1) % graph.graph['num_edge_colors']
    
    def reset_edge_color(self):
        self.edge_color = 0

    def next_vertex_color(self,graph):
        self.vertex_color= (self.vertex_color+1) % graph.graph['num_vertex_colors']

    @property
    def grid_unit(self):
        """Grid spacing in graph coordinates, independent of camera zoom."""
        return max(1, self.grid_base_unit * self.grid_unit_scale)

    def draw_grid(self):
        if self.grid_mode not in ('square', 'radial'):
            return
        width = self.screen.get_width()
        height = self.screen.get_height()
        unit = self.grid_unit
        x1, y1, x2, y2 = self.visual_box
        origin = _real_to_screen_unclipped(self, self.grid_origin)
        cache_key = (
            self.grid_mode, width, height, round(unit, 2),
            tuple(round(value, 6) for value in self.visual_box),
            tuple(round(value, 6) for value in self.grid_origin),
            self.radial_divisions if self.grid_mode == 'radial' else None,
        )
        if cache_key == self._grid_surface_key:
            self.screen.blit(self._grid_surface, (0, 0))
            return

        grid_surface = pygame.Surface((width, height), pygame.SRCALPHA)
        color = (224, 228, 232, 255)
        primary_color = (188, 196, 204, 255)
        if self.grid_mode == 'square':
            screen_unit_x = unit * width / (x2 - x1)
            screen_unit_y = unit * height / (y2 - y1)
            x_count = int(width / screen_unit_x) + 2
            y_count = int(height / screen_unit_y) + 2
            for x_index in range(-x_count, x_count + 1):
                x = round(origin[0] + x_index * screen_unit_x)
                if 0 <= x < width:
                    pygame.draw.line(grid_surface, color, (x, 0), (x, height - 1), 1)
            for y_index in range(-y_count, y_count + 1):
                y = round(origin[1] + y_index * screen_unit_y)
                if 0 <= y < height:
                    pygame.draw.line(grid_surface, color, (0, y), (width - 1, y), 1)
        else:
            max_radius = max(
                dist(self.grid_origin, self.screen_to_real(corner))
                for corner in ((0, 0), (width, 0), (0, height), (width, height))
            )
            max_ring = int(max_radius / unit) + 1
            pygame.draw.circle(
                grid_surface, primary_color, (round(origin[0]), round(origin[1])), 2
            )
            for index in range(self.radial_divisions):
                angle = RADIAL_GRID_OFFSET + 2 * pi * index / self.radial_divisions
                endpoint = _real_to_screen_unclipped(
                    self,
                    (
                        self.grid_origin[0] + cos(angle) * max_radius,
                        self.grid_origin[1] + sin(angle) * max_radius,
                    ),
                )
                pygame.draw.line(
                    grid_surface, primary_color,
                    (round(origin[0]), round(origin[1])), endpoint, 2
                )

            previous_divisions = self.radial_divisions
            for ring in range(1, max_ring + 1):
                divisions = _radial_grid_divisions(ring, self.radial_divisions)
                if divisions == 0:
                    continue
                radius = ring * unit
                left_top = _real_to_screen_unclipped(
                    self, (self.grid_origin[0] - radius, self.grid_origin[1] - radius)
                )
                right_bottom = _real_to_screen_unclipped(
                    self, (self.grid_origin[0] + radius, self.grid_origin[1] + radius)
                )
                pygame.draw.ellipse(
                    grid_surface,
                    color,
                    pygame.Rect(
                        left_top[0], left_top[1],
                        right_bottom[0] - left_top[0], right_bottom[1] - left_top[1],
                    ),
                    1,
                )
                if divisions > previous_divisions:
                    new_spoke_factor = divisions // previous_divisions
                    for index in range(divisions):
                        if index % new_spoke_factor == 0:
                            continue
                        angle = RADIAL_GRID_OFFSET + 2 * pi * index / divisions
                        start = _real_to_screen_unclipped(
                            self,
                            (
                                self.grid_origin[0] + cos(angle) * ring * unit,
                                self.grid_origin[1] + sin(angle) * ring * unit,
                            ),
                        )
                        end = _real_to_screen_unclipped(
                            self,
                            (
                                self.grid_origin[0] + cos(angle) * max_radius,
                                self.grid_origin[1] + sin(angle) * max_radius,
                            ),
                        )
                        pygame.draw.line(grid_surface, color, start, end, 1)
                    previous_divisions = divisions
        self._grid_surface_key = cache_key
        self._grid_surface = grid_surface
        self.screen.blit(grid_surface, (0, 0))

    def draw_graph(self, graph, selection=None, edge_start=None, edge_color=None, selection_preview=None, edge_starts=None, selected_curve_point=None):
        nodes = graph.nodes()
        arrow_type = graph.graph['graph_type']=='digraph'
        self.draw_grid()
        for v1, v2 in graph.edges:
            p1 = self.real_to_screen(nodes[v1]["position"])
            p2 = self.real_to_screen(nodes[v2]["position"])
            c = self.color_list(graph.edges[v1,v2]['col'])
            control_points = _edge_curve_points(graph, v1, v2)
            if control_points:
                samples = _edge_screen_samples(graph, self, v1, v2)
                if selection is not None and selection.has_edge(graph, v1, v2):
                    pygame.draw.lines(self.screen, (0, 180, 90), False, samples, 7)
                pygame.draw.lines(self.screen, c, False, samples, 2)
                if arrow_type:
                    draw_arrow(
                        self.screen, samples[-2], samples[-1], arrow_tip=True,
                        vertex_radius=self.vertex_radius, color=c
                    )
            elif p1 and p2:
                if selection is not None and selection.has_edge(graph, v1, v2):
                    pygame.draw.line(self.screen, (0, 180, 90), p1, p2, 7)
                draw_arrow(self.screen, p1, p2,arrow_tip=arrow_type,vertex_radius=self.vertex_radius,color=c)
        preview_sources = tuple(edge_starts) if edge_starts is not None else (() if edge_start is None else (edge_start,))
        for source in preview_sources:
            p1 = self.real_to_screen(nodes[source]["position"])
            p2 = self.real_to_screen(self.mouse_pos)
            c = self.color_list(self.edge_color if edge_color is None else edge_color)
            if p1 is not None and p2 is not None:
                draw_arrow(self.screen, p1, p2,arrow_tip=arrow_type,vertex_radius=0,color=c)

        for v in nodes:
            p = self.real_to_screen(nodes[v]["position"])
            c = self.color_list(nodes[v]["col"])
            if p:
                if selection is not None and v in selection.nodes:
                    pygame.draw.circle(self.screen, (0, 180, 90), p, self.vertex_radius + 4, 3)
                pygame.draw.circle(self.screen, c, p, self.vertex_radius)

                # render the vertex name
                text = self.font.render(v, True, (255, 255, 255))
                text_rect = text.get_rect(center=p)

                # blit the text on the screen
                self.screen.blit(text, text_rect)

        if selection is not None:
            for edge in selection.edges:
                if not graph.has_edge(edge.source, edge.target):
                    continue
                for index, point in enumerate(_edge_curve_points(graph, edge.source, edge.target)):
                    point_screen = _real_to_screen_unclipped(self, point)
                    active = selected_curve_point == (edge, index)
                    color = (245, 130, 30) if active else (20, 140, 150)
                    pygame.draw.circle(self.screen, color, point_screen, 7)
                    pygame.draw.circle(self.screen, (255, 255, 255), point_screen, 3)

        if selection_preview is not None:
            gesture, points = selection_preview
            if gesture == 'rectangle' and len(points) >= 2:
                left, right = sorted((points[0][0], points[-1][0]))
                top, bottom = sorted((points[0][1], points[-1][1]))
                rect = pygame.Rect(left, top, right - left, bottom - top)
                pygame.draw.rect(self.screen, (0, 150, 130), rect, 2)
            elif gesture == 'lasso' and len(points) >= 2:
                pygame.draw.lines(self.screen, (0, 150, 130), False, points, 2)

    def _toolbar_items(self, actions, context):
        items = []
        group_order = ['basic', 'custom']
        group_order.extend(
            action.group for action in actions if action.group not in group_order
        )
        x_margin = 12
        row_height = 32
        right_margin = self.screen.get_width() - x_margin
        header_x = x_margin
        header_y = 12

        for group in group_order:
            is_expanded = group in self.expanded_toolbar_groups
            title = {
                'basic': 'Basic functions',
                'custom': 'Custom functions',
            }.get(group, group.replace('_', ' ').title())
            prefix = '- ' if is_expanded else '+ '
            header_width = max(
                self.toolbar_font.size('+ ' + title)[0],
                self.toolbar_font.size('- ' + title)[0],
            ) + 24
            if header_x > x_margin and header_x + header_width > right_margin:
                header_x = x_margin
                header_y += row_height + 5
            header = pygame.Rect(header_x, header_y, header_width, row_height)
            header_color = (30, 85, 91) if group == 'basic' else (57, 70, 85)
            items.append(('group', group, prefix + title, header_color, header))
            header_x += header_width + 8

        y = header_y + row_height + 8
        for group in group_order:
            if group not in self.expanded_toolbar_groups:
                continue
            grouped_actions = [
                (index, action) for index, action in enumerate(actions)
                if action.group == group and action.is_available(context)
            ]
            def action_order(item):
                index, action = item
                shortcut = _normalize_shortcut(action.shortcut or '')
                special = (
                    action.id == 'delete'
                    or 'ctrl' in shortcut.split('+')
                    or shortcut in ('esc', 'space')
                )
                return (not special, index)

            x = x_margin
            for _, action in sorted(grouped_actions, key=action_order):
                toggle_prefix = ''
                if action.checked is not None:
                    toggle_prefix = '[x] ' if action.checked(context) else '[ ] '
                action_name = action.display_name(context)
                action_label = f'{action.shortcut}  {action_name}' if action.shortcut else action_name
                label = toggle_prefix + action_label
                width = self.toolbar_font.size(label)[0] + 24
                if x > x_margin and x + width > right_margin:
                    x = x_margin
                    y += row_height + 5
                rect = pygame.Rect(x, y, width, row_height)
                if action.id == 'delete':
                    color = (177, 58, 48)
                elif action.checked is not None and action.checked(context):
                    color = (35, 133, 92)
                elif action.library:
                    color = (30, 112, 120)
                else:
                    color = (75, 88, 105)
                items.append(('action', action, label, color, rect))
                x += width + 8
            if grouped_actions:
                y += row_height + 5
        return items

    def toggle_toolbar_group(self, group):
        if group in self.expanded_toolbar_groups:
            self.expanded_toolbar_groups.remove(group)
        else:
            self.expanded_toolbar_groups.add(group)

    def toolbar_item_at(self, actions, context, screen_position):
        for kind, value, _, _, rect in self._toolbar_items(actions, context):
            if rect.collidepoint(screen_position):
                return kind, value
        return None

    def draw_toolbar(self, actions, context):
        for _, _, label, color, rect in self._toolbar_items(actions, context):
            pygame.draw.rect(self.screen, color, rect, border_radius=4)
            text = self.toolbar_font.render(label, True, (255, 255, 255))
            self.screen.blit(text, text.get_rect(center=rect.center))
    
    def draw_animations(self):
        remaining_animations = []
        for (anim_duration,anim_func) in self.animations:
            if ti.time() < anim_duration:
                remaining_animations.append((anim_duration,anim_func))
                anim_func()
        self.animations = remaining_animations

    def write_instant(self,text,screen_pos):
        # render the text
        cx,cy = center = screen_pos
        for line in text.split("\n"):
            text_render = self.font.render(line, True, (0, 0, 0))
            text_rect = text_render.get_rect(center=center)
            self.screen.blit(text_render, text_rect)
            cy +=1.2*text_rect.height
            center = (cx, cy)
    
    def write(self,text,duration,screen_relative_position=(.5,.5)):
        # render the text
        screen_pos = screen_relative_position[0]*self.screen.get_width(), screen_relative_position[1]*self.screen.get_height()
        self.animations.append(( ti.time() + duration, lambda : self.write_instant(text,screen_pos)))

def empty_graph(**kwargs):
    """Create an empty directed graph and apply provided graph attributes."""
    graph = nx.DiGraph()
    # default values for important parameters
    for key, value in kwargs.items():
        graph.graph[key] = value
    return graph

def is_event_left(event,CTRL_activated):
    """Return True if the event should be treated as a left-click."""
    return event.button == 1 and not CTRL_activated

def is_event_right(event,CTRL_activated):
    """Return True if the event should be treated as a right-click."""
    return event.button == 3 or CTRL_activated

####################################################################################

####################################################################################

####################################################################################

def main(actions=(), graph_file=None, **kwargs):
    """Run the interactive editor.

    Parameters
    ----------
    actions:
        Additional editor actions.
    graph_file:
        GraphML file to open and update.  When omitted, ``graph.graphml`` in
        the current working directory is used.  This keeps user data separate
        from the installed library.
    """
    custom_actions = tuple(actions)
    if any(not isinstance(action, Action) for action in custom_actions):
        raise TypeError("actions must contain GraphAction, VertexAction, EdgeAction, VertexGroupAction, or Action values")

    rules = print_rules(custom_actions)

    #default graph parameters for important ones
    kwargs = {**{'graph_type' : 'graph','num_edge_colors' : 2,'num_vertex_colors' : 2},**kwargs}

    pygame.init()
    infoObject = pygame.display.Info()
    screen = pygame.display.set_mode((0.8 * infoObject.current_w, 0.9 * infoObject.current_h), pygame.RESIZABLE)
    pygame.display.set_caption("Graph Editor")
    running = True
    CTRL_activated = False

    graph_path = Path(graph_file) if graph_file is not None else Path.cwd() / DEFAULT_GRAPH_FILE
    graph = convert_from_file(graph_path, kwargs)

    box = BOX(screen)
    interaction = InteractionController()
    graph_clipboard = None
    last_canvas_pos = box.screen_to_real((screen.get_width() // 2, screen.get_height() // 2))
    box.write(rules,5,(0.8,0.2))


    # History stack for undo support
    history = []
    history_pos = -1
    MAX_HISTORY = 200

    def push_serialized_state(data):
        nonlocal history, history_pos
        if history_pos < len(history) - 1:
            history = history[:history_pos+1]
        history.append(data)
        history_pos = len(history) - 1
        if len(history) > MAX_HISTORY:
            history.pop(0)
            history_pos -= 1
    
    def save_state():
        nonlocal history, history_pos, graph
        push_serialized_state(_serialize_graph(graph))
        print(f"saved graph with {graph.number_of_nodes()} nodes")

    def save_state_if_changed():
        """Push pre_data only if graph changed since pre_data was taken."""
        nonlocal history, history_pos, graph
        pre_snap = history[history_pos] if history_pos >= 0 else None
        post_snap = _serialize_graph(graph)
        if pre_snap != post_snap:
            push_serialized_state(post_snap)

    def redo():
        nonlocal history, history_pos, graph
        if history_pos >= len(history) - 1:
            history_pos = len(history) - 1
        else:
            history_pos += 1
        graph = _deserialize_graph(history[history_pos])
        for key, value in kwargs.items():
            graph.graph[key] = value
        interaction.cancel_gesture()
        interaction.selection.prune(graph)
        box.reset_edge_color()

    def undo():
        nonlocal history, history_pos, graph
        if history_pos <= 0:
            return
        history_pos -= 1
        graph = _deserialize_graph(history[history_pos])
        # ensure graph meta params remain from kwargs
        for key, value in kwargs.items():
            graph.graph[key] = value
        interaction.cancel_gesture()
        interaction.selection.prune(graph)
        box.reset_edge_color()

    def undo_action(context):
        undo()
        context.replace_graph(graph)

    def redo_action(context):
        redo()
        context.replace_graph(graph)

    def make_context(pointer_position):
        def replace_graph(new_graph):
            nonlocal graph
            graph = new_graph

        return EditorContext(
            graph, interaction.selection, box, interaction, pointer_position, replace_graph
        )

    def change_color(context):
        if interaction.creating_edge:
            box.next_edge_color(graph)
        elif context.selection.edges or context.selection.nodes:
            interaction.cycle_selected_edge_colors(graph)
            interaction.cycle_selected_vertex_colors(graph, box)
        elif interaction.begin_vertex is not None:
            box.next_vertex_color(graph)
        else:
            vertex = interaction.focus_vertex(graph, context.pointer_position)
            if vertex is not None:
                box.vertex_color = graph.nodes[vertex]['col']
                box.next_vertex_color(graph)
                graph.nodes[vertex]['col'] = box.vertex_color

    def delete_selection(context):
        if not interaction.delete_selected_curve_point(graph):
            interaction.delete_selection(graph)

    def deselect(context):
        interaction.selection.clear()
        interaction.cancel_gesture()

    def reset_graph(context):
        interaction.selection.clear()
        interaction.cancel_gesture()
        context.replace_graph(empty_graph(**kwargs))

    def copy_graph_action(context):
        nonlocal graph_clipboard
        selected_nodes = context.selection.nodes or None
        graph_clipboard = copy_graph_selection(graph, selected_nodes)

    def paste_graph(context):
        if graph_clipboard is None or not graph_clipboard.nodes:
            return
        x1, y1, x2, y2 = box.visual_box
        offset = (
            box.vertex_radius * (x2 - x1) / box.screen.get_width(),
            -box.vertex_radius * (y2 - y1) / box.screen.get_height(),
        )
        pasted_graph, pasted_nodes = paste_graph_selection(graph, graph_clipboard, offset)
        context.selection.clear()
        context.selection.nodes.update(pasted_nodes)
        interaction.cancel_gesture()
        context.replace_graph(pasted_graph)

    def cut_selected_edges(context):
        cut_edges_to_rest(graph, context.selection.nodes)

    def has_cuttable_edges(context):
        selected_nodes = context.selection.nodes
        return bool(selected_nodes) and any(
            (source in selected_nodes) != (target in selected_nodes)
            for source, target in graph.edges
        )

    def toggle_grid(mode):
        toggle_grid_mode(box, interaction, graph, mode)

    def decrease_grid_unit(context):
        box.grid_unit_scale = max(0.25, box.grid_unit_scale / 1.3)

    def increase_grid_unit(context):
        box.grid_unit_scale = min(10.0, box.grid_unit_scale * 1.3)

    def decrease_radial_divisions(context):
        box.radial_divisions = max(2, box.radial_divisions - 1)

    def increase_radial_divisions(context):
        box.radial_divisions += 1

    def save_tikz(context):
        from tikz_export import save_tikz_dialog

        tikz_path = save_tikz_dialog(context.graph, graph_path.with_suffix('.tex'))
        if tikz_path is not None:
            print(f"TikZ saved in {tikz_path}")

    built_in_actions = [
        Action('color', 'Color', 'C', change_color, lambda context: (
            bool(context.selection.nodes or context.selection.edges)
            or interaction.creating_edge
            or interaction.focus_vertex(graph, context.pointer_position) is not None
        )),
        Action('undo', 'Undo', 'Ctrl+Z', undo_action, lambda context: history_pos > 0),
        Action('redo', 'Redo', 'Shift+Ctrl+Z', redo_action, lambda context: history_pos < len(history) - 1),
        Action('escape', 'Deselect', 'Esc', deselect, lambda context: bool(
            context.selection.nodes or context.selection.edges
            or interaction.gesture or interaction.selected_curve_point
        )),
        Action('reset', 'Reset', 'Space', reset_graph, lambda context: bool(graph.number_of_nodes() or graph.number_of_edges())),
        Action('copy', 'Copy', 'Ctrl+C', copy_graph_action, lambda context: bool(graph.number_of_nodes())),
        Action('paste', 'Paste', 'Ctrl+V', paste_graph, lambda context: graph_clipboard is not None and bool(graph_clipboard.nodes)),
        Action('save_tikz', 'Save TikZ', 'Ctrl+S', save_tikz, lambda context: bool(graph.number_of_nodes())),
        Action('delete', 'Delete', 'Del', delete_selection, lambda context: bool(
            context.selection.nodes or context.selection.edges or interaction.selected_curve_point
        )),
        Action('cut', 'Cut edges to rest', 'T', cut_selected_edges, has_cuttable_edges),
        Action('add_curve_point', 'Add curve point', None, lambda context: interaction.add_curve_point_to_selection(graph), lambda context: bool(context.selection.edges)),
        Action(
            'square_grid', 'Square grid', None,
            lambda context: toggle_grid('square'), lambda context: True,
            library=True, group='grid', checked=lambda context: box.grid_mode == 'square',
        ),
        Action(
            'radial_grid', 'Radial grid', None,
            lambda context: toggle_grid('radial'), lambda context: True,
            library=True, group='grid', checked=lambda context: box.grid_mode == 'radial',
        ),
        Action(
            'grid_unit_increase', 'Grid unit ++', None,
            increase_grid_unit,
            lambda context: box.grid_mode is not None and box.grid_unit_scale < 10.0,
            library=True, group='grid',
        ),
        Action(
            'grid_unit_decrease', 'Grid unit --', None,
            decrease_grid_unit,
            lambda context: box.grid_mode is not None and box.grid_unit_scale > 0.25,
            library=True, group='grid',
        ),
        Action(
            'radial_divisions_increase',
            'Radial ++', None,
            increase_radial_divisions,
            lambda context: box.grid_mode == 'radial',
            library=True, group='grid',
        ),
        Action(
            'radial_divisions_decrease', 'Radial --', None,
            decrease_radial_divisions,
            lambda context: box.grid_mode == 'radial' and box.radial_divisions > 2,
            library=True, group='grid',
        ),
    ]
    for action in built_in_actions:
        action.library = True
        if action.group == 'custom':
            action.group = 'basic'
    all_actions = built_in_actions + list(custom_actions)
    actions_by_shortcut = {}
    for action in all_actions:
        if action.shortcut is None:
            continue
        shortcut = _normalize_shortcut(action.shortcut)
        if shortcut in actions_by_shortcut:
            raise ValueError(f"Shortcut '{action.shortcut}' is assigned to more than one action")
        actions_by_shortcut[shortcut] = action

    def run_action(action, pointer_position):
        nonlocal graph
        context = make_context(pointer_position)
        if not execute_action(action, context):
            return False
        graph = context.graph
        interaction.selection.prune(graph)
        return True

    def action_for_key(event, modifiers):
        shortcut = _shortcut_for_key(event, modifiers)
        return actions_by_shortcut.get(shortcut) if shortcut is not None else None

    # initial state
    save_state()

    

    while running:
        events = pygame.event.get()
        for event in events:
            screen_pos = getattr(event, 'pos', pygame.mouse.get_pos())
            box.mouse_pos = pos = box.screen_to_real(screen_pos)
            mods = pygame.key.get_mods()
            context = make_context(last_canvas_pos)
            toolbar_item = box.toolbar_item_at(all_actions, context, screen_pos)
            if event.type in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP) and toolbar_item is None:
                last_canvas_pos = pos
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1 and toolbar_item is not None:
                    item_kind, item_value = toolbar_item
                    if item_kind == 'group':
                        box.toggle_toolbar_group(item_value)
                    else:
                        run_action(item_value, last_canvas_pos)
                        if _action_should_snap(item_value):
                            snap_unselected_vertices(graph, interaction.selection, box, box.grid_mode)
                        save_state_if_changed()
                else:
                    if mods & pygame.KMOD_CTRL:
                        CTRL_activated = True
                    interaction.handle_mouse_down(
                        event, graph, box, pos, screen_pos, mods, CTRL_activated
                    )
            elif event.type == pygame.MOUSEBUTTONUP:
                interaction.handle_mouse_up(
                    event, graph, box, pos, CTRL_activated, screen_pos
                )
                CTRL_activated = False
                snap_unselected_vertices(graph, interaction.selection, box, box.grid_mode)
                save_state_if_changed()
            elif event.type == pygame.KEYDOWN:
                action = action_for_key(event, mods)
                if action is not None:
                    run_action(action, last_canvas_pos)
                    if _action_should_snap(action):
                        snap_unselected_vertices(graph, interaction.selection, box, box.grid_mode)
                    save_state_if_changed()
                   
            # Mouse wheel scroll event handling
            elif event.type == pygame.MOUSEWHEEL:
                zoom_amount = 1.1 if event.y < 0 else 0.9  # Scroll up zooms in, scroll down zooms out
                box.zoom( zoom_amount)
                if snap_unselected_vertices(graph, interaction.selection, box, box.grid_mode):
                    save_state_if_changed()
            elif event.type == pygame.MOUSEMOTION:
                interaction.handle_mouse_motion(
                    graph, box, pos, screen_pos, getattr(event, 'buttons', pygame.mouse.get_pressed())
                )

        screen.fill((255, 255, 255))
        edge_start = interaction.begin_vertex if interaction.creating_edge else None
        box.draw_graph(
            graph,
            interaction.selection,
            None,
            box.edge_color,
            interaction.selection_preview(),
            edge_starts=interaction.active_edge_sources(),
            selected_curve_point=interaction.selected_curve_point,
        )
        box.draw_toolbar(all_actions, make_context(last_canvas_pos))
        box.draw_animations()
        pygame.display.update()
        ti.sleep(.01)

    if not running:
        graph_path.parent.mkdir(parents=True, exist_ok=True)
        nx.write_graphml(convert_position(graph), graph_path)
        print(f"Graph saved in {graph_path}")
        pygame.quit()
