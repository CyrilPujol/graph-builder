"""Curves support for Graph Builder."""
from __future__ import annotations

import json
from math import atan2, cos, hypot, pi, sin, tan

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


def curve_cubics(start, end, controls):
    """Describe an interpolating curve as cubic Bézier segments (four points each)."""
    points = [tuple(start), *(tuple(point) for point in controls), tuple(end)]
    if len(controls) == 1:
        ax, ay = start
        mx, my = controls[0]
        bx, by = end
        determinant = 2 * (ax*(my-by) + mx*(by-ay) + bx*(ay-my))
        if abs(determinant) > 1e-8:
            cx = ((ax*ax+ay*ay)*(my-by) + (mx*mx+my*my)*(by-ay)
                  + (bx*bx+by*by)*(ay-my)) / determinant
            cy = ((ax*ax+ay*ay)*(bx-mx) + (mx*mx+my*my)*(ax-bx)
                  + (bx*bx+by*by)*(mx-ax)) / determinant
            radius = hypot(ax-cx, ay-cy)
            first = atan2(ay-cy, ax-cx)
            via = atan2(my-cy, mx-cx)
            last = atan2(by-cy, bx-cx)
            positive = (last-first) % (2*pi)
            sweep = positive if (via-first) % (2*pi) <= positive else positive-2*pi
            count = max(1, int(abs(sweep)/(pi/2)) + (abs(sweep) % (pi/2) > 1e-9))
            segments = []
            for index in range(count):
                a, b = first+sweep*index/count, first+sweep*(index+1)/count
                factor = 4*radius*tan((b-a)/4)/3
                p0, p3 = (cx+radius*cos(a), cy+radius*sin(a)), (cx+radius*cos(b), cy+radius*sin(b))
                segments.append((p0, (p0[0]-factor*sin(a), p0[1]+factor*cos(a)),
                                 (p3[0]+factor*sin(b), p3[1]-factor*cos(b)), p3))
            segments[0] = (tuple(start), *segments[0][1:])
            segments[-1] = (*segments[-1][:-1], tuple(end))
            return segments
    elif len(controls) > 1:
        segments = []
        for index in range(len(points)-1):
            p0, p1 = points[max(0, index-1)], points[index]
            p2, p3 = points[index+1], points[min(len(points)-1, index+2)]
            c1 = tuple(p1[axis]+(p2[axis]-p0[axis])/6 for axis in (0, 1))
            c2 = tuple(p2[axis]-(p3[axis]-p1[axis])/6 for axis in (0, 1))
            segments.append((p1, c1, c2, p2))
        return segments
    start, end = tuple(start), tuple(end)
    return [(start, tuple(start[a]+(end[a]-start[a])/3 for a in (0, 1)),
             tuple(start[a]+2*(end[a]-start[a])/3 for a in (0, 1)), end)]


def split_cubic(segment, t):
    """Split a cubic exactly using de Casteljau's construction."""
    def mix(a, b):
        return tuple((1-t)*a[i]+t*b[i] for i in (0, 1))
    p0, p1, p2, p3 = segment
    a, b, c = mix(p0, p1), mix(p1, p2), mix(p2, p3)
    d, e = mix(a, b), mix(b, c)
    point = mix(d, e)
    return (p0, a, d, point), (point, e, c, p3)


def _trim_curve_start(segments, center, style):
    """Discard the initial portion inside a vertex, retaining the exact curve."""
    from graph_builder_core.model.styles import vertex_boundary_distance

    if style['shape'] == 'none':
        return segments

    def outside(point):
        dx, dy = point[0]-center[0], point[1]-center[1]
        return hypot(dx, dy) > vertex_boundary_distance(style, dx, dy)

    for index, segment in enumerate(segments):
        # Bracket the first boundary crossing, then refine it independently
        # of the display sampling density or the size of the vertex.
        for step in range(1, 129):
            t = step/128
            if outside(split_cubic(segment, t)[0][-1]):
                low, high = (step-1)/128, t
                for _ in range(35):
                    middle = (low+high)/2
                    if outside(split_cubic(segment, middle)[0][-1]):
                        high = middle
                    else:
                        low = middle
                return [split_cubic(segment, high)[1], *segments[index+1:]]
    return []


def visible_edge_cubics(graph, source, target, key=None):
    """Clip an edge at its styled vertices, including loops and large shapes.

    Arrowheads use the final tangent of these same segments on the canvas
    and in TikZ. Stored curve handles and positions remain unchanged.
    """
    from graph_builder_core.model.styles import effective_style, vertex_boundary_distance

    start, end = graph.nodes[source]['position'], graph.nodes[target]['position']
    controls = _edge_curve_points(graph, source, target, key)
    if source == target and not controls:
        controls = _loop_controls(graph, source)
    source_style = effective_style(graph, 'vertex', graph.nodes[source])
    target_style = effective_style(graph, 'vertex', graph.nodes[target])
    if not controls:
        # Most edges are straight: intersect their rays directly rather than
        # searching a Bézier parameter on every vertex drag.
        dx, dy = end[0]-start[0], end[1]-start[1]
        length = hypot(dx, dy)
        if not length:
            return []
        first = vertex_boundary_distance(source_style, dx, dy)
        last = vertex_boundary_distance(target_style, -dx, -dy)
        if first+last >= length:
            return []
        a = (start[0]+dx*first/length, start[1]+dy*first/length)
        b = (end[0]-dx*last/length, end[1]-dy*last/length)
        return curve_cubics(a, b, [])
    segments = curve_cubics(start, end, controls)
    segments = _trim_curve_start(segments, start, source_style)
    reverse = [tuple(reversed(segment)) for segment in reversed(segments)]
    reverse = _trim_curve_start(reverse, end, target_style)
    return [tuple(reversed(segment)) for segment in reversed(reverse)]
