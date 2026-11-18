"""Bounded undirected graph-minor search with connected branch-set witnesses."""
from __future__ import annotations

import networkx as nx
from .styles import basic_index_for_appearance, effective_style, use_basic_style


MAX_HOST_VERTICES = 45
MAX_PATTERN_VERTICES = 16


def find_minor(graph, host_nodes, pattern_nodes, seconds=60, workers=4):
    """Find a minor of the underlying simple graphs.

    Arrows, parallel copies, and loops are ignored, as is conventional for
    the undirected minor relation. A result maps each pattern vertex to its
    connected, pairwise disjoint branch set in the host.
    """
    from .optimization import _solver

    host_nodes, pattern_nodes = set(host_nodes), set(pattern_nodes)
    if not host_nodes or not pattern_nodes or not host_nodes <= set(graph) or not pattern_nodes <= set(graph):
        raise ValueError('Select nonempty vertex sets that exist in the graph.')
    if len(host_nodes) > MAX_HOST_VERTICES or len(pattern_nodes) > MAX_PATTERN_VERTICES:
        raise ValueError(f'Minor search is limited to {MAX_HOST_VERTICES} host and '
                         f'{MAX_PATTERN_VERTICES} pattern vertices.')
    if len(pattern_nodes) > len(host_nodes):
        return {'status': 'none', 'branch_sets': []}
    simple = nx.Graph(graph)
    simple.remove_edges_from(nx.selfloop_edges(simple))
    host = simple.subgraph(host_nodes)
    pattern = simple.subgraph(pattern_nodes)
    host_vertices = sorted(host, key=str)
    pattern_vertices = sorted(pattern, key=str)
    n = len(host_vertices)
    if pattern.number_of_edges() > host.number_of_edges():
        # Contraction can only remove or merge edges, never create one.
        return {'status': 'none', 'branch_sets': []}
    cp_model, solver = _solver(seconds, workers)
    model = cp_model.CpModel()
    member = {(v, b): model.new_bool_var(f'bag_{v}_{b}')
              for v in range(n) for b in range(len(pattern_vertices))}
    root = {(v, b): model.new_bool_var(f'root_{v}_{b}')
            for v in range(n) for b in range(len(pattern_vertices))}
    for v in range(n):
        model.add(sum(member[v, b] for b in range(len(pattern_vertices))) <= 1)
    oriented_edges = [(host_vertices.index(u), host_vertices.index(v))
                      for u, v in host.edges()]
    oriented_edges += [(v, u) for u, v in oriented_edges]
    for b in range(len(pattern_vertices)):
        model.add(sum(root[v, b] for v in range(n)) == 1)
        size = model.new_int_var(1, n, f'bag_size_{b}')
        model.add(size == sum(member[v, b] for v in range(n)))
        supply = {}
        for v in range(n):
            model.add(root[v, b] <= member[v, b])
            supply[v] = model.new_int_var(0, n, f'supply_{v}_{b}')
            model.add_multiplication_equality(supply[v], [root[v, b], size])
        flow = {}
        for u, v in oriented_edges:
            amount = model.new_int_var(0, n - 1, f'flow_{u}_{v}_{b}')
            model.add(amount <= (n - 1) * member[u, b])
            model.add(amount <= (n - 1) * member[v, b])
            flow[u, v] = amount
        for v in range(n):
            incoming = sum(flow[u, v] for u, w in oriented_edges if w == v)
            outgoing = sum(flow[v, w] for u, w in oriented_edges if u == v)
            model.add(incoming - outgoing == member[v, b] - supply[v])
    index = {vertex: b for b, vertex in enumerate(pattern_vertices)}
    for first, second in pattern.edges():
        a, b = index[first], index[second]
        witnesses = []
        for u, v in oriented_edges:
            witness = model.new_bool_var(f'join_{a}_{b}_{u}_{v}')
            model.add(witness <= member[u, a])
            model.add(witness <= member[v, b])
            witnesses.append(witness)
        if not witnesses:
            return {'status': 'none', 'branch_sets': []}
        model.add(sum(witnesses) >= 1)
    status = solver.solve(model)
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {'status': 'found', 'branch_sets': [
            [pattern_vertices[b], [host_vertices[v] for v in range(n)
                                   if solver.value(member[v, b])]]
            for b in range(len(pattern_vertices))]}
    return {'status': 'none' if status == cp_model.INFEASIBLE else 'timeout',
            'branch_sets': []}


def lift_minor_styles(graph, host_nodes, pattern_nodes, branch_sets):
    """Show the contraction witness with inherited basic styles only."""
    host_nodes, pattern_nodes = set(host_nodes), set(pattern_nodes)
    branch_sets = {target: set(nodes) for target, nodes in branch_sets}
    if (set(branch_sets) != pattern_nodes or not pattern_nodes <= set(graph)
            or any(not bag for bag in branch_sets.values())):
        raise ValueError('The minor witness no longer matches the pattern.')
    covered = set().union(*branch_sets.values())
    if covered - host_nodes or sum(map(len, branch_sets.values())) != len(covered):
        raise ValueError('The minor witness no longer matches the host.')
    simple = nx.Graph(graph)
    simple.remove_edges_from(nx.selfloop_edges(simple))
    if any(not nx.is_connected(simple.subgraph(bag)) for bag in branch_sets.values()):
        raise ValueError('The minor witness has a disconnected branch set.')
    for first, second in simple.subgraph(pattern_nodes).edges():
        if not any(simple.has_edge(u, v) for u in branch_sets[first]
                   for v in branch_sets[second]):
            raise ValueError('The minor witness is missing an edge between branch sets.')
    looks = [effective_style(graph, 'vertex', graph.nodes[node]) for node in pattern_nodes]
    uniform = all(look == looks[0] for look in looks[1:])
    if uniform:
        for index, node in enumerate(sorted(pattern_nodes, key=str), 1):
            use_basic_style(graph.nodes[node], index)
    colors = {
        node: (int(graph.nodes[node].get('col', 0)) if uniform else
               basic_index_for_appearance(graph, 'vertex',
                                          effective_style(graph, 'vertex', graph.nodes[node])))
        for node in pattern_nodes
    }
    inverse = {node: target for target, bag in branch_sets.items() for node in bag}
    for node in host_nodes:
        use_basic_style(graph.nodes[node], colors[inverse[node]] if node in inverse else 0)
    graph.graph['num_vertex_colors'] = max(
        int(graph.graph.get('num_vertex_colors', 1)), max(colors.values(), default=0) + 1)
    return uniform
