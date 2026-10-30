"""Automatic vertex placement without Qt or changes to the graph model."""
from __future__ import annotations

from collections import deque
from math import cos, pi, sin

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


def arrange_positions(graph, movable, iterations=80, spacing=110.0):
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
        return {node: positions[node] for node in movable}

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
    result = nx.spring_layout(layout_graph, pos=initial, fixed=list(fixed) or None,
                              iterations=iterations, k=spacing, scale=None,
                              weight=None, seed=0)
    if not fixed:
        before_center = (sum(p[0] for p in positions.values()) / len(positions),
                         sum(p[1] for p in positions.values()) / len(positions))
        after_center = (sum(p[0] for p in result.values()) / len(result),
                        sum(p[1] for p in result.values()) / len(result))
        offset = (before_center[0] - after_center[0],
                  before_center[1] - after_center[1])
    else:
        offset = (0, 0)
    return {node: (float(result[node][0] + offset[0]),
                   float(result[node][1] + offset[1])) for node in movable}
