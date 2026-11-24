"""Export positioned NetworkX graphs as standalone TikZ picture contents."""
from __future__ import annotations

from math import atan2, cos, hypot, pi, sin, tan
from pathlib import Path
import re

from graph_builder_core.geometry.curves import _edge_curve_points, _loop_controls, edge_samples
from graph_builder_core.geometry.polygons import _hull
from graph_builder_core.model.document import labels_visible
from graph_builder_core.model.edges import visible_edges
from graph_builder_core.model.palette import colormap_1
from graph_builder_core.model.regions import line_controls, region_polygons, regions
from graph_builder_core.model.styles import contrast_text_color, effective_style


# The canvas default is 34 units wide and roughly twice the label's height.
# Match that visual proportion with TikZ's default 10 pt text.
TIKZ_VERTEX_POINT_SCALE = 20 / 34
# A default 34-unit canvas vertex becomes 20 pt wide in TikZ. Since TikZ's
# unqualified coordinates are centimetres, use this same conversion for the
# graph geometry, not just for node dimensions.
TIKZ_COORDINATE_SCALE = TIKZ_VERTEX_POINT_SCALE * 2.54 / 72.27


def _number(value, places=3):
    """Keep coordinates short without throwing away visible precision."""
    rendered = f'{float(value):.{places}f}'.rstrip('0').rstrip('.')
    return '0' if rendered in ('', '-0') else rendered


def _curve_commands(start, end, controls, coordinate, endpoint):
    """Describe the canvas's circular arc or Catmull–Rom spline as TikZ cubics."""
    points = [tuple(start), *(tuple(point) for point in controls), tuple(end)]
    cubics = []
    if len(controls) == 1:
        a, middle, b = points
        ax, ay = a
        mx, my = middle
        bx, by = b
        determinant = 2 * (ax*(my-by) + mx*(by-ay) + bx*(ay-my))
        if abs(determinant) > 1e-9:
            center_x = ((ax*ax+ay*ay)*(my-by) + (mx*mx+my*my)*(by-ay)
                        + (bx*bx+by*by)*(ay-my)) / determinant
            center_y = ((ax*ax+ay*ay)*(bx-mx) + (mx*mx+my*my)*(ax-bx)
                        + (bx*bx+by*by)*(mx-ax)) / determinant
            radius = ((ax-center_x)**2 + (ay-center_y)**2)**.5
            first = atan2(ay-center_y, ax-center_x)
            via = atan2(my-center_y, mx-center_x)
            last = atan2(by-center_y, bx-center_x)
            positive = (last-first) % (2*pi)
            sweep = positive if (via-first) % (2*pi) <= positive else positive - 2*pi
            count = max(1, int(abs(sweep) / (pi/2)) + (abs(sweep) % (pi/2) > 1e-9))
            for index in range(count):
                angle = first + sweep*index/count
                next_angle = first + sweep*(index+1)/count
                delta = next_angle-angle
                factor = 4*radius*tan(delta/4)/3
                p0 = (center_x+radius*cos(angle), center_y+radius*sin(angle))
                p3 = (center_x+radius*cos(next_angle), center_y+radius*sin(next_angle))
                c1 = (p0[0]-factor*sin(angle), p0[1]+factor*cos(angle))
                c2 = (p3[0]+factor*sin(next_angle), p3[1]-factor*cos(next_angle))
                cubics.append((c1, c2, p3))
    elif len(controls) > 1:
        for index in range(len(points)-1):
            p0, p1 = points[max(0, index-1)], points[index]
            p2, p3 = points[index+1], points[min(len(points)-1, index+2)]
            c1 = tuple(p1[axis] + (p2[axis]-p0[axis])/6 for axis in (0, 1))
            c2 = tuple(p2[axis] - (p3[axis]-p1[axis])/6 for axis in (0, 1))
            cubics.append((c1, c2, p2))
    if not cubics:
        return f' -- {endpoint}'
    return ''.join(f' .. controls {coordinate(c1)} and {coordinate(c2)} .. '
                   f'{endpoint if index == len(cubics)-1 else coordinate(finish)}'
                   for index, (c1, c2, finish) in enumerate(cubics))


def _circle_through(a, b, c):
    """Return the circle through three sampled contour points, if stable."""
    ax, ay = a
    bx, by = b
    cx, cy = c
    determinant = 2 * (ax*(by-cy) + bx*(cy-ay) + cx*(ay-by))
    if abs(determinant) < 1e-6:
        return None
    x = ((ax*ax+ay*ay)*(by-cy) + (bx*bx+by*by)*(cy-ay)
         + (cx*cx+cy*cy)*(ay-by)) / determinant
    y = ((ax*ax+ay*ay)*(cx-bx) + (bx*bx+by*by)*(ax-cx)
         + (cx*cx+cy*cy)*(bx-ax)) / determinant
    radius = hypot(ax-x, ay-y)
    return (x, y, radius) if radius < 1e7 else None


def _padded_outline_commands(points, coordinate, coordinate_scale, padding):
    """Write Qt's rounded offset contour as straight segments and real arcs.

    Qt flattens rounded joins when it combines the stroke with the region.
    Restore circular joins as TikZ arcs and curved offsets as short splines.
    """
    outline = list(points[:-1] if points[0] == points[-1] else points)
    if not outline:
        return ''
    outline.append(outline[0])
    steps = sorted(hypot(outline[i+1][0]-outline[i][0],
                         outline[i+1][1]-outline[i][1])
                   for i in range(len(outline)-1))
    jump_threshold = max(12, 3*steps[len(steps)//2])
    commands = [coordinate(outline[0])]

    def round_arc(start):
        if start+2 >= len(outline):
            return None
        circle = _circle_through(*outline[start:start+3])
        if circle is None or abs(circle[2]-abs(padding)) > max(.35*abs(padding), .5):
            return None
        cx, cy, radius = circle
        first = atan2(outline[start][1]-cy, outline[start][0]-cx)
        second = atan2(outline[start+1][1]-cy, outline[start+1][0]-cx)
        direction = 1 if (second-first) % (2*pi) < pi else -1
        end, previous = start+2, second
        while end < len(outline):
            point = outline[end]
            angle = atan2(point[1]-cy, point[0]-cx)
            turn = (angle-previous) % (2*pi) if direction > 0 else (previous-angle) % (2*pi)
            sweep = ((angle-first) % (2*pi) if direction > 0
                     else (first-angle) % (2*pi))
            if (abs(hypot(point[0]-cx, point[1]-cy)-radius) > .16
                    or turn > pi/3 or sweep > 2*pi/3):
                break
            previous = angle
            end += 1
        arc_sweep = ((previous-first) % (2*pi) if direction > 0
                     else (first-previous) % (2*pi))
        return ((first, previous, direction, radius, end-1)
                if end-start >= 6 and arc_sweep > pi/6 else None)

    def straight_end(start):
        end = start+1
        while end+1 < len(outline):
            a, b, c = outline[start], outline[end], outline[end+1]
            dx, dy = c[0]-a[0], c[1]-a[1]
            distance = abs((b[0]-a[0])*dy-(b[1]-a[1])*dx) / max(hypot(dx, dy), 1e-9)
            if distance > .025:
                break
            end += 1
        return end

    def simplify_curve(chain, tolerance=1.0):
        if len(chain) < 3:
            return chain
        first, last = chain[0], chain[-1]
        dx, dy = last[0]-first[0], last[1]-first[1]
        denominator = max(hypot(dx, dy), 1e-9)
        index = max(range(1, len(chain)-1), key=lambda i:
                    abs((chain[i][0]-first[0])*dy-
                        (chain[i][1]-first[1])*dx)/denominator)
        error = abs((chain[index][0]-first[0])*dy-
                    (chain[index][1]-first[1])*dx)/denominator
        if error <= tolerance:
            return [first, last]
        return simplify_curve(chain[:index+1], tolerance)[:-1] + simplify_curve(chain[index:], tolerance)

    index = 0
    while index < len(outline)-1:
        arc = round_arc(index)
        if arc:
            first, last_angle, direction, radius, last_index = arc
            sweep = ((last_angle-first) % (2*pi) if direction > 0
                     else -((first-last_angle) % (2*pi)))
            # Screen y points down, so the TikZ arc turns the other way.
            start_degrees = -first*180/pi
            end_degrees = -(first+sweep)*180/pi
            commands.append(
                f' arc[start angle={_number(start_degrees)}, '
                f'end angle={_number(end_degrees)}, '
                f'radius={_number(radius*coordinate_scale)}cm]')
            index = last_index
            continue
        if hypot(outline[index+1][0]-outline[index][0],
                 outline[index+1][1]-outline[index][1]) > jump_threshold:
            commands.append(f' -- {coordinate(outline[index+1])}')
            index += 1
            continue
        end = straight_end(index)
        if end-index >= 8 or index+2 >= len(outline):
            commands.append(f' -- {coordinate(outline[end])}')
            index = end
            continue
        # The original boundary may itself be curved. Fit a short smooth
        # spline to its offset samples, stopping before the next round join.
        end = index+1
        while (end < len(outline)-1 and not round_arc(end)
               and straight_end(end)-end < 8
               and hypot(outline[end+1][0]-outline[end][0],
                         outline[end+1][1]-outline[end][1]) <= jump_threshold):
            end += 1
        controls = simplify_curve(outline[index:end+1])
        if len(controls) < 3:
            commands.append(f' -- {coordinate(outline[end])}')
        else:
            for part in range(len(controls)-1):
                p0, p1 = controls[max(0, part-1)], controls[part]
                p2, p3 = controls[part+1], controls[min(len(controls)-1, part+2)]
                c1 = tuple(p1[axis]+(p2[axis]-p0[axis])/6 for axis in (0, 1))
                c2 = tuple(p2[axis]-(p3[axis]-p1[axis])/6 for axis in (0, 1))
                commands.append(f' .. controls {coordinate(c1)} and {coordinate(c2)} .. {coordinate(p2)}')
        index = end
    return ''.join(commands)


def _convex_region_anchors(graph, region, positions):
    """Return editable anchors for a straight convex padded boundary."""
    if float(region.get('margin', 0)) <= 0:
        return None
    if region['mode'] in ('hull', 'bag'):
        anchors = region.get('anchors', region['nodes'])
        items = [(anchor, tuple(anchor['point']) if isinstance(anchor, dict)
                  else tuple(positions[anchor])) for anchor in anchors
                 if isinstance(anchor, dict) or anchor in graph]
        hull = _hull(point for _, point in items)
        if len(hull) < 3:
            return None
        ordered = [next((item for item in items if item[1] == point), None)
                   for point in hull]
    elif region['mode'] == 'path':
        segments = region.get('segments', [])
        if len(segments) < 3 or any(segment['kind'] != 'line' or
                                   segment.get('controls') for segment in segments):
            return None
        ordered = []
        for segment in segments:
            if 'source_point' in segment:
                point = tuple(segment['source_point'])
                anchor = {'point': point}
            else:
                anchor = segment['source']
                point = tuple(positions[anchor])
            ordered.append((anchor, point))
        for index, segment in enumerate(segments):
            end = (tuple(segment['target_point']) if 'target_point' in segment
                   else tuple(positions[segment['target']]))
            if hypot(end[0]-ordered[(index+1) % len(ordered)][1][0],
                     end[1]-ordered[(index+1) % len(ordered)][1][1]) > 1e-6:
                return None
    else:
        return None
    if any(item is None for item in ordered):
        return None
    points = [point for _, point in ordered]
    area = sum(point[0]*points[(i+1) % len(points)][1] -
               points[(i+1) % len(points)][0]*point[1]
               for i, point in enumerate(points))
    if abs(area) < 1e-8:
        return None
    orientation = 1 if area > 0 else -1
    for index, point in enumerate(points):
        before, after = points[index-1], points[(index+1) % len(points)]
        cross = ((point[0]-before[0])*(after[1]-point[1]) -
                 (point[1]-before[1])*(after[0]-point[0]))
        if orientation*cross <= 1e-8:
            return None
    return ordered, orientation


def _anchored_padding_path(anchors, orientation, padding, coordinate,
                           coordinate_scale, node_ids, region_index):
    """Offset a convex polygon with vertex-linked starts and round arcs."""
    radius = abs(padding)*coordinate_scale
    prelude = [f'    \\def\\regionpadding{{{_number(radius)}cm}}']
    points = [point for _, point in anchors]
    normals = []
    for index, point in enumerate(points):
        next_point = points[(index+1) % len(points)]
        dx, dy = next_point[0]-point[0], next_point[1]-point[1]
        length = hypot(dx, dy)
        normals.append((orientation*dy/length, -orientation*dx/length))
    corners = []
    for index, (anchor, point) in enumerate(anchors):
        if isinstance(anchor, dict):
            name = f'region{region_index}anchor{index}'
            prelude.append(f'    \\coordinate ({name}) at {coordinate(point)};')
            reference = f'({name})'
        else:
            reference = f'({node_ids[anchor]}.center)'
        before, after = normals[index-1], normals[index]
        start = -atan2(before[1], before[0])*180/pi
        finish = -atan2(after[1], after[0])*180/pi
        sweep = ((start-finish) % 360 if orientation > 0
                 else -((finish-start) % 360))
        corners.append((reference, start, start-sweep))
    segments = []
    for index, (reference, start, finish) in enumerate(corners):
        if index == 0:
            offset = f'{reference} ++({_number(start)}:\\regionpadding)'
        else:
            # A plain "-- (v) ++(...)" would draw through the vertex first.
            # The shifted coordinate keeps the offset directly in the path.
            offset = (f'([shift={{({_number(start)}:\\regionpadding)}}]'
                      f'{reference[1:-1]})')
        segments.append(f'{"-- " if index else ""}{offset} '
                        f'arc[start angle={_number(start)}, '
                        f'end angle={_number(finish)}, radius=\\regionpadding]')
    return prelude, '\n        '.join(segments) + ' -- cycle'

def _color_index(attributes):
    try:
        return max(0, int(attributes.get('style', 0)))
    except (TypeError, ValueError):
        return 0


def _rgb(color_index):
    return ','.join(str(channel) for channel in colormap_1(color_index))


def _vertex_text_color(style):
    if style['text'] != 'auto':
        return style['text']
    fill = 'none' if style['shape'].startswith('hollow_') else style['fill']
    return contrast_text_color(fill)


def graph_to_tikz(graph, max_width_cm=14.0, max_height_cm=9.0):
    """Return compact, editable TikZ source that fits a page-sized area."""
    nodes = list(graph.nodes)
    node_ids = {node: f'v{index}' for index, node in enumerate(nodes)}
    positions = {
        node: graph.nodes[node].get('position', (0.0, 0.0))
        for node in nodes
    }
    region_boundaries = [(region, points, index == 0)
                         for region in regions(graph)
                         for index, points in enumerate(region_polygons(graph, region))
                         if len(points) >= 3]

    all_positions = list(positions.values()) + [point for _, points, _ in region_boundaries for point in points]
    if all_positions:
        min_x = min(position[0] for position in all_positions)
        max_x = max(position[0] for position in all_positions)
        min_y = min(position[1] for position in all_positions)
        max_y = max(position[1] for position in all_positions)
    else:
        min_x = max_x = min_y = max_y = 0.0
    graph_width = max(max_x - min_x, 1.0)
    graph_height = max(max_y - min_y, 1.0)
    page_scale = min(1.0, max_width_cm / (graph_width * TIKZ_COORDINATE_SCALE),
                     max_height_cm / (graph_height * TIKZ_COORDINATE_SCALE))
    coordinate_scale = TIKZ_COORDINATE_SCALE * page_scale
    length_scale = TIKZ_VERTEX_POINT_SCALE * page_scale

    def tikz_position(position):
        return ((position[0] - min_x) * coordinate_scale,
                (max_y - position[1]) * coordinate_scale)

    def coordinate(position):
        x, y = tikz_position(position)
        return f'({_number(x)},{_number(y)})'

    def node_ref(node):
        return f'({node_ids[node]}.center)'

    vertex_colors = sorted({_color_index(graph.nodes[node]) for node in nodes})
    edges = list(visible_edges(graph))
    directed = graph.graph.get('graph_type') != 'graph'
    edge_colors = sorted({_color_index(attributes) for _, _, _, attributes in edges})
    vertex_appearances = {node: effective_style(graph, 'vertex', graph.nodes[node])
                          for node in nodes}
    edge_appearances = {(source, target, key): effective_style(graph, 'edge', attributes)
                        for source, target, key, attributes in edges}
    base_vertices = {index: effective_style(graph, 'vertex', {'style': index})
                     for index in vertex_colors}
    base_edges = {index: effective_style(graph, 'edge', {'style': index})
                  for index in edge_colors}
    show_labels = labels_visible(graph)
    has_vertex_labels = show_labels and any(
        str(graph.nodes[node].get('label', node)) for node in nodes)
    has_edge_labels = show_labels and any(
        str(attributes.get('label', '')) for _, _, _, attributes in edges)
    has_region_labels = any(region.get('label') for region, _, first in region_boundaries
                            if first)
    custom_colors = {}
    for style in (*base_vertices.values(), *vertex_appearances.values()):
        custom_colors.update((value.lower(), None) for value in
                             (style['fill'], style['outline'],
                              _vertex_text_color(style))
                             if isinstance(value, str) and value.startswith('#'))
    for style in (*base_edges.values(), *edge_appearances.values()):
        value = style['stroke']
        if isinstance(value, str) and value.startswith('#'):
            custom_colors[value.lower()] = None
    for region, _, _ in region_boundaries:
        for value in (region['style']['fill'], region['style']['outline']):
            if isinstance(value, str) and value.startswith('#'):
                custom_colors[value.lower()] = None
    palette_colors = {}
    for index in vertex_colors:
        palette_colors.setdefault('#%02x%02x%02x' % colormap_1(index),
                                  f'vertexcolor{index}')
    for index in edge_colors:
        palette_colors.setdefault('#%02x%02x%02x' % colormap_1(index),
                                  f'edgecolor{index}')
    custom_colors = {value: f'graphstyle{index}'
                     for index, value in enumerate(sorted(
                         value for value in custom_colors
                         if value not in ('#ffffff', '#000000') and
                         value not in palette_colors))}

    def color_name(value):
        if str(value).lower() == '#ffffff':
            return 'white'
        if str(value).lower() == '#000000':
            return 'black'
        return palette_colors.get(str(value).lower(),
                                  custom_colors.get(str(value).lower(), value))

    lines = [
        r'\pgfdeclarelayer{background}',
        r'\pgfdeclarelayer{edgelayer}',
        r'\pgfdeclarelayer{nodelayer}',
        r'\pgfsetlayers{background,edgelayer,nodelayer,main}',
        '',
    ]
    if directed and edges:
        lines.insert(0, r'\usetikzlibrary{arrows.meta}')
    if any(style['shape'].removeprefix('hollow_') in ('diamond', 'triangle')
           for style in vertex_appearances.values()):
        lines.insert(0, r'\usetikzlibrary{shapes.geometric}')
    for color_index in vertex_colors:
        lines.append(f'\\definecolor{{vertexcolor{color_index}}}{{RGB}}{{{_rgb(color_index)}}}')
    for color_index in edge_colors:
        lines.append(f'\\definecolor{{edgecolor{color_index}}}{{RGB}}{{{_rgb(color_index)}}}')
    for value, name in custom_colors.items():
        lines.append(f'\\definecolor{{{name}}}{{HTML}}{{{value[1:]}}}')

    def vertex_options(style):
        shape = style['shape']
        fill = style['fill']
        if shape.startswith('hollow_'):
            shape, fill = shape[7:], 'none'
        shape_option = {'circle': 'circle', 'square': 'rectangle',
                        'diamond': 'diamond',
                        'triangle': 'regular polygon, regular polygon sides=3',
                        'none': 'draw=none, fill=none'}.get(shape, 'circle')
        options = (f'{shape_option}, draw={color_name(style["outline"]) if shape != "none" else "none"}, '
                   f'fill={color_name(fill) if shape != "none" else "none"}, '
                   f'text={color_name(_vertex_text_color(style))}, '
                   f'line width={_number(float(style["outline_width"])*length_scale)}pt, '
                   f'minimum size={_number(float(style["size"])*length_scale)}pt, '
                   'inner sep=0pt')
        if style['tikz_options'].strip():
            options += ', ' + style['tikz_options'].strip()
        return options

    def edge_options(style, *, include_raw=True, include_arrow=True):
        dash = {'solid': 'solid', 'dash': 'dashed', 'dot': 'dotted',
                'dashdot': 'dash dot'}.get(style['pattern'], 'solid')
        options = (f'draw={color_name(style["stroke"])}, '
                   f'line width={_number(float(style["width"])*length_scale)}pt, '
                   f'opacity={_number(style["opacity"])}, {dash}, fill=none')
        if directed and include_arrow:
            tip = {'triangle': 'Triangle', 'stealth': 'Stealth',
                   'latex': 'Latex', 'open': 'Triangle'}.get(
                       style.get('arrow_shape', 'triangle'), 'Triangle')
            modifier = 'open,' if style.get('arrow_shape') == 'open' else ''
            length = _number(float(style.get('arrow_length', 11)) * length_scale)
            width = _number(float(style.get('arrow_width', 10)) * length_scale)
            options += f', ->, >={{{tip}[{modifier}length={length}pt,width={width}pt]}}'
        if include_raw and style['tikz_options'].strip():
            options += ', ' + style['tikz_options'].strip()
        return options

    for index, style in base_vertices.items():
        lines.append(f'\\tikzset{{vertex_{index}/.style={{{vertex_options(style)}}}}}')
    for index, style in base_edges.items():
        lines.append(f'\\tikzset{{edge_{index}/.style={{{edge_options(style)}}}}}')
    label_font = ('' if page_scale == 1 else
                  f'font=\\fontsize{{{_number(10*page_scale)}pt}}'
                  f'{{{_number(12*page_scale)}pt}}\\selectfont, ')
    if has_vertex_labels:
        lines.append(f'\\tikzset{{vertex_label/.style={{{label_font}inner sep=0pt, anchor=center, draw=none, fill=none}}}}')
    if has_edge_labels:
        lines.append(f'\\tikzset{{edge_label/.style={{{label_font}fill=white, inner sep={_number(page_scale)}pt}}}}')
    if has_region_labels:
        lines.append(f'\\tikzset{{region_label/.style={{{label_font}draw=none, fill=none, text=black}}}}')
    lines.extend(('', r'\begin{tikzpicture}', r'  \begin{pgfonlayer}{nodelayer}'))

    vertex_label_lines = []
    for node in nodes:
        style = f"vertex_{_color_index(graph.nodes[node])}"
        appearance = vertex_appearances[node]
        label_value = graph.nodes[node].get('label', node)
        label = str(label_value) if show_labels else ''
        options = f'style={style}'
        if appearance != base_vertices[_color_index(graph.nodes[node])]:
            options += ', ' + vertex_options(appearance)
        # Keep the body at the chosen diameter. A separate label node remains
        # part of TikZ's picture bounds, so long labels are not cropped.
        lines.append(
            f'    \\node[{options}] ({node_ids[node]}) at {coordinate(positions[node])} {{}};'
        )
        if label:
            label_options = f'vertex_label, text={color_name(_vertex_text_color(appearance))}'
            if appearance['tikz_options'].strip():
                label_options += ', ' + appearance['tikz_options'].strip()
            label_options += ', draw=none, fill=none'
            vertex_label_lines.append(
                f'  \\node[{label_options}] at ({node_ids[node]}.center) '
                f'{{{label}}};')
    lines.extend([
        r'  \end{pgfonlayer}',
        r'  \begin{pgfonlayer}{background}',
    ])
    for region_index, (region, points, first_component) in enumerate(region_boundaries):
        style = region['style']
        options = (f'fill={color_name(style["fill"])}, '
                   f'draw={color_name(style["outline"])}, '
                   f'line width={_number(float(style["width"])*length_scale)}pt, '
                   f'fill opacity={_number(style["opacity"])}, '
                   f'draw opacity={_number(style["opacity"])}')
        if style.get('tikz_options', '').strip():
            options += ', ' + style['tikz_options'].strip()
        simple_path = (region['mode'] == 'path' and not float(region.get('margin', 0))
                       and first_component and sum(item is region for item, _, _ in region_boundaries) == 1)
        anchored = (_convex_region_anchors(graph, region, positions)
                    if first_component and float(region.get('margin', 0)) > 0 and
                    sum(item is region for item, _, _ in region_boundaries) == 1
                    else None)
        if anchored:
            prelude, path = _anchored_padding_path(
                *anchored, float(region['margin']), coordinate,
                coordinate_scale, node_ids, region_index)
            lines.extend(prelude)
            lines.append(f'    \\path[{options}]\n        {path};')
        elif simple_path:
            segments = region['segments']
            first = segments[0]
            start = (coordinate(first['source_point']) if 'source_point' in first
                     else node_ref(first['source']))
            path = start
            for segment in segments:
                end = (coordinate(segment['target_point']) if 'target_point' in segment
                       else node_ref(segment['target']))
                if segment['kind'] == 'edge':
                    edge_source = segment.get('edge_source', segment['source'])
                    edge_target = segment.get('edge_target', segment['target'])
                    controls = (_edge_curve_points(graph, edge_source, edge_target, segment.get('key'))
                                or (_loop_controls(graph, edge_source) if edge_source == edge_target else []))
                    if (segment['source'], segment['target']) != (edge_source, edge_target):
                        controls = list(reversed(controls))
                else:
                    controls = line_controls(graph, segment)
                start_position = (tuple(segment['source_point']) if 'source_point' in segment
                                  else positions[segment['source']])
                end_position = (tuple(segment['target_point']) if 'target_point' in segment
                                else positions[segment['target']])
                path += _curve_commands(start_position, end_position, controls, coordinate, end)
            lines.append(f'    \\path[{options}] {path} -- cycle;')
        else:
            # Padding changes the actual contour, so preserve that geometry.
            # Vertex references remain useful for unpadded convex hulls.
            def boundary_point(point):
                if not float(region.get('margin', 0)):
                    for node, position in positions.items():
                        if abs(position[0]-point[0]) < 1e-6 and abs(position[1]-point[1]) < 1e-6:
                            return node_ref(node)
                return coordinate(point)
            if float(region.get('margin', 0)):
                path = _padded_outline_commands(points, coordinate, coordinate_scale,
                                                float(region['margin']))
            else:
                outline = points[:-1] if points[0] == points[-1] else points
                path = ' -- '.join(boundary_point(point) for point in outline)
            lines.append(f'    \\path[{options}] {path} -- cycle;')
        if first_component and region.get('label'):
            center = (sum(point[0] for point in points) / len(points),
                      sum(point[1] for point in points) / len(points))
            lines.append(f'    \\node[region_label] at {coordinate(center)} '
                         f'{{{region["label"]}}};')
    lines.extend([
        r'  \end{pgfonlayer}',
        r'  \begin{pgfonlayer}{edgelayer}',
    ])

    for source, target, key, attributes in edges:
        color_index = _color_index(attributes)
        edge_style = f'edge_{color_index}'
        appearance = edge_appearances[(source, target, key)]
        label_value = attributes.get('label', '')
        label = str(label_value) if show_labels else ''
        options = f'style={edge_style}'
        if appearance != base_edges[color_index]:
            arrow_fields = ('arrow_shape', 'arrow_length', 'arrow_width')
            arrow_changed = any(appearance.get(field) != base_edges[color_index].get(field)
                                for field in arrow_fields)
            options += ',' + edge_options(appearance, include_raw=False,
                                          include_arrow=arrow_changed)
        # Raw options are last, so a deliberate TikZ override wins.
        if appearance['tikz_options'].strip():
            options += ', ' + appearance['tikz_options'].strip()
        controls = _edge_curve_points(graph, source, target, key)
        if controls or source == target:
            samples = edge_samples(graph, source, target, key)
            actual_controls = controls or _loop_controls(graph, source)
            path = _curve_commands(positions[source], positions[target], actual_controls,
                                   coordinate, f'({node_ids[target]})')
            lines.append(f'    \\draw[{options}] ({node_ids[source]}){path};')
            index = round((len(samples)-1) * float(appearance['label_t']))
            label_position = samples[index]
            tangent_before = samples[max(0, index-1)]
            tangent_after = samples[min(len(samples)-1, index+1)]
        else:
            lines.append(
                f'    \\draw[{options}] '
                f'({node_ids[source]}) to ({node_ids[target]});'
            )
            t = float(appearance['label_t'])
            label_position = ((1-t)*positions[source][0] + t*positions[target][0],
                              (1-t)*positions[source][1] + t*positions[target][1])
            tangent_before, tangent_after = positions[source], positions[target]
        if label:
            if appearance['label_offset']:
                from math import hypot
                dx = tangent_after[0] - tangent_before[0]
                dy = tangent_after[1] - tangent_before[1]
                length = hypot(dx, dy)
                if length:
                    offset = float(appearance['label_offset'])
                    label_position = (label_position[0] - dy*offset/length,
                                      label_position[1] + dx*offset/length)
            lines.append(
                f'    \\node[edge_label] at {coordinate(label_position)} {{{label}}};'
            )

    lines.extend([
        r'  \end{pgfonlayer}',
        *vertex_label_lines,
        r'\end{tikzpicture}',
        '',
    ])
    # A palette color is often superseded by an exact style color. Keep only
    # definitions that the emitted nodes and paths actually reference.
    body = '\n'.join(line for line in lines if not line.startswith(r'\definecolor{'))
    lines = [line for line in lines
             if not line.startswith(r'\definecolor{') or
             re.search(r'(?<![A-Za-z0-9])' +
                       re.escape(line.split('{', 2)[1].split('}', 1)[0]) +
                       r'(?![A-Za-z0-9])', body)]
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
