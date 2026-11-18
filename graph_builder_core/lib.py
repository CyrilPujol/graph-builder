"""Graph data and extension API shared by the Qt editor and custom scripts.

No GUI toolkit is imported here. Simple documents use NetworkX ``DiGraph``
and multiedge documents use ``MultiDiGraph``. An undirected edge is stored as
two matching arcs for compatibility with old GraphML files.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from math import atan2, ceil, cos, floor, hypot, pi, sin, sqrt
from pathlib import Path
from typing import Any, Callable

import networkx as nx
from networkx.readwrite import json_graph

from .palette import colormap_1
from .edges import edge_data, edge_records, visible_edges, add_edge, has_edge, remove_edge


DEFAULT_GRAPH_OPTIONS = {
    'graph_type': 'graph', 'num_edge_colors': 2,
    'num_vertex_colors': 4, 'show_labels': True,
    'loops': False, 'multiedges': False,
}


def empty_graph(**options):
    graph = nx.MultiDiGraph() if options.get('multiedges') else nx.DiGraph()
    graph.graph.update(DEFAULT_GRAPH_OPTIONS)
    graph.graph.update(options)
    return graph


def unused_label(graph):
    """Choose a new stable internal ID; visible labels may be duplicated."""
    index = 0
    while str(index) in graph:
        index += 1
    return str(index)


def vertex_label(graph, node):
    return str(graph.nodes[node].get('label', node))


def edge_label(graph, source, target, key=None):
    return str(edge_data(graph, source, target, key).get('label', ''))


def labels_visible(graph):
    return graph.graph.get('show_labels', graph.graph.get('show_vertex_labels', True))


def logical_edges(graph):
    """Yield each visible edge once, including every directed arc."""
    for source, target, _, _ in visible_edges(graph):
        yield source, target


def set_edge_label(graph, source, target, label, key=None):
    edge_data(graph, source, target, key)['label'] = label
    if graph.graph.get('graph_type') == 'graph' and has_edge(graph, target, source, key):
        edge_data(graph, target, source, key)['label'] = label


def flip_edge(graph, source, target, edge_color=0):
    """Toggle a simple edge, or add a clear path in a multigraph."""
    if source == target and not graph.graph.get('loops', False):
        return
    if graph.is_multigraph():
        from .edge_layout import free_loop_controls, parallel_controls
        controls = []
        if all(node in graph and 'position' in graph.nodes[node]
               for node in (source, target)):
            controls = (free_loop_controls(graph, source) if source == target else
                        parallel_controls(graph, source, target))
        # Use a free key in both directions so paired undirected arcs agree.
        key = 0
        while has_edge(graph, source, target, key) or has_edge(graph, target, source, key):
            key += 1
        add_edge(graph, source, target, {'col': edge_color}, key)
        if graph.graph.get('graph_type') == 'graph' and source != target:
            add_edge(graph, target, source, {'col': edge_color}, key)
        if controls:
            _set_edge_curve_points(graph, source, target, controls, key)
        return key
    controls = None
    if (source == target and not graph.has_edge(source, target)
            and source in graph and 'position' in graph.nodes[source]):
        from .edge_layout import free_loop_controls
        controls = free_loop_controls(graph, source)
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
    if controls and graph.has_edge(source, target):
        _set_edge_curve_points(graph, source, target, controls)


def full_join(graph, first, second, edge_color=0):
    """Add every allowed edge from ``first`` to ``second`` once.

    Existing simple edges are left alone. In a multigraph each distinct pair
    gains one edge, with the same automatic curve placement as manual creation.
    """
    sources = set(first) & set(graph)
    targets = set(second) & set(graph)
    directed = graph.graph.get('graph_type') != 'graph'
    loops = bool(graph.graph.get('loops', False))
    seen = set()
    added = 0
    for source in sorted(sources, key=str):
        for target in sorted(targets, key=str):
            if source == target and not loops:
                continue
            identity = (source, target) if directed else frozenset((source, target))
            if identity in seen:
                continue
            seen.add(identity)
            if not graph.is_multigraph() and (
                    graph.has_edge(source, target) or
                    (not directed and graph.has_edge(target, source))):
                continue
            flip_edge(graph, source, target, edge_color)
            added += 1
    return added


def _loop_controls(graph, node, index=1):
    from .edge_layout import loop_controls
    return loop_controls(graph, node, index - 1)


def set_directed(graph, directed):
    if graph.is_multigraph():
        if not directed:
            def id_order(node):
                identifier = str(node)
                return (0, int(identifier), identifier) if identifier.isdecimal() else (1, identifier)

            identities = {(frozenset((u, v)), key)
                          for u, v, key, _ in edge_records(graph)}
            retained = []
            for pair, key in sorted(identities, key=lambda entry: (
                    tuple(sorted(map(id_order, entry[0]))), str(entry[1]))):
                if len(pair) == 1:
                    source = target = next(iter(pair))
                else:
                    first, second = sorted(pair, key=id_order)
                    source, target = ((first, second) if has_edge(graph, first, second, key)
                                      else (second, first))
                retained.append((source, target, key,
                                 copy.deepcopy(edge_data(graph, source, target, key)),
                                 _edge_curve_points(graph, source, target, key)))
            graph.clear_edges()
            graph.graph['graph_type'] = 'graph'
            for source, target, key, data, points in retained:
                add_edge(graph, source, target, data, key)
                if source != target:
                    add_edge(graph, target, source, data, key)
                if points:
                    _set_edge_curve_points(graph, source, target, points, key)
        graph.graph['graph_type'] = 'digraph' if directed else 'graph'
        return
    if not directed:
        # A directed pair can carry two different looks or labels. Keep the
        # arc from the lower internal ID when both exist, then mirror it.
        # If only one direction exists, that existing arc is the winner.
        def id_order(node):
            identifier = str(node)
            return (0, int(identifier), identifier) if identifier.isdecimal() else (1, identifier)

        pairs = {frozenset((source, target)) for source, target in graph.edges}
        retained = []
        for pair in sorted(pairs, key=lambda pair: tuple(sorted(map(id_order, pair)))):
            if len(pair) != 2:
                continue
            first, second = sorted(pair, key=id_order)
            source, target = ((first, second) if graph.has_edge(first, second)
                              else (second, first))
            retained.append((source, target, copy.deepcopy(graph.edges[source, target]),
                             _edge_curve_points(graph, source, target)))
        for source, target, data, _ in retained:
            for start, end in ((source, target), (target, source)):
                if not graph.has_edge(start, end):
                    graph.add_edge(start, end)
                graph.edges[start, end].clear()
                graph.edges[start, end].update(copy.deepcopy(data))
    graph.graph['graph_type'] = 'digraph' if directed else 'graph'
    if not directed:
        for source, target, _, points in retained:
            if points:
                _set_edge_curve_points(graph, source, target, points)


def _edge_curve_points(graph, source, target, key=None):
    """Read absolute curve points from current or older GraphML attributes."""
    if not graph.has_edge(source, target):
        return []
    data = edge_data(graph, source, target, key)
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


def _set_edge_curve_points(graph, source, target, points, key=None):
    if not graph.has_edge(source, target):
        return
    start = graph.nodes[source]['position']
    end = graph.nodes[target]['position']
    midpoint = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
    offsets = [(x - midpoint[0], y - midpoint[1]) for x, y in points]
    edge_data(graph, source, target, key)['curve_offsets'] = json.dumps(offsets)
    edge_data(graph, source, target, key).pop('curve_points', None)
    if source != target and graph.graph.get('graph_type') == 'graph' and has_edge(graph, target, source, key):
        edge_data(graph, target, source, key)['curve_offsets'] = json.dumps(list(reversed(offsets)))
        edge_data(graph, target, source, key).pop('curve_points', None)


def contract(graph, vertices, new_vertex=None, representative=None):
    """Contract selected vertices (or selected-edge endpoints) into one vertex."""
    vertices = set(vertices) & set(graph.nodes)
    if len(vertices) < 2:
        return graph
    if new_vertex is None:
        new_vertex = unused_label(graph)
    elif new_vertex in graph:
        raise ValueError(f'Contracted vertex ID already exists: {new_vertex!r}')
    positions = [graph.nodes[vertex]['position'] for vertex in vertices]
    position = (sum(x for x, _ in positions) / len(positions),
                sum(y for _, y in positions) / len(positions))
    new_graph = graph.__class__()
    new_graph.graph.update(copy.deepcopy(graph.graph))
    for vertex, attributes in graph.nodes(data=True):
        if vertex not in vertices:
            new_graph.add_node(vertex, **copy.deepcopy(attributes))
    if representative is None:
        representative = next(vertex for vertex in graph.nodes if vertex in vertices)
    elif representative not in vertices:
        raise ValueError('Representative must be one of the contracted vertices')
    attributes = copy.deepcopy(graph.nodes[representative])
    attributes['position'] = position
    new_graph.add_node(new_vertex, **attributes)
    for source, target, key, attributes in visible_edges(graph):
        source = new_vertex if source in vertices else source
        target = new_vertex if target in vertices else target
        if source != target or graph.graph.get('loops', False):
            key = add_edge(new_graph, source, target, attributes)
            if graph.graph.get('graph_type') == 'graph' and source != target:
                add_edge(new_graph, target, source, attributes, key)
    return new_graph


def fuse(graph, vertices, tolerance=10.0):
    """Contract each near-coincident group, preserving a representative's style.

    With no selection, consider the whole graph. A single selected vertex also
    considers unselected vertices at its position.
    The tolerance is measured in graph coordinates, independently of zoom.
    Return the replacement graph and the IDs of the newly fused vertices.
    """
    selected = [node for node in graph if node in vertices]

    def nearby(first, second):
        x1, y1 = graph.nodes[first]['position']
        x2, y2 = graph.nodes[second]['position']
        return hypot(x1 - x2, y1 - y2) <= tolerance

    if len(selected) == 1:
        candidates = [selected[0]] + [node for node in graph
                                      if node != selected[0] and nearby(node, selected[0])]
    else:
        candidates = selected or list(graph)
    groups = []
    for node in candidates:
        for group in groups:
            if all(nearby(node, member) for member in group):
                group.append(node)
                break
        else:
            groups.append([node])
    if len(selected) == 1:
        groups = groups[:1]
    fused = set()
    reserved = set(graph)
    next_id = 0
    for group in groups:
        if len(group) < 2:
            continue
        while str(next_id) in reserved:
            next_id += 1
        new_vertex = str(next_id)
        graph = contract(graph, group, new_vertex, group[0])
        reserved.add(new_vertex)
        fused.add(new_vertex)
    return graph, fused


def twin(graph, vertices, return_new_vertices=False, offset=(20, 20)):
    """Clone each selected vertex's original neighbors with one shared offset."""
    originals = [node for node in graph if node in vertices]
    original_edges = [(source, target, copy.deepcopy(data))
                      for source, target, data in graph.edges(data=True)]
    added = set()
    for node in originals:
        new_node = unused_label(graph)
        attributes = copy.deepcopy(graph.nodes[node])
        x, y = attributes['position']
        attributes['position'] = (x + offset[0], y + offset[1])
        attributes.pop('label', None)
        graph.add_node(new_node, **attributes)
        added.add(new_node)
        for source, target, data in original_edges:
            if source == node:
                graph.add_edge(new_node, target, **copy.deepcopy(data))
            if target == node:
                graph.add_edge(source, new_node, **copy.deepcopy(data))
    return (graph, added) if return_new_vertices else graph


def complement(graph, vertices):
    """Complement the graph induced by ``vertices``, or the whole graph."""
    vertices = set(vertices) & set(graph.nodes)
    vertices = list(vertices or graph.nodes)
    if graph.graph.get('graph_type') == 'graph':
        for index, source in enumerate(vertices):
            for target in vertices[index + 1:]:
                if graph.has_edge(source, target) or graph.has_edge(target, source):
                    while graph.has_edge(source, target):
                        graph.remove_edge(source, target)
                    while graph.has_edge(target, source):
                        graph.remove_edge(target, source)
                else:
                    graph.add_edge(source, target, col=0)
                    graph.add_edge(target, source, col=0)
    else:
        for source in vertices:
            for target in vertices:
                if source != target:
                    if graph.has_edge(source, target):
                        while graph.has_edge(source, target):
                            graph.remove_edge(source, target)
                    else:
                        graph.add_edge(source, target, col=0)
    return graph


def transform_selection(graph, vertices, transform):
    """Transform selected vertices and their internal edge curves about their center."""
    vertices = set(vertices) & set(graph.nodes)
    if not vertices:
        return graph
    center_x = sum(graph.nodes[node]['position'][0] for node in vertices) / len(vertices)
    center_y = sum(graph.nodes[node]['position'][1] for node in vertices) / len(vertices)

    directed = graph.graph.get('graph_type') != 'graph'
    seen_edges = set()
    curve_points = {}
    for source, target, key, _ in visible_edges(graph):
        if source not in vertices and target not in vertices:
            continue
        edge_key = ((source, target) if directed else frozenset((source, target)), key)
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)
        curve_points[(source, target, key)] = _edge_curve_points(graph, source, target, key)

    def transform_point(point):
        x, y = transform(point[0] - center_x, point[1] - center_y)
        return x + center_x, y + center_y

    for vertex in vertices:
        graph.nodes[vertex]['position'] = transform_point(graph.nodes[vertex]['position'])
    for (source, target, key), points in curve_points.items():
        if points:
            transformed = ([transform_point(point) for point in points]
                           if source in vertices and target in vertices else points)
            _set_edge_curve_points(graph, source, target, transformed, key)
    return graph


def rotate(graph, vertices, degrees):
    """Rotate selected vertices around the center of their positions."""
    angle = degrees * pi / 180
    return transform_selection(graph, vertices, lambda x, y: (
        x * cos(angle) - y * sin(angle), x * sin(angle) + y * cos(angle)))


def flip_horizontal(graph, vertices):
    """Mirror the selection left-to-right across its vertical center line."""
    return transform_selection(graph, vertices, lambda x, y: (-x, y))


def flip_vertical(graph, vertices):
    """Mirror the selection top-to-bottom across its horizontal center line."""
    return transform_selection(graph, vertices, lambda x, y: (x, -y))


def scale_selection(graph, vertices, factor):
    """Scale selected positions and internal edge curves around their center."""
    if factor <= 0:
        raise ValueError('Scale factor must be positive.')
    return transform_selection(graph, vertices,
                               lambda x, y: (factor * x, factor * y))


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


def edge_samples(graph, source, target, key=None):
    return _interpolating_curve_samples(
        graph.nodes[source]['position'], graph.nodes[target]['position'],
        _edge_curve_points(graph, source, target, key) or (_loop_controls(graph, source) if source == target else []),
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


def radial_grid_new_spokes(maximum_radius, unit, main_divisions):
    """Yield (start radius, angular index, divisions) for new radial half-lines."""
    previous_divisions = main_divisions
    for ring in range(1, min(1000, ceil(maximum_radius / unit) + 1)):
        divisions = radial_grid_divisions(ring, main_divisions)
        if divisions > previous_divisions:
            step = divisions // previous_divisions
            for index in range(divisions):
                if index % step:
                    yield ring * unit, index, divisions
            previous_divisions = divisions


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


def axis_alignment_plan(moved_positions, reference_positions, pixels_per_unit=1.0,
                        axis_visible=(False, False), origin_visible=False,
                        include_matches=False):
    """Find a shared translation and the guide lines that explain it.

    Each coordinate is independent, so a horizontal and vertical alignment may
    use different reference vertices. Distances are measured in screen pixels
    for consistent behavior at every zoom level. Farther references require a
    closer alignment before they attract the moved group. ``axis_visible`` is
    (vertical axis, horizontal axis). An axis has zero along-line separation.
    When requested, return the moved and reference indices behind each guide.
    A virtual axis target has no reference index.
    """
    if pixels_per_unit <= 0:
        empty = ((0.0, 0.0), ())
        return (*empty, ()) if include_matches else empty
    moved_positions = list(moved_positions)
    references = list(reference_positions)
    if origin_visible and (0, 0) not in references:
        references.append((0.0, 0.0))
    offsets = [0.0, 0.0]
    guides = []
    matches = []
    for axis in (0, 1):
        best = None
        for moved_index, moved in enumerate(moved_positions):
            for reference_index, reference in enumerate(references):
                gap = abs(moved[axis] - reference[axis]) * pixels_per_unit
                separation = abs(moved[1-axis] - reference[1-axis]) * pixels_per_unit
                threshold = 18 / (1 + separation / 240)
                if gap <= threshold:
                    score = (gap / threshold, gap, separation, tuple(moved), tuple(reference))
                    if best is None or score < best[0]:
                        projected = ((reference[0], moved[1]) if axis == 0 else
                                     (moved[0], reference[1]))
                        best = (score, reference[axis] - moved[axis],
                                (tuple(reference), projected), moved_index, reference_index)
            if axis_visible[axis]:
                gap = abs(moved[axis]) * pixels_per_unit
                if gap <= 18:
                    projected = ((0.0, moved[1]) if axis == 0 else
                                 (moved[0], 0.0))
                    score = (gap / 18, gap, 0.0, tuple(moved), projected)
                    if best is None or score < best[0]:
                        best = (score, -moved[axis], ((0.0, 0.0), projected),
                                moved_index, None)
        if best is not None:
            offsets[axis] = best[1]
            guides.append(best[2])
            matches.append((best[3], best[4]))
    result = (tuple(offsets), tuple(guides))
    return (*result, tuple(matches)) if include_matches else result


def axis_alignment_offset(moved_positions, reference_positions, pixels_per_unit=1.0):
    """Return only the translation of an alignment plan."""
    return axis_alignment_plan(moved_positions, reference_positions,
                               pixels_per_unit)[0]


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
    output = nx.MultiDiGraph() if graph.is_multigraph() else nx.DiGraph()
    output.graph.update(copy.deepcopy(graph.graph))
    for node, data in graph.nodes(data=True):
        attributes = copy.deepcopy(data)
        if 'position' in attributes:
            x, y = attributes.pop('position')
            attributes.update(position_x=float(x), position_y=float(y))
        output.add_node(str(node), **attributes)
    for index, (source, target, key, data) in enumerate(edge_records(graph)):
        attributes = copy.deepcopy(data)
        if graph.is_multigraph():
            # GraphML edge IDs are document-wide, while an undirected logical
            # edge uses the same key for its two stored arcs.
            attributes['graph_builder_edge_key'] = (
                f'int:{key}' if type(key) is int else f'str:{key}')
            add_edge(output, str(source), str(target), attributes, f'edge-{index}')
        else:
            add_edge(output, str(source), str(target), attributes)
    from .regions import remap_regions
    remap_regions(output, {node: str(node) for node in graph})
    return output


def convert_from_file(graph_file, kwargs=None):
    """Read old and new editor GraphML into a normalized NetworkX graph."""
    options = dict(DEFAULT_GRAPH_OPTIONS)
    if kwargs:
        options.update(kwargs)
    if not Path(graph_file).exists():
        return empty_graph(**options)
    loaded = nx.read_graphml(graph_file)
    def enabled(value):
        return value is True or str(value).strip().lower() in ('true', '1', 'yes')

    graph = (nx.MultiDiGraph() if loaded.is_multigraph() or
             enabled(loaded.graph.get('multiedges')) else nx.DiGraph())
    graph.graph.update(options)
    graph.graph.update(loaded.graph)
    graph.graph['multiedges'] = graph.is_multigraph()
    graph.graph['loops'] = (enabled(graph.graph.get('loops')) or
                            bool(nx.number_of_selfloops(loaded)))
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
    for source, target, key, data in edge_records(loaded):
        attributes = dict(data)
        attributes['col'] = int(attributes.get('col', 0))
        if graph.is_multigraph():
            stored_key = attributes.pop('graph_builder_edge_key', None)
            if isinstance(stored_key, str) and stored_key.startswith('int:'):
                key = int(stored_key[4:])
            elif isinstance(stored_key, str) and stored_key.startswith('str:'):
                key = stored_key[4:]
        add_edge(graph, str(source), str(target), attributes, key)
    if graph.graph['graph_type'] == 'graph':
        for source, target, key, data in list(edge_records(graph)):
            if not has_edge(graph, target, source, key):
                add_edge(graph, target, source, data, key)
                points = _edge_curve_points(graph, source, target, key)
                if points:
                    _set_edge_curve_points(graph, source, target, points, key)
    for source, target, key, data in list(edge_records(graph)):
        if data.get('curve_points'):
            _set_edge_curve_points(graph, source, target, _edge_curve_points(graph, source, target, key), key)
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
    key: Any = None

    def __hash__(self):
        return hash((self.key, self.directed, (self.source, self.target) if self.directed else frozenset((self.source, self.target))))

    def __eq__(self, other):
        if not isinstance(other, EdgeRef) or self.directed != other.directed or self.key != other.key:
            return False
        return ((self.source, self.target) == (other.source, other.target) if self.directed
                else frozenset((self.source, self.target)) == frozenset((other.source, other.target)))


@dataclass
class SelectionState:
    nodes: set = field(default_factory=set)
    edges: set = field(default_factory=set)
    regions: set = field(default_factory=set)

    def clear(self):
        self.nodes.clear()
        self.edges.clear()
        self.regions.clear()

    def single_node(self):
        return next(iter(self.nodes)) if len(self.nodes) == 1 and not self.edges and not self.regions else None

    def prune(self, graph):
        self.nodes.intersection_update(graph.nodes)
        self.edges = {edge for edge in self.edges if has_edge(graph, edge.source, edge.target, edge.key)}
        from .regions import regions
        self.regions.intersection_update(region['id'] for region in regions(graph))


def selected_vertices(selection):
    """Include the endpoints of selected edges in a vertex selection."""
    vertices = set(selection.nodes)
    for edge in selection.edges:
        vertices.update((edge.source, edge.target))
    return vertices


@dataclass
class GraphClipboard:
    nodes: tuple
    node_attributes: dict
    internal_edges: tuple
    boundary_edges: tuple
    regions: tuple = ()


def copy_graph_selection(graph, selected_nodes=None):
    selected = set(graph.nodes) if selected_nodes is None else set(selected_nodes) & set(graph)
    nodes = tuple(node for node in graph if node in selected)
    internal, boundary = [], []
    for source, target, key, data in edge_records(graph):
        if source in selected and target in selected:
            internal.append((source, target, key, copy.deepcopy(data)))
        elif source in selected or target in selected:
            boundary.append((source, target, key, copy.deepcopy(data)))
    from .regions import regions
    def referenced_nodes(region):
        if region['mode'] in ('hull', 'bag'):
            return set(region['nodes'])
        return {node for segment in region.get('segments', [])
                for node in (segment['source'], segment['target'])}
    copied_regions = tuple(copy.deepcopy(region) for region in regions(graph)
                           if referenced_nodes(region) <= selected)
    return GraphClipboard(nodes, {node: copy.deepcopy(dict(graph.nodes[node])) for node in nodes},
                          tuple(internal), tuple(boundary), copied_regions)


def paste_graph_selection(graph, clipboard, offset=(20, 20), *, return_regions=False):
    output = copy.deepcopy(graph)
    mapping = {}
    for old in clipboard.nodes:
        new = unused_label(output)
        data = copy.deepcopy(clipboard.node_attributes[old])
        x, y = data.get('position', (0, 0))
        data['position'] = (x + offset[0], y + offset[1])
        output.add_node(new, **data)
        mapping[old] = new
    for source, target, key, data in (*clipboard.internal_edges, *clipboard.boundary_edges):
        if source in mapping or target in mapping:
            new_source, new_target = mapping.get(source, source), mapping.get(target, target)
            if new_source in output and new_target in output:
                add_edge(output, new_source, new_target, data, key)
    from .regions import add_region
    region_ids = set()
    for region in clipboard.regions:
        remapped = copy.deepcopy(region)
        remapped['nodes'] = [mapping[node] for node in region.get('nodes', [])]
        for segment in remapped.get('segments', []):
            for field in ('source', 'target', 'edge_source', 'edge_target'):
                if field in segment:
                    segment[field] = mapping[segment[field]]
        identifier = add_region(output, mode=remapped['mode'], nodes=remapped['nodes'],
                                segments=remapped['segments'], label=remapped['label'],
                                style=remapped['style'], margin=remapped.get('margin', 0))
        region_ids.add(identifier)
    if return_regions:
        return output, set(mapping.values()), region_ids
    return output, set(mapping.values())


def cut_edges_to_rest(graph, selected_nodes):
    selected = set(selected_nodes)
    edges = [(source, target, key) if graph.is_multigraph() else (source, target)
             for source, target, key, _ in edge_records(graph)
             if (source in selected) != (target in selected)]
    graph.remove_edges_from(edges)
    return len(edges)


def pendant(graph, vertices, vertex_color=None, edge_color=0):
    """Attach one well-spaced pendant vertex to each selected vertex.

    A leaf grows away from its parent. At a branching vertex, the new edge
    points into an open angular gap and avoids nearby occupied positions.
    Return the new internal vertex IDs without changing the selection.
    """
    selected = set(vertices)
    parents = [node for node in graph if node in selected]
    if not parents:
        return set()
    occupied = [tuple(graph.nodes[node]['position']) for node in graph]
    created = set()
    directed = graph.graph.get('graph_type') != 'graph'
    for parent in parents:
        x, y = graph.nodes[parent]['position']
        neighbors = set(graph.successors(parent)) | set(graph.predecessors(parent))
        directions = []
        lengths = []
        for neighbor in neighbors:
            nx, ny = graph.nodes[neighbor]['position']
            dx, dy = nx - x, ny - y
            length = hypot(dx, dy)
            if length > 1e-6:
                directions.append(atan2(dy, dx))
                lengths.append(length)
        spacing = max(75.0, min(220.0, sorted(lengths)[len(lengths)//2]
                                  if lengths else 90.0))
        if not directions:
            preferred = -pi / 2
        elif len(directions) == 1:
            preferred = directions[0] + pi
        else:
            outward_x = -sum(cos(angle) for angle in directions)
            outward_y = -sum(sin(angle) for angle in directions)
            if hypot(outward_x, outward_y) > .25:
                preferred = atan2(outward_y, outward_x)
            else:
                ordered = sorted(directions)
                gap, start = max(((ordered[(i + 1) % len(ordered)] - angle) % (2*pi),
                                  angle) for i, angle in enumerate(ordered))
                preferred = start + gap / 2
        offsets = (0, pi/6, -pi/6, pi/3, -pi/3, pi/2, -pi/2, pi)
        candidates = []
        for offset in offsets:
            angle = preferred + offset
            position = (x + spacing*cos(angle), y + spacing*sin(angle))
            clearance = min((hypot(position[0]-px, position[1]-py)
                             for px, py in occupied if hypot(px-x, py-y) > 1e-6),
                            default=2.5 * spacing)
            score = min(clearance, 2.5 * spacing) - spacing * abs(offset) / (3*pi)
            candidates.append((score, -abs(offset), position))
        position = max(candidates)[2]
        new_vertex = unused_label(graph)
        color = graph.nodes[parent].get('col', 0) if vertex_color is None else vertex_color
        graph.add_node(new_vertex, position=position, col=color)
        graph.add_edge(parent, new_vertex, col=edge_color, label='')
        if not directed:
            graph.add_edge(new_vertex, parent, col=edge_color, label='')
        occupied.append(position)
        created.add(new_vertex)
    return created


@dataclass
class EditorContext:
    graph: nx.DiGraph | nx.MultiDiGraph
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
    description: str | None = None

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
        identity = ((edge.source, edge.target, edge.key) if context.graph.is_multigraph()
                    else (edge.source, edge.target))
        return function(context.graph, identity)
    return ContextAction(invoke, shortcut,
                         lambda context: len(context.selection.edges) == 1 and not context.selection.nodes,
                         name or function.__name__, group)


def builtin_editor_actions():
    """Editing commands present regardless of a user's custom action script."""
    def selected(context):
        return selected_vertices(context.selection)

    def transform_vertices(context):
        return selected(context) or set(context.graph.nodes)

    can_transform = lambda context: len(transform_vertices(context)) >= 2

    def add_pendants(context):
        interaction = context.interaction
        pendant(context.graph, context.selection.nodes,
                vertex_color=getattr(interaction, 'vertex_color', None),
                edge_color=getattr(interaction, 'edge_color', 0))

    def add_twins(context):
        _, added = twin(context.graph, selected(context), return_new_vertices=True)
        context.selection.clear()
        context.selection.nodes.update(added)

    def fuse_nearby(context):
        graph, added = fuse(context.graph, context.selection.nodes)
        context.graph = graph
        if added:
            context.selection.nodes.intersection_update(graph)
            context.selection.nodes.update(added)
            context.selection.edges.clear()

    return (
        Action('builtin:twin', 'Twin', 'w', add_twins,
               lambda context: bool(selected(context)), library=True, group='edition',
               description='Add a false twin vertex.'),
        Action('builtin:contract', 'Contract', 'o',
               lambda context: contract(context.graph, selected(context)),
               can_transform, library=True, group='edition',
               description='Contract the selection.'),
        Action('builtin:fuse', 'Fuse', 'f', fuse_nearby,
               lambda context: bool(context.graph), library=True, group='edition',
               description='Identify vertices with the same position.'),
        Action('builtin:complement', 'Complement', None,
               lambda context: complement(context.graph, selected(context)),
               lambda context: True, library=True, group='edition'),
        Action('builtin:pendant', 'Pendant', 'p', add_pendants,
               lambda context: bool(context.selection.nodes), library=True, group='edition',
               description='Add a pendant vertex.'),
        Action('builtin:rotate_left', 'Rotate left 10°', None,
               lambda context: rotate(context.graph, transform_vertices(context), -10),
               can_transform, library=True, group='basic',
               pair_id='transformation', pair_label='Transformation'),
        Action('builtin:rotate_right', 'Rotate right 10°', None,
               lambda context: rotate(context.graph, transform_vertices(context), 10),
               can_transform, library=True, group='basic',
               pair_id='transformation', pair_label='Transformation'),
        Action('builtin:flip_horizontal', 'Flip horizontally', None,
               lambda context: flip_horizontal(context.graph, transform_vertices(context)),
               can_transform, library=True, group='basic',
               pair_id='transformation', pair_label='Transformation'),
        Action('builtin:flip_vertical', 'Flip vertically', None,
               lambda context: flip_vertical(context.graph, transform_vertices(context)),
               can_transform, library=True, group='basic',
               pair_id='transformation', pair_label='Transformation'),
        Action('builtin:half_turn', 'Central symmetry (180°)', None,
               lambda context: rotate(context.graph, transform_vertices(context), 180),
               can_transform, library=True, group='basic',
               pair_id='transformation', pair_label='Transformation'),
        Action('builtin:grow', 'Grow ×1.1', None,
               lambda context: scale_selection(context.graph, transform_vertices(context), 1.1),
               can_transform, library=True, group='basic',
               pair_id='transformation', pair_label='Transformation'),
        Action('builtin:shrink', 'Shrink ÷1.1', None,
               lambda context: scale_selection(context.graph, transform_vertices(context), 1/1.1),
               can_transform, library=True, group='basic',
               pair_id='transformation', pair_label='Transformation'),
    )


from .custom import button, discover_buttons


def _caller_actions(actions, namespace):
    if actions is None:
        return discover_buttons(namespace)
    return [getattr(action, '__graph_button__', action) for action in actions]


def main(actions=None, graph_file=None, *, untitled=False, **options):
    """Run Graph Builder as an application, blocking until its window closes.

    Decorated functions in the calling module become Custom buttons. Pass
    ``actions`` to choose buttons explicitly, or ``graph_file`` to open a
    particular GraphML file. Use ``untitled=True`` for a new graph that asks
    where to save. The return value is an application exit code,
    not a graph. Use ``edit_graph`` to draw a graph within a Python workflow.

    Example::

        from graph_builder import *
        main()
    """
    import inspect
    import argparse
    frame = inspect.currentframe()
    try:
        actions = _caller_actions(actions, frame.f_back.f_globals)
    finally:
        del frame
    if untitled and graph_file is not None:
        raise ValueError('Choose either graph_file or untitled=True.')
    if graph_file is None and not untitled:
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument('--graph')
        arguments, _ = parser.parse_known_args()
        graph_file = arguments.graph
    from .qt import launch
    return launch(actions=actions, graph_file=graph_file, untitled=untitled, **options)


def edit_graph(graph=None, *, actions=None):
    """Open a drawing window and return the edited NetworkX graph on close.

    ``graph`` may be an ``nx.Graph`` or ``nx.DiGraph``. It is copied, so the
    original is never changed. Omit it to start with an empty undirected graph.
    The returned graph has integer vertex keys. Existing integer keys are kept,
    while other keys are reassigned and retained as visible labels. New
    vertices receive integer keys, positions, and default drawing attributes.
    Decorated functions in the calling module become Custom buttons, or pass
    ``actions`` to choose them explicitly. The window blocks until closed.
    Saving to GraphML is optional. If a file is opened in the editor, the
    currently open graph is the one returned.

    Example::

        import networkx as nx
        from graph_builder import edit_graph

        graph = edit_graph(nx.path_graph(4))
        print(graph.number_of_edges())
    """
    import inspect
    frame = inspect.currentframe()
    try:
        actions = _caller_actions(actions, frame.f_back.f_globals)
    finally:
        del frame
    from .qt import edit_graph_window
    return edit_graph_window(graph, actions=actions)
