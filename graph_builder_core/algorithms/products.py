"""Products of two selected induced graphs, independent of the editor UI."""
from __future__ import annotations

import networkx as nx

from graph_builder_core.algorithms.generators import GeneratedGraph
from graph_builder_core.model.document import vertex_label
from graph_builder_core.model.edges import visible_edges


PRODUCTS = {
    'tensor': ('Tensor', nx.tensor_product),
    'cartesian': ('Cartesian', nx.cartesian_product),
    'lexicographic': ('Lexicographic', nx.lexicographic_product),
}
MAX_PRODUCT_VERTICES = 300
MAX_PRODUCT_EDGES = 6000


def _factor(graph, nodes):
    directed = graph.graph.get('graph_type') != 'graph'
    factor = (nx.MultiDiGraph() if directed else nx.MultiGraph()) if graph.is_multigraph() else (
        nx.DiGraph() if directed else nx.Graph())
    factor.add_nodes_from(nodes)
    for source, target, _, _ in visible_edges(graph):
        if source in factor and target in factor:
            factor.add_edge(source, target)
    return factor


def _positions(graph, first, second):
    """Use the Minkowski-sum drawing before viewport centering and scaling."""
    a = {node: graph.nodes[node].get('position', (0, 0)) for node in first}
    b = {node: graph.nodes[node].get('position', (0, 0)) for node in second}
    return {(u, v): (a[u][0] + b[v][0], a[u][1] + b[v][1])
            for u in first for v in second}


def generate_product(graph, first_nodes, second_nodes, kind):
    """Return a positioned product, with a size guard before insertion."""
    if kind not in PRODUCTS:
        raise ValueError(f'Unknown graph product: {kind}')
    first_set, second_set = set(first_nodes), set(second_nodes)
    first = [node for node in graph if node in first_set]
    second = [node for node in graph if node in second_set]
    if not first or not second:
        raise ValueError('Select at least one vertex for each factor.')
    if len(first) * len(second) > MAX_PRODUCT_VERTICES:
        raise ValueError(f'This product would have over {MAX_PRODUCT_VERTICES} vertices.')
    first_graph, second_graph = _factor(graph, first), _factor(graph, second)
    first_edges, second_edges = first_graph.number_of_edges(), second_graph.number_of_edges()
    directed = first_graph.is_directed()
    if kind == 'tensor':
        estimate = first_edges * second_edges * (1 if directed else 2)
    elif kind == 'cartesian':
        estimate = first_edges * len(second) + second_edges * len(first)
    else:
        estimate = first_edges * len(second)**2 + second_edges * len(first)
    if estimate > MAX_PRODUCT_EDGES:
        raise ValueError(f'This product would have over {MAX_PRODUCT_EDGES} edges.')
    result = PRODUCTS[kind][1](first_graph, second_graph)
    if result.number_of_edges() > MAX_PRODUCT_EDGES:
        raise ValueError(f'This product would have over {MAX_PRODUCT_EDGES} edges.')
    positions = _positions(graph, first, second)
    labels = {(u, v): f'{vertex_label(graph, u)},{vertex_label(graph, v)}'
              for u, v in result}
    return GeneratedGraph(result, positions, labels)
