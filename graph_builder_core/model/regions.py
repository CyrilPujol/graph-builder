"""GraphML-safe regions whose boundaries follow live vertices and edge curves."""
from __future__ import annotations

import json
from math import cos, hypot, pi, sin

from graph_builder_core.geometry.curves import _interpolating_curve_samples, edge_samples
from graph_builder_core.geometry.polygons import (
    _hull, _area, _signed_area, _offset_polygon, _buffer_polygons,
)
from graph_builder_core.model.edges import has_edge


DEFAULT_REGION_STYLE = {'fill': '#c7cbd1', 'outline': '#89919a',
                        'width': 1.5, 'opacity': 0.28, 'tikz_options': ''}


def regions(graph):
    value = graph.graph.get('regions', '[]')
    try:
        loaded = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return []
    return loaded if isinstance(loaded, list) else []


def set_regions(graph, values):
    if values:
        graph.graph['regions'] = json.dumps(values, ensure_ascii=False, sort_keys=True)
    else:
        graph.graph.pop('regions', None)


def region_by_id(graph, identifier):
    return next((region for region in regions(graph) if region['id'] == identifier), None)


def update_region(graph, identifier, changes):
    items = regions(graph)
    for region in items:
        if region['id'] == identifier:
            region.update(changes)
            set_regions(graph, items)
            return
    raise KeyError(identifier)


def remove_regions(graph, identifiers):
    set_regions(graph, [region for region in regions(graph) if region['id'] not in identifiers])


def add_region(graph, *, mode, nodes=(), segments=(), label='', style=None, margin=0,
               tag=None, anchors=None):
    items = regions(graph)
    identifier = max((int(region['id']) for region in items), default=-1) + 1
    region = {'id': identifier, 'mode': mode, 'nodes': list(nodes),
              'segments': list(segments), 'label': label,
              'style': dict(DEFAULT_REGION_STYLE | (style or {})), 'margin': float(margin)}
    if anchors is not None:
        region['anchors'] = list(anchors)
    if tag is not None:
        region['tag'] = str(tag)
    items.append(region)
    set_regions(graph, items)
    return identifier


def _raw_path(graph, region):
    points, spans = [], []
    for segment in region.get('segments', []):
        sample = segment_points(graph, segment)
        if not sample:
            return [], []
        start = max(0, len(points) - 1)
        points.extend(sample if not points else sample[1:])
        spans.append((start, len(points)))
    return points, spans


def region_segment_points(graph, region, segment_index):
    """Visible segment of a manual boundary, including post-curve padding."""
    points, spans = _raw_path(graph, region)
    if not points or segment_index >= len(spans):
        return []
    start, end = spans[segment_index]
    return _offset_polygon(points, float(region.get('margin', 0)))[start:end]


def region_polygons(graph, region):
    """Resolve all visible components of a live, distance-padded region."""
    if region['mode'] in ('hull', 'bag'):
        anchors = region.get('anchors', region['nodes'])
        points = [_anchor_position(graph, anchor) for anchor in anchors
                  if isinstance(anchor, dict) or anchor in graph]
        margin = float(region.get('margin', 0))
        hull = _hull(points)
        if _area(hull) <= 1:
            # Give one or two vertices a small base region, then apply the
            # same geometric padding as for every other boundary.
            hull = _hull((x + 18*cos(i*pi/16), y + 18*sin(i*pi/16))
                         for x, y in points for i in range(32))
        return _buffer_polygons(hull, margin)
    points, _ = _raw_path(graph, region)
    if len(points) < 3 or hypot(points[0][0]-points[-1][0],
                                points[0][1]-points[-1][1]) > 1e-6:
        return []
    return _buffer_polygons(points, float(region.get('margin', 0)))


def region_points(graph, region):
    """Return the largest boundary for previews and legacy callers."""
    polygons = region_polygons(graph, region)
    if polygons:
        return max(polygons, key=_area)
    if region['mode'] == 'path':
        # An unfinished boundary is an open line used by the creation preview.
        return _raw_path(graph, region)[0]
    return []


def set_region_properties(graph, identifier, values):
    """Apply dialog values, converting modes without changing IDs or styles."""
    region = region_by_id(graph, identifier)
    if region is None:
        raise KeyError(identifier)
    target = values.get('mode', 'manual' if region['mode'] == 'path' else 'hull')
    if target not in ('manual', 'hull'):
        raise ValueError('Choose a convex hull or manual boundary.')
    current = 'manual' if region['mode'] == 'path' else 'hull'
    if target != current:
        if current == 'hull':
            anchors = region.get('anchors', region.get('nodes', []))
            if len(anchors) < 3:
                raise ValueError('A manual boundary needs at least three points.')
            region['segments'] = [path_segment(anchors[i], anchors[(i + 1) % len(anchors)])
                                  for i in range(len(anchors))]
            region['mode'] = 'path'
        else:
            anchors = [({'point': segment['source_point']} if 'source_point' in segment
                        else segment['source']) for segment in region.get('segments', [])]
            if len(anchors) < 3:
                raise ValueError('A convex hull needs at least three points.')
            region['anchors'] = anchors
            region['nodes'] = [anchor for anchor in anchors if not isinstance(anchor, dict)]
            region['segments'] = []
            region['mode'] = 'hull'
    region['margin'] = float(values.get('margin', region.get('margin', 0)))
    for field in ('label', 'style'):
        if field in values:
            region[field] = values[field]
    if not any(_area(polygon) > 1 for polygon in region_polygons(graph, region)):
        if region['margin'] < 0:
            raise ValueError('This negative padding removes the entire region.')
        raise ValueError('This boundary does not enclose an area. Change its vertex order or padding.')
    update_region(graph, identifier, region)


def _anchor_position(graph, anchor):
    return tuple(anchor['point']) if isinstance(anchor, dict) else graph.nodes[anchor]['position']


def _segment_endpoint(graph, segment, side):
    return (tuple(segment[f'{side}_point']) if f'{side}_point' in segment
            else graph.nodes[segment[side]]['position'])


def line_controls(graph, segment):
    """Convert vertex-relative control coordinates to canvas positions."""
    start = _segment_endpoint(graph, segment, 'source')
    end = _segment_endpoint(graph, segment, 'target')
    dx, dy = end[0] - start[0], end[1] - start[1]
    return [(start[0] + t*dx - normal*dy, start[1] + t*dy + normal*dx)
            for t, normal in segment.get('controls', [])]


def set_line_controls(graph, segment, positions):
    """Store controls in a moving segment's local coordinate frame."""
    start = _segment_endpoint(graph, segment, 'source')
    end = _segment_endpoint(graph, segment, 'target')
    dx, dy = end[0] - start[0], end[1] - start[1]
    length2 = dx*dx + dy*dy
    if length2 < 1e-9:
        return
    segment['controls'] = [[((x-start[0])*dx + (y-start[1])*dy)/length2,
                            (-(x-start[0])*dy + (y-start[1])*dx)/length2]
                           for x, y in positions]


def segment_points(graph, segment):
    source, target = segment['source'], segment['target']
    if (('source_point' not in segment and source not in graph) or
            ('target_point' not in segment and target not in graph)):
        return []
    if segment['kind'] == 'edge':
        first, last = segment.get('edge_source', source), segment.get('edge_target', target)
        key = segment.get('key')
        if not has_edge(graph, first, last, key):
            if graph.graph.get('graph_type') == 'graph' and has_edge(graph, last, first, key):
                first, last = last, first
            else:
                return []
        sample = edge_samples(graph, first, last, key)
        return sample if (source, target) == (first, last) else list(reversed(sample))
    start = _segment_endpoint(graph, segment, 'source')
    end = _segment_endpoint(graph, segment, 'target')
    return _interpolating_curve_samples(start, end, line_controls(graph, segment))


def path_segment(source, target, edge=None):
    if edge is None:
        segment = {'kind': 'line', 'source': source if not isinstance(source, (tuple, dict)) else None,
                   'target': target if not isinstance(target, (tuple, dict)) else None}
        for side, anchor in (('source', source), ('target', target)):
            if isinstance(anchor, (tuple, dict)):
                segment[f'{side}_point'] = list(anchor['point'] if isinstance(anchor, dict) else anchor)
        return segment
    return {'kind': 'edge', 'source': source, 'target': target,
            'edge_source': edge.source, 'edge_target': edge.target, 'key': edge.key}


def cycle_from_edges(graph, selected_edges):
    """Order selected edges into one closed boundary, or return None."""
    edges = list(selected_edges)
    if not edges:
        return None
    incident = {}
    for index, edge in enumerate(edges):
        if not has_edge(graph, edge.source, edge.target, edge.key):
            return None
        incident.setdefault(edge.source, []).append(index)
        incident.setdefault(edge.target, []).append(index)
    if any(len(indices) != 2 for indices in incident.values()):
        return None
    start = edges[0].source
    current = start
    used = set()
    segments = []
    while len(used) < len(edges):
        candidates = [index for index in incident[current] if index not in used]
        if not candidates or (len(set(candidates)) != 1 and used):
            return None
        index = min(set(candidates))
        edge = edges[index]
        following = edge.target if edge.source == current else edge.source
        segments.append(path_segment(current, following, edge))
        used.add(index)
        current = following
    if current != start:
        return None
    polygon = region_points(graph, {'mode': 'path', 'segments': segments})
    return segments if _area(polygon) > 1 else None


def hull_region_nodes(graph, nodes):
    chosen = set(nodes)
    nodes = [node for node in graph if node in chosen]
    if not nodes:
        return None
    points = [graph.nodes[node]['position'] for node in nodes]
    margin = 0 if _area(_hull(points)) > 1 else 18
    if not _area(region_points(graph, {'mode': 'hull', 'nodes': nodes, 'margin': margin})) > 1:
        return None
    return nodes, margin


def valid_boundary(graph, segments):
    return _area(region_points(graph, {'mode': 'path', 'segments': segments})) > 1


def prune_regions(graph):
    """Discard regions whose boundary references no longer exist."""
    kept = []
    for region in regions(graph):
        if region['mode'] in ('hull', 'bag'):
            if any(node not in graph for node in region.get('nodes', [])):
                continue
        if not region_polygons(graph, region):
            continue
        kept.append(region)
    set_regions(graph, kept)


def remap_regions(graph, mapping):
    """Follow a NetworkX relabeling without leaving stale region references."""
    remapped = regions(graph)
    for region in remapped:
        region['nodes'] = [mapping.get(node, node) for node in region.get('nodes', [])]
        if 'anchors' in region:
            region['anchors'] = [anchor if isinstance(anchor, dict) else mapping.get(anchor, anchor)
                                 for anchor in region['anchors']]
        for segment in region.get('segments', []):
            for field in ('source', 'target', 'edge_source', 'edge_target'):
                if field in segment:
                    segment[field] = mapping.get(segment[field], segment[field])
    set_regions(graph, remapped)
