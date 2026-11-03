"""Automatic vertex placement without Qt or changes to the graph model."""
from __future__ import annotations

from collections import deque
from math import cos, hypot, pi, sin

import networkx as nx


PIN_ATTRIBUTE = 'layout_pinned'


def pinned_vertices(graph):
    """Pins constrain layout, but never prevent manual vertex movement."""
    return {node for node, data in graph.nodes(data=True)
            if data.get(PIN_ATTRIBUTE) is True or data.get(PIN_ATTRIBUTE) == 'True'}


def movable_vertices(graph, selected=()):
    """Selection limits layout scope; without one, use every unpinned node."""
    selected = set(selected) & set(graph)
    return (selected if selected else set(graph)) - pinned_vertices(graph)


def neighborhood_distances(graph, dragged, distance=1):
    """Shortest undirected distances from a dragged group, capped locally."""
    dragged = set(dragged) & set(graph)
    distances = {node: 0 for node in dragged}
    frontier = deque((node, 0) for node in dragged)
    while frontier:
        node, depth = frontier.popleft()
        if depth >= distance:
            continue
        adjacent = set(graph.neighbors(node))
        if graph.is_directed():
            adjacent.update(graph.predecessors(node))
        for neighbor in adjacent:
            if neighbor not in distances:
                distances[neighbor] = depth + 1
                frontier.append((neighbor, depth + 1))
    return distances


def nearby_movable_vertices(graph, dragged, distance=1):
    """Unpinned neighbors of a dragged group, limited to a small local area."""
    distances = neighborhood_distances(graph, dragged, distance)
    return set(distances) - set(dragged) - pinned_vertices(graph)


def relaxed_neighborhood_positions(graph, dragged):
    """Move direct neighbors, with distance-two vertices as fixed anchors."""
    distances = neighborhood_distances(graph, dragged, distance=2)
    movable = {node for node, depth in distances.items() if depth == 1}
    movable -= pinned_vertices(graph)
    if not movable:
        return {}
    local_graph = graph.subgraph(distances)
    target = arrange_positions(local_graph, movable, iterations=4)
    result = {}
    for node, point in target.items():
        x, y = graph.nodes[node]['position']
        next_position = (x + .3 * (point[0] - x),
                         y + .3 * (point[1] - y))
        if abs(next_position[0] - x) + abs(next_position[1] - y) > .01:
            result[node] = next_position
    return result


def _spring_without_numpy(graph, positions, movable, iterations, spacing):
    """Small deterministic fallback for NetworkX's optional NumPy layout."""
    positions = {node: list(point) for node, point in positions.items()}
    nodes = list(graph)
    edges = list(graph.edges)
    span = max(max(point[axis] for point in positions.values()) -
               min(point[axis] for point in positions.values()) for axis in (0, 1))
    initial_temperature = max(10.0, span * .1)
    for iteration in range(iterations):
        movement = {node: [0.0, 0.0] for node in movable}
        for index, source in enumerate(nodes):
            for target in nodes[index + 1:]:
                if source not in movable and target not in movable:
                    continue
                dx = positions[source][0] - positions[target][0]
                dy = positions[source][1] - positions[target][1]
                distance = max(.01, hypot(dx, dy))
                force = spacing**2 / distance**2
                if source in movable:
                    movement[source][0] += dx * force
                    movement[source][1] += dy * force
                if target in movable:
                    movement[target][0] -= dx * force
                    movement[target][1] -= dy * force
        for source, target in edges:
            dx = positions[source][0] - positions[target][0]
            dy = positions[source][1] - positions[target][1]
            distance = max(.01, hypot(dx, dy))
            force = distance / spacing
            if source in movable:
                movement[source][0] -= dx * force
                movement[source][1] -= dy * force
            if target in movable:
                movement[target][0] += dx * force
                movement[target][1] += dy * force
        temperature = initial_temperature * (1 - iteration / max(1, iterations))
        for node in movable:
            dx, dy = movement[node]
            length = hypot(dx, dy)
            if length:
                step = min(length, temperature) / length
                positions[node][0] += dx * step
                positions[node][1] += dy * step
    return positions


def arrange_positions(graph, movable, iterations=80, spacing=110.0,
                      center=None, fit_size=None):
    """Return positions for movable nodes, preserving all other positions exactly.

    Starting from the drawing makes repeated use predictable. A stable small
    displacement separates coincident movable vertices, which otherwise give
    the force solver no useful direction to move.
    """
    movable = set(movable) & set(graph) - pinned_vertices(graph)
    if not movable:
        return {}
    positions = {node: tuple(map(float, graph.nodes[node]['position'])) for node in graph}
    if len(positions) < 2:
        return {node: tuple(center) if center is not None else positions[node]
                for node in movable}

    layout_graph = nx.Graph()
    layout_graph.add_nodes_from(graph)
    layout_graph.add_edges_from((u, v) for u, v in graph.edges if u != v)
    fixed = set(graph) - movable
    # Equal positions are common after importing or generating a graph.
    seen = {}
    initial = {}
    for index, node in enumerate(graph):
        x, y = positions[node]
        key = (x, y)
        count = seen.get(key, 0)
        seen[key] = count + 1
        if count and node in movable:
            angle = 2 * pi * ((index * .61803398875) % 1)
            x += 4 * count * cos(angle)
            y += 4 * count * sin(angle)
        initial[node] = (x, y)
    try:
        result = nx.spring_layout(layout_graph, pos=initial, fixed=list(fixed) or None,
                                  iterations=iterations, k=spacing, scale=None,
                                  weight=None, seed=0)
    except ImportError:
        result = _spring_without_numpy(layout_graph, initial, movable,
                                       iterations, spacing)
    if not fixed:
        before_center = (sum(p[0] for p in positions.values()) / len(positions),
                         sum(p[1] for p in positions.values()) / len(positions))
        after_center = (sum(p[0] for p in result.values()) / len(result),
                        sum(p[1] for p in result.values()) / len(result))
        offset = (before_center[0] - after_center[0],
                  before_center[1] - after_center[1])
    else:
        offset = (0, 0)
    arranged = {node: (float(result[node][0] + offset[0]),
                       float(result[node][1] + offset[1])) for node in movable}
    if not fixed and (center is not None or fit_size is not None):
        source_center = (sum(point[0] for point in arranged.values()) / len(arranged),
                         sum(point[1] for point in arranged.values()) / len(arranged))
        destination = tuple(center) if center is not None else source_center
        scale = 1.0
        if fit_size is not None:
            xs = [point[0] for point in arranged.values()]
            ys = [point[1] for point in arranged.values()]
            scale = min(1.0, fit_size[0] / max(max(xs) - min(xs), 1.0),
                        fit_size[1] / max(max(ys) - min(ys), 1.0))
        arranged = {node: (destination[0] + (point[0] - source_center[0]) * scale,
                           destination[1] + (point[1] - source_center[1]) * scale)
                    for node, point in arranged.items()}
    return arranged
