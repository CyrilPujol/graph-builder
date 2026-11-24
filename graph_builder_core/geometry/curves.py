"""Curves support for Graph Builder."""
from __future__ import annotations

import json
from math import atan2, cos, hypot, pi, sin

from graph_builder_core.model.edges import edge_data, has_edge


def _loop_controls(graph, node, index=1):
    from graph_builder_core.geometry.edge_layout import loop_controls
    return loop_controls(graph, node, index - 1)


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
