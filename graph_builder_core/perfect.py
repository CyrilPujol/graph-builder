"""Conservative perfect-graph recognition for the Metrics panel."""
from __future__ import annotations

from itertools import combinations

import networkx as nx


def _odd_hole(graph):
    nodes = list(graph)
    for size in range(5, len(nodes) + 1, 2):
        for subset in combinations(nodes, size):
            selected = set(subset)
            if all(len(selected.intersection(graph[node])) == 2 for node in subset):
                induced = graph.subgraph(subset)
                if nx.is_connected(induced):
                    return True
    return False


def perfect_status(graph):
    """Return Yes, No, or Unknown without making unproved claims.

    For small graphs the Strong Perfect Graph Theorem gives an exact check:
    no induced odd hole in either the graph or its complement.
    """
    simple = nx.Graph(graph)
    simple.remove_edges_from(nx.selfloop_edges(simple))
    complement = nx.complement(simple)
    if len(simple) <= 16:
        return 'No' if _odd_hole(simple) or _odd_hole(complement) else 'Yes'
    if (nx.is_bipartite(simple) or nx.is_bipartite(complement) or
            nx.is_chordal(simple) or nx.is_chordal(complement)):
        return 'Yes'
    return 'Unknown (exact check limited to 16 vertices)'
