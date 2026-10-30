"""GraphML-safe, layered appearance settings for vertices and edges."""
from __future__ import annotations

import json
from copy import deepcopy
from math import hypot

from graph_builder_lib import colormap_1


FIELDS = {
    'vertex': ('fill', 'outline', 'shape', 'size', 'outline_width', 'text',
               'latex_label', 'tikz_options'),
    'edge': ('stroke', 'width', 'pattern', 'opacity', 'label_t',
             'label_offset', 'latex_label', 'tikz_options'),
}


def _read(value):
    if isinstance(value, dict):
        return deepcopy(value)
    try:
        result = json.loads(value or '{}')
        return result if isinstance(result, dict) else {}
    except (TypeError, ValueError):
        return {}


def _write(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def base_style(kind, color_index):
    color = '#%02x%02x%02x' % colormap_1(color_index)
    if kind == 'vertex':
        return dict(fill=color, outline='#222222', shape='circle', size=34.0,
                    outline_width=1.5, text='auto', latex_label=False,
                    tikz_options='')
    return dict(stroke=color, width=2.6, pattern='solid', opacity=1.0,
                label_t=.5, label_offset=0.0, latex_label=False,
                tikz_options='')


def vertex_boundary_distance(style, dx, dy):
    """Distance from the vertex center to its visible boundary along a ray."""
    length = hypot(dx, dy)
    if not length:
        return 0.0
    ux, uy = dx / length, dy / length
    shape = str(style['shape']).removeprefix('hollow_')
    radius = float(style['size']) / 2
    if shape == 'none':
        return 0.0
    if shape == 'square':
        return radius / max(abs(ux), abs(uy))
    if shape == 'diamond':
        return radius / (abs(ux) + abs(uy))
    if shape == 'triangle':
        candidates = [radius / uy] if uy > 0 else []
        slope = 2 * abs(ux) - uy
        if slope > 0:
            candidates.append(radius / slope)
        return min(candidates)
    return radius


def contrast_text_color(fill):
    """Readable automatic label color, shared by canvas and TikZ export."""
    if fill == 'none':
        return '#111111'
    if isinstance(fill, str) and len(fill) == 7 and fill.startswith('#'):
        try:
            red, green, blue = (int(fill[index:index+2], 16) for index in (1, 3, 5))
            luminance = .2126 * red + .7152 * green + .0722 * blue
            return '#111111' if luminance > 145 else '#ffffff'
        except ValueError:
            pass
    return '#ffffff'


def palette_styles(graph, kind):
    return _read(graph.graph.get(f'{kind}_styles'))


def presets(graph, kind):
    return _read(graph.graph.get(f'{kind}_presets'))


def effective_style(graph, kind, attributes):
    style = base_style(kind, attributes.get('col', 0))
    style.update(palette_styles(graph, kind).get(str(attributes.get('col', 0)), {}))
    preset = attributes.get('style_preset')
    if preset:
        style.update(presets(graph, kind).get(preset, {}).get('style', {}))
    style.update(_read(attributes.get('style_overrides')))
    return style


def set_overrides(attributes, changes):
    """None removes an override, other values replace it."""
    overrides = _read(attributes.get('style_overrides'))
    for field, value in changes.items():
        if value is None:
            overrides.pop(field, None)
        else:
            overrides[field] = value
    if overrides:
        attributes['style_overrides'] = _write(overrides)
    else:
        attributes.pop('style_overrides', None)


def set_palette_style(graph, kind, index, style):
    values = palette_styles(graph, kind)
    values[str(index)] = {key: value for key, value in style.items() if key in FIELDS[kind]}
    graph.graph[f'{kind}_styles'] = _write(values)


def set_preset(graph, kind, identifier, name, style):
    values = presets(graph, kind)
    values[identifier] = {'name': name,
                          'style': {key: value for key, value in style.items()
                                    if key in FIELDS[kind]}}
    graph.graph[f'{kind}_presets'] = _write(values)


def remove_preset(graph, kind, identifier):
    """Freeze the effective appearance of linked objects before removing it."""
    values = presets(graph, kind)
    if identifier not in values:
        return
    data_items = (graph.nodes.values() if kind == 'vertex' else
                  (data for _, _, data in graph.edges(data=True)))
    for attributes in data_items:
        if attributes.get('style_preset') == identifier:
            frozen = effective_style(graph, kind, attributes)
            attributes.pop('style_preset', None)
            set_overrides(attributes, frozen)
    del values[identifier]
    graph.graph[f'{kind}_presets'] = _write(values)


def copy_style(graph, kind, attributes):
    """A snapshot that can be pasted without a live preset link."""
    return deepcopy(effective_style(graph, kind, attributes))


def paste_style(attributes, snapshot):
    attributes.pop('style_preset', None)
    set_overrides(attributes, snapshot)


def set_edge_style(graph, source, target, changes, preset=None):
    """Keep the two arcs of a logical undirected edge synchronized."""
    pairs = [(source, target)]
    if graph.graph.get('graph_type') == 'graph' and graph.has_edge(target, source):
        pairs.append((target, source))
    for pair in pairs:
        attributes = graph.edges[pair]
        set_overrides(attributes, changes)
        if preset is not None:
            if preset:
                attributes['style_preset'] = preset
            else:
                attributes.pop('style_preset', None)
