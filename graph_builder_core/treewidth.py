"""Small-graph tree-width bounds, certificates, and decomposition drawings."""
from __future__ import annotations

import time

import networkx as nx


def _simple(graph):
    simple = nx.Graph(graph)
    simple.remove_edges_from(nx.selfloop_edges(simple))
    return simple


def _lower_bound(graph):
    return max(nx.core_number(graph).values(), default=0) if graph.number_of_edges() else 0


def quick_bounds(graph):
    """Return a certified lower bound and a decomposition upper bound."""
    simple = _simple(graph)
    if not simple:
        return 0, 0, nx.Graph()
    width, decomposition = nx.approximation.treewidth_min_fill_in(simple)
    return _lower_bound(simple), max(0, width), decomposition


def _elimination_decomposition(nodes, edges, order):
    adjacency = {node: set() for node in nodes}
    for u, v in edges:
        adjacency[u].add(v)
        adjacency[v].add(u)
    bags = []
    for vertex in order:
        neighbors = adjacency[vertex].copy()
        bags.append(frozenset(neighbors | {vertex}))
        for neighbor in neighbors:
            adjacency[neighbor].update(neighbors - {neighbor})
            adjacency[neighbor].discard(vertex)
        del adjacency[vertex]
    index = {vertex: position for position, vertex in enumerate(order)}
    tree = nx.Graph()
    tree.add_nodes_from(range(len(bags)))
    roots = []
    for position, vertex in enumerate(order):
        later = bags[position] - {vertex}
        if later:
            tree.add_edge(position, min(index[node] for node in later))
        else:
            roots.append(position)
    for first, second in zip(roots, roots[1:]):
        tree.add_edge(first, second)
    return nx.relabel_nodes(tree, {index: bags[index] for index in tree})


def solve(graph, seconds=60):
    """Search elimination orders, keeping rigorous bounds on timeout."""
    from .optimization import OptimizationResult

    started = time.monotonic()
    simple = _simple(graph)
    lower, upper, decomposition = quick_bounds(simple)
    if not simple:
        return OptimizationResult('Tree-width tw', 0, 0, {}, True,
                                  time.monotonic() - started)
    if lower == upper:
        return OptimizationResult('Tree-width tw', lower, upper,
                                  witness_payload(decomposition), True,
                                  time.monotonic() - started)
    nodes = list(simple)
    if len(nodes) > 32:
        return OptimizationResult('Tree-width tw', lower, upper,
                                  witness_payload(decomposition), False,
                                  time.monotonic() - started,
                                  'Exact search is limited to 32 vertices')
    deadline = started + max(0.01, seconds - 0.5)
    initial = {node: frozenset(simple[node]) for node in nodes}
    best_lower = lower
    best_order = None

    def search(adjacency, limit, failed):
        if time.monotonic() >= deadline:
            raise TimeoutError
        if not adjacency:
            return []
        key = frozenset((node, neighbors) for node, neighbors in adjacency.items())
        if key in failed:
            return None
        candidates = [node for node, neighbors in adjacency.items() if len(neighbors) <= limit]
        candidates.sort(key=lambda node: (sum(b not in adjacency[a]
                         for a in adjacency[node] for b in adjacency[node] if str(a) < str(b)),
                         len(adjacency[node]), str(node)))
        for node in candidates:
            neighbors = adjacency[node]
            reduced = {other: set(near) - {node} for other, near in adjacency.items() if other != node}
            for other in neighbors:
                reduced[other].update(neighbors - {other})
            tail = search({other: frozenset(near) for other, near in reduced.items()}, limit, failed)
            if tail is not None:
                return [node] + tail
        failed.add(key)
        return None

    try:
        for limit in range(lower, upper):
            order = search(initial, limit, set())
            if order is not None:
                upper = limit
                best_order = order
                break
            best_lower = limit + 1
    except TimeoutError:
        pass
    if best_order is not None:
        decomposition = _elimination_decomposition(nodes, simple.edges(), best_order)
    return OptimizationResult('Tree-width tw', best_lower, upper,
                              witness_payload(decomposition), best_lower == upper,
                              time.monotonic() - started,
                              'Time-limited search' if best_lower != upper else '')


def _bag_name(index):
    result = ''
    index += 1
    while index:
        index, digit = divmod(index - 1, 26)
        result = chr(65 + digit) + result
    return result


def witness_payload(decomposition):
    bags = sorted(decomposition, key=lambda bag: (len(bag), tuple(sorted(map(str, bag)))))
    index = {bag: i for i, bag in enumerate(bags)}
    return {'bags': [{'name': _bag_name(i), 'vertices': list(bag)}
                     for i, bag in enumerate(bags)],
            'edges': [[index[u], index[v]] for u, v in decomposition.edges()]}
