"""GraphML-safe, layered appearance settings for vertices and edges."""
from __future__ import annotations

from copy import deepcopy
import json
from math import hypot

from graph_builder_core.model.edges import edge_data
from graph_builder_core.model.palette import colormap_1


FIELDS = {
    'vertex': ('fill', 'outline', 'shape', 'size', 'outline_width', 'text',
               'tikz_options'),
    'edge': ('stroke', 'width', 'pattern', 'opacity', 'label_t',
             'label_offset', 'arrow_shape', 'arrow_length', 'arrow_width',
             'tikz_options'),
}

DEFAULT_PRESET_ID = '__default_style__'


def _read(value):
    if isinstance(value, dict):
        result = deepcopy(value)
        result.pop('latex_label', None)
        return result
    try:
        result = json.loads(value or '{}')
        if isinstance(result, dict):
            result.pop('latex_label', None)
            return result
        return {}
    except (TypeError, ValueError):
        return {}


def _write(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def base_style(kind, color_index):
    color = '#%02x%02x%02x' % colormap_1(color_index)
    if kind == 'vertex':
        if int(color_index) == 0:
            return dict(fill='#ffffff', outline='#000000', shape='circle', size=34.0,
                        outline_width=2.0, text='auto',
                        tikz_options='')
        return dict(fill=color, outline='#222222', shape='circle', size=34.0,
                    outline_width=1.5, text='auto',
                    tikz_options='')
    return dict(stroke=color, width=2.6, pattern='solid', opacity=1.0,
                label_t=.5, label_offset=0.0, arrow_shape='triangle',
                arrow_length=11.0, arrow_width=10.0,
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
    stored = _read(graph.graph.get(f'{kind}_presets'))
    stored.pop(DEFAULT_PRESET_ID, None)
    return {DEFAULT_PRESET_ID: {'name': 'Default style', 'style': {}}} | stored


def effective_style(graph, kind, attributes):
    style = base_style(kind, attributes.get('style', 0))
    style.update(palette_styles(graph, kind).get(str(attributes.get('style', 0)), {}))
    preset = attributes.get('style_preset')
    if preset:
        style.update(presets(graph, kind).get(preset, {}).get('style', {}))
    style.update(_read(attributes.get('style_overrides')))
    return style


def has_custom_look(attributes):
    """Whether an object's own style can override its basic style's appearance."""
    preset = attributes.get('style_preset')
    return bool(_read(attributes.get('style_overrides'))) or bool(
        preset and preset != DEFAULT_PRESET_ID)


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


def reset_palette_style(graph, kind, index):
    """Remove a basic style's shared customization and restore its built-in look."""
    values = palette_styles(graph, kind)
    values.pop(str(index), None)
    if values:
        graph.graph[f'{kind}_styles'] = _write(values)
    else:
        graph.graph.pop(f'{kind}_styles', None)


def set_preset(graph, kind, identifier, name, style):
    if identifier == DEFAULT_PRESET_ID:
        raise ValueError('The built-in Default style cannot be edited')
    values = _read(graph.graph.get(f'{kind}_presets'))
    values[identifier] = {'name': name,
                          'style': {key: value for key, value in style.items()
                                    if key in FIELDS[kind]}}
    graph.graph[f'{kind}_presets'] = _write(values)


def remove_preset(graph, kind, identifier):
    """Freeze the effective appearance of linked objects before removing it."""
    if identifier == DEFAULT_PRESET_ID:
        return
    values = _read(graph.graph.get(f'{kind}_presets'))
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


def use_basic_style(attributes, index):
    """Assign a shared style, discarding object-specific appearance only.

    Labels and unrelated attributes are intentionally left alone.
    """
    attributes['style'] = int(index)
    attributes.pop('style_overrides', None)
    attributes.pop('style_preset', None)


def basic_index_for_appearance(graph, kind, appearance):
    """Find or append an inherited style matching an effective appearance."""
    count_key = 'num_vertex_styles' if kind == 'vertex' else 'num_edge_styles'
    count = max(1, int(graph.graph.get(count_key, 1)))
    for index in range(count):
        if effective_style(graph, kind, {'style': index}) == appearance:
            return index
    set_palette_style(graph, kind, count, appearance)
    graph.graph[count_key] = count + 1
    return count


def set_edge_style(graph, source, target, changes, preset=None, key=None):
    """Keep the two arcs of a logical undirected edge synchronized."""
    pairs = [(source, target)]
    if graph.graph.get('graph_type') == 'graph' and graph.has_edge(target, source):
        pairs.append((target, source))
    for pair in pairs:
        attributes = edge_data(graph, *pair, key)
        set_overrides(attributes, changes)
        if preset is not None:
            if preset:
                attributes['style_preset'] = preset
            else:
                attributes.pop('style_preset', None)
