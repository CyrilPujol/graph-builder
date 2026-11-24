"""Conservative perfect-graph recognition for the Properties panel."""
from __future__ import annotations

from itertools import combinations
from time import monotonic

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


def perfect_exact_status(graph, seconds=60):
    """Use CP-SAT to exclude every induced odd hole and antihole.

    The first found witness proves non-perfection. Exhausting all odd lengths
    in both the graph and its complement proves perfection. A timeout makes
    no claim.
    """
    from graph_builder_core.algorithms.optimization import _solver

    quick = perfect_status(graph)
    if quick in ('Yes', 'No'):
        return quick
    simple = nx.Graph(graph)
    simple.remove_edges_from(nx.selfloop_edges(simple))
    nodes = list(simple)
    positions = {node: index for index, node in enumerate(nodes)}
    deadline = monotonic() + seconds
    for candidate in (simple, nx.complement(simple)):
        edges = {(positions[u], positions[v]) for u, v in candidate.edges()}
        edges |= {(v, u) for u, v in edges}
        adjacent = [(u, v) for u, v in edges if u != v]
        nonadjacent = [(u, v) for u in range(len(nodes)) for v in range(len(nodes))
                       if u != v and (u, v) not in edges]
        for size in range(5, len(nodes) + 1, 2):
            remaining = deadline - monotonic()
            if remaining <= 0:
                return 'Unknown (time limit)'
            # Each table is copied into the CP-SAT model. Keep a hard memory
            # ceiling for larger graphs rather than risking an app crash.
            pairs = size * (size - 1) // 2
            if pairs * max(len(adjacent), len(nonadjacent)) > 1_000_000:
                return 'Unknown (size limit)'
            cp_model, solver = _solver(remaining, 4)
            model = cp_model.CpModel()
            cycle = [model.NewIntVar(0, len(nodes) - 1, f'v{i}') for i in range(size)]
            model.AddAllDifferent(cycle)
            for i in range(size):
                for j in range(i + 1, size):
                    allowed = adjacent if j == i + 1 or (i == 0 and j == size - 1) else nonadjacent
                    model.AddAllowedAssignments((cycle[i], cycle[j]), allowed)
            status = solver.Solve(model)
            if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                return 'No'
            if status != cp_model.INFEASIBLE:
                return 'Unknown (time limit)'
    return 'Yes'
