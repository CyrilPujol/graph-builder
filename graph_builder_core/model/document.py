"""Document defaults, labels and history snapshots.

Internal documents use string IDs and paired arcs for undirected edges.
The public Python API converts vertex IDs to integers in extensions.py.
"""
from __future__ import annotations

import networkx as nx
from networkx.readwrite import json_graph

from graph_builder_core.model.edges import edge_data, visible_edges, has_edge


DEFAULT_GRAPH_OPTIONS = {
    'graph_type': 'graph', 'num_edge_styles': 2,
    'num_vertex_styles': 4, 'show_labels': True,
    'loops': False, 'multiedges': False,
}


def canonical_graph_options(options):
    """Accept older style-count names without keeping them in new documents."""
    values = dict(options)
    for old, new in (('num_vertex_colors', 'num_vertex_styles'),
                     ('num_edge_colors', 'num_edge_styles')):
        legacy = values.pop(old, None)
        if legacy is not None and new not in values:
            values[new] = legacy
    return values


def empty_graph(**options):
    options = canonical_graph_options(options)
    graph = nx.MultiDiGraph() if options.get('multiedges') else nx.DiGraph()
    graph.graph.update(DEFAULT_GRAPH_OPTIONS)
    graph.graph.update(options)
    return graph


def unused_label(graph):
    """Choose a new stable internal ID; visible labels may be duplicated."""
    index = 0
    while str(index) in graph:
        index += 1
    return str(index)


def vertex_label(graph, node):
    return str(graph.nodes[node].get('label', node))


def edge_label(graph, source, target, key=None):
    return str(edge_data(graph, source, target, key).get('label', ''))


def labels_visible(graph):
    return graph.graph.get('show_labels', graph.graph.get('show_vertex_labels', True))


def logical_edges(graph):
    """Yield each visible edge once, including every directed arc."""
    for source, target, _, _ in visible_edges(graph):
        yield source, target


def set_edge_label(graph, source, target, label, key=None):
    edge_data(graph, source, target, key)['label'] = label
    if graph.graph.get('graph_type') == 'graph' and has_edge(graph, target, source, key):
        edge_data(graph, target, source, key)['label'] = label


def _serialize_graph(graph):
    return json_graph.node_link_data(graph)


def _deserialize_graph(data):
    return json_graph.node_link_graph(data)
