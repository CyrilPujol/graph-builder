"""Graph editing operations, without menus, dialogs or history side effects."""
from __future__ import annotations

import copy
from math import atan2, cos, hypot, pi, sin

import networkx as nx

from graph_builder_core.geometry.curves import _edge_curve_points, _set_edge_curve_points
from graph_builder_core.model.document import unused_label
from graph_builder_core.model.edges import (
    edge_data, edge_records, visible_edges, add_edge, has_edge,
)


def flip_edge(graph, source, target, edge_color=0, *, avoid_obstacles=False):
    """Toggle a simple edge, or add a clear path in a multigraph.

    Canvas creation can request obstacle avoidance for ordinary edges too.
    Generated graphs keep their explicitly chosen layouts by default.
    """
    if source == target and not graph.graph.get('loops', False):
        return
    if graph.is_multigraph():
        from graph_builder_core.geometry.edge_layout import free_loop_controls, parallel_controls
        controls = []
        if all(node in graph and 'position' in graph.nodes[node]
               for node in (source, target)):
            controls = (free_loop_controls(graph, source) if source == target else
                        parallel_controls(graph, source, target))
        # Use a free key in both directions so paired undirected arcs agree.
        key = 0
        while has_edge(graph, source, target, key) or has_edge(graph, target, source, key):
            key += 1
        add_edge(graph, source, target, {'style': edge_color}, key)
        if graph.graph.get('graph_type') == 'graph' and source != target:
            add_edge(graph, target, source, {'style': edge_color}, key)
        if controls:
            _set_edge_curve_points(graph, source, target, controls, key)
        return key
    controls = None
    adding = (not graph.has_edge(source, target) and
              (graph.graph.get('graph_type') != 'graph' or
               not graph.has_edge(target, source)))
    if adding and all(node in graph and 'position' in graph.nodes[node]
                      for node in (source, target)):
        if source == target:
            from graph_builder_core.geometry.edge_layout import free_loop_controls
            controls = free_loop_controls(graph, source)
        elif avoid_obstacles:
            from graph_builder_core.geometry.edge_layout import parallel_controls
            controls = parallel_controls(graph, source, target)
    if graph.graph.get('graph_type') == 'graph':
        if graph.has_edge(source, target) or graph.has_edge(target, source):
            graph.remove_edges_from(((source, target), (target, source)))
        else:
            graph.add_edge(source, target, style=edge_color)
            graph.add_edge(target, source, style=edge_color)
    elif graph.has_edge(source, target):
        graph.remove_edge(source, target)
    else:
        graph.add_edge(source, target, style=edge_color)
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
                    graph.add_edge(source, target, style=0)
                    graph.add_edge(target, source, style=0)
    else:
        for source in vertices:
            for target in vertices:
                if source != target:
                    if graph.has_edge(source, target):
                        while graph.has_edge(source, target):
                            graph.remove_edge(source, target)
                    else:
                        graph.add_edge(source, target, style=0)
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
        color = graph.nodes[parent].get('style', 0) if vertex_color is None else vertex_color
        graph.add_node(new_vertex, position=position, style=color)
        graph.add_edge(parent, new_vertex, style=edge_color, label='')
        if not directed:
            graph.add_edge(new_vertex, parent, style=edge_color, label='')
        occupied.append(position)
        created.add(new_vertex)
    return created
