"""Subgraph witnesses between two selected induced graphs."""
from __future__ import annotations

import networkx as nx

from graph_builder_core.algorithms.morphism import lift_morphism_styles


MAX_PATTERN_VERTICES = 60
MAX_HOST_VERTICES = 180


def find_subgraph(graph, host_nodes, pattern_nodes, *, induced=False):
    """Find an injective mapping from the pattern to the host.

    Both vertex sets induce graphs. Arcs, loops and parallel-edge counts are
    respected. ``induced`` also forbids extra host edges among matched nodes.
    Run this in a cancellable worker for large searches.
    """
    host_nodes, pattern_nodes = set(host_nodes), set(pattern_nodes)
    if not host_nodes or not pattern_nodes or not host_nodes <= set(graph) or not pattern_nodes <= set(graph):
        raise ValueError('Select nonempty vertex sets that exist in the graph.')
    if len(pattern_nodes) > MAX_PATTERN_VERTICES or len(host_nodes) > MAX_HOST_VERTICES:
        raise ValueError(f'Subgraph search is limited to {MAX_HOST_VERTICES} host vertices '
                         f'and {MAX_PATTERN_VERTICES} pattern vertices.')
    if len(pattern_nodes) > len(host_nodes):
        return {'status': 'none', 'mapping': []}
    host = graph.subgraph(host_nodes).copy()
    pattern = graph.subgraph(pattern_nodes).copy()
    matchers = {nx.Graph: nx.algorithms.isomorphism.GraphMatcher,
                nx.DiGraph: nx.algorithms.isomorphism.DiGraphMatcher,
                nx.MultiGraph: nx.algorithms.isomorphism.MultiGraphMatcher,
                nx.MultiDiGraph: nx.algorithms.isomorphism.MultiDiGraphMatcher}
    matcher_type = matchers[type(graph)]
    matcher = matcher_type(host, pattern)
    witnesses = (matcher.subgraph_isomorphisms_iter() if induced else
                 matcher.subgraph_monomorphisms_iter())
    mapping = next(witnesses, None)
    return {'status': 'found', 'mapping': list(mapping.items())} if mapping is not None else {
        'status': 'none', 'mapping': []}


def lift_subgraph_styles(graph, host_nodes, pattern_nodes, mapping, *, induced=False):
    """Color a found host copy using the pattern's basic styles."""
    host_nodes, pattern_nodes = set(host_nodes), set(pattern_nodes)
    mapping = dict(mapping)
    if (not set(mapping) <= host_nodes or len(mapping) != len(pattern_nodes)
            or set(mapping.values()) != pattern_nodes):
        raise ValueError('The subgraph witness no longer matches the selected vertices.')
    return lift_morphism_styles(graph, set(mapping), pattern_nodes, mapping,
                                allow_extra_edges=True, highlight_uncolored=True,
                                highlight_uncolored_edges=not induced)
