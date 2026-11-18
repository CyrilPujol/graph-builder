"""Choose compact edge curves from the geometry already on the canvas.

The controls are stored in graph coordinates, so the same path is used by Qt,
GraphML and TikZ. This module has no GUI dependency.
"""
from __future__ import annotations

from math import cos, hypot, pi, sin

from .edges import visible_edges
from .styles import effective_style


def _at(samples, fraction):
    position = fraction * (len(samples) - 1)
    index = min(int(position), len(samples) - 2)
    amount = position - index
    first, second = samples[index], samples[index + 1]
    return (first[0] + amount * (second[0] - first[0]),
            first[1] + amount * (second[1] - first[1]))


def _distance_to_path(point, samples):
    best = float('inf')
    for first, second in zip(samples, samples[1:]):
        dx, dy = second[0] - first[0], second[1] - first[1]
        length_squared = dx*dx + dy*dy
        fraction = (0 if length_squared == 0 else max(0, min(1,
                    ((point[0] - first[0])*dx + (point[1] - first[1])*dy)
                    / length_squared)))
        best = min(best, hypot(point[0] - first[0] - fraction*dx,
                               point[1] - first[1] - fraction*dy))
    return best


def _obstacles(graph, source, target):
    """Cache current paths and vertex discs once per edge creation."""
    from .lib import edge_samples
    edges = []
    for first, second, key, data in visible_edges(graph):
        if ('position' not in graph.nodes[first] or
                'position' not in graph.nodes[second]):
            continue
        samples = edge_samples(graph, first, second, key)
        same_pair = source != target and {first, second} == {source, target}
        if same_pair and (first, second) != (source, target):
            samples = list(reversed(samples))
        width = float(effective_style(graph, 'edge', data)['width'])
        edges.append((same_pair, samples, width))
    vertices = []
    for node, data in graph.nodes(data=True):
        if node in (source, target) or 'position' not in data:
            continue
        style = effective_style(graph, 'vertex', data)
        vertices.append((data['position'], max(12, float(style['size']) / 2) + 7))
    return edges, vertices


def _obstruction(samples, edges, vertices):
    """Penalize overlap and intervening vertices, allowing isolated crossings."""
    fractions = (.2, .3, .4, .5, .6, .7, .8)
    interior = [_at(samples, fraction) for fraction in fractions]
    penalty = 0.0
    for position, clearance in vertices:
        # Use the whole polyline so a vertex cannot slip between sample sites
        # on a long edge.
        gap = _distance_to_path(position, samples)
        penalty += max(0, clearance - gap) ** 2 * 4
    for same_pair, other, width in edges:
        if same_pair:
            distances = [hypot(point[0] - _at(other, fraction)[0],
                               point[1] - _at(other, fraction)[1])
                         for point, fraction in zip(interior, fractions)]
            # Edges may touch at their endpoints. The middle of their paths
            # must be separate enough to grab either one.
            threshold = max(13, width / 2 + 8)
            penalty += max(0, threshold - distances[3]) ** 2 * 8
            penalty += sum(max(0, 9 - distance) ** 2 for distance in
                           (distances[1], distances[5]))
        else:
            # A single crossing is normal. Several nearby samples indicate
            # that the proposed edge follows an existing path.
            near = [_distance_to_path(point, other) for point in interior]
            if sum(distance < max(9, width / 2 + 5) for distance in near) >= 3:
                penalty += sum(max(0, 10 - distance) ** 2 for distance in near)
    return penalty


def parallel_controls(graph, source, target):
    """Find the shortest free straight or one-control path between vertices."""
    from .lib import _interpolating_curve_samples
    start, end = graph.nodes[source]['position'], graph.nodes[target]['position']
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = hypot(dx, dy)
    if length < 1:
        dx, dy, length = 1, 0, 1
    normal = (-dy / length, dx / length)
    midpoint = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
    edges, vertices = _obstacles(graph, source, target)
    rings = max(6, sum(same_pair for same_pair, _, _ in edges) + 3)
    best = None
    for slot in range(2 * rings + 1):
        offset = 0 if slot == 0 else 28 * ((slot + 1) // 2) * (1 if slot % 2 else -1)
        controls = ([] if offset == 0 else
                    [(midpoint[0] + normal[0]*offset,
                      midpoint[1] + normal[1]*offset)])
        samples = _interpolating_curve_samples(start, end, controls)
        penalty = _obstruction(samples, edges, vertices)
        if penalty < 1e-7:
            return controls
        score = penalty + abs(offset) * .02
        if best is None or score < best[0]:
            best = (score, controls)
    return best[1]


def loop_controls(graph, node, slot=0):
    """A small two-control petal, initially on the left of the vertex."""
    x, y = graph.nodes[node]['position']
    size = float(effective_style(graph, 'vertex', graph.nodes[node])['size'])
    radius = size / 2
    angle = pi + (slot % 8) * pi / 4
    extent = radius + 22 + 14 * (slot // 8)
    half_width = max(10, radius * .68) + 3 * (slot // 8)
    ux, uy = cos(angle), sin(angle)
    nx, ny = -uy, ux
    return [(x + ux*extent - nx*half_width, y + uy*extent - ny*half_width),
            (x + ux*extent + nx*half_width, y + uy*extent + ny*half_width)]


def free_loop_controls(graph, node):
    """Prefer the reference's left-hand loop, then other clear directions."""
    from .lib import _interpolating_curve_samples
    center = graph.nodes[node]['position']
    edges, vertices = _obstacles(graph, node, node)
    loops = sum(first == second == node for first, second, _, _ in visible_edges(graph))
    best = None
    for slot in range(max(8, loops + 4)):
        controls = loop_controls(graph, node, slot)
        samples = _interpolating_curve_samples(center, center, controls)
        penalty = _obstruction(samples, edges, vertices)
        if penalty < 1e-7:
            return controls
        score = penalty + slot * .1
        if best is None or score < best[0]:
            best = (score, controls)
    return best[1]
