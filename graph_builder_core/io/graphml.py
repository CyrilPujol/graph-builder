"""Graphml support for Graph Builder."""
from __future__ import annotations

import copy
from pathlib import Path

import networkx as nx

from graph_builder_core.geometry.curves import _edge_curve_points, _set_edge_curve_points
from graph_builder_core.model.document import DEFAULT_GRAPH_OPTIONS, canonical_graph_options, empty_graph
from graph_builder_core.model.edges import edge_records, add_edge, has_edge


def convert_position(graph):
    """Create a GraphML-safe graph with x/y attributes and graph settings."""
    output = nx.MultiDiGraph() if graph.is_multigraph() else nx.DiGraph()
    output.graph.update(copy.deepcopy(canonical_graph_options(graph.graph)))
    for node, data in graph.nodes(data=True):
        attributes = copy.deepcopy(data)
        if 'position' in attributes:
            x, y = attributes.pop('position')
            attributes.update(position_x=float(x), position_y=float(y))
        output.add_node(str(node), **attributes)
    for index, (source, target, key, data) in enumerate(edge_records(graph)):
        attributes = copy.deepcopy(data)
        if graph.is_multigraph():
            # GraphML edge IDs are document-wide, while an undirected logical
            # edge uses the same key for its two stored arcs.
            attributes['graph_builder_edge_key'] = (
                f'int:{key}' if type(key) is int else f'str:{key}')
            add_edge(output, str(source), str(target), attributes, f'edge-{index}')
        else:
            add_edge(output, str(source), str(target), attributes)
    from graph_builder_core.model.regions import remap_regions
    remap_regions(output, {node: str(node) for node in graph})
    return output


def convert_from_file(graph_file, kwargs=None, *, graph_index=0):
    """Read GraphML or a graph6-family file. graph_index selects a compact record."""
    options = dict(DEFAULT_GRAPH_OPTIONS)
    if kwargs:
        options.update(canonical_graph_options(kwargs))
    if not Path(graph_file).exists():
        return empty_graph(**options)
    from graph_builder_core.io.compact_graphs import COMPACT_SUFFIXES, editor_graph, read_compact_graphs
    if Path(graph_file).suffix.lower() in COMPACT_SUFFIXES:
        return editor_graph(read_compact_graphs(graph_file)[graph_index], options)
    loaded = nx.read_graphml(graph_file)
    def enabled(value):
        return value is True or str(value).strip().lower() in ('true', '1', 'yes')

    graph = (nx.MultiDiGraph() if loaded.is_multigraph() or
             enabled(loaded.graph.get('multiedges')) else nx.DiGraph())
    graph.graph.update(options)
    graph.graph.update(canonical_graph_options(loaded.graph))
    graph.graph['multiedges'] = graph.is_multigraph()
    graph.graph['loops'] = (enabled(graph.graph.get('loops')) or
                            bool(nx.number_of_selfloops(loaded)))
    if 'show_labels' not in loaded.graph and 'show_vertex_labels' in loaded.graph:
        graph.graph['show_labels'] = str(loaded.graph['show_vertex_labels']).lower() != 'false'
    else:
        graph.graph['show_labels'] = str(graph.graph['show_labels']).lower() != 'false'
    for key in ('num_edge_styles', 'num_vertex_styles'):
        graph.graph[key] = max(1, int(graph.graph[key]))
    for node, data in loaded.nodes(data=True):
        attributes = dict(data)
        x = float(attributes.pop('position_x', 0))
        y = float(attributes.pop('position_y', 0))
        attributes['position'] = (x, y)
        attributes['style'] = int(attributes.pop('style', attributes.pop('col', 0)))
        graph.add_node(str(node), **attributes)
    for source, target, key, data in edge_records(loaded):
        attributes = dict(data)
        attributes['style'] = int(attributes.pop('style', attributes.pop('col', 0)))
        if graph.is_multigraph():
            stored_key = attributes.pop('graph_builder_edge_key', None)
            if isinstance(stored_key, str) and stored_key.startswith('int:'):
                key = int(stored_key[4:])
            elif isinstance(stored_key, str) and stored_key.startswith('str:'):
                key = stored_key[4:]
        add_edge(graph, str(source), str(target), attributes, key)
    if graph.graph['graph_type'] == 'graph':
        for source, target, key, data in list(edge_records(graph)):
            if not has_edge(graph, target, source, key):
                add_edge(graph, target, source, data, key)
                points = _edge_curve_points(graph, source, target, key)
                if points:
                    _set_edge_curve_points(graph, source, target, points, key)
    for source, target, key, data in list(edge_records(graph)):
        if data.get('curve_points'):
            _set_edge_curve_points(graph, source, target, _edge_curve_points(graph, source, target, key), key)
    return graph


def write_graph_file(graph, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    nx.write_graphml(convert_position(graph), path)
    return path
