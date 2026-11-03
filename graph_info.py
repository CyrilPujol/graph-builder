"""Read-only graph information for the Qt editor.

The functions accept ordinary NetworkX Graph/DiGraph instances. The command
line worker receives only topology, so expensive analysis can be stopped
without ever changing the editor's document.
"""
from __future__ import annotations

import json
import random
import sys

import networkx as nx


ANALYSIS_TIMEOUT_MS = 2000
EXACT_DISTANCE_LIMIT = 120
DISTANCE_SAMPLE_SIZE = 24


def _line(label, value):
    return f'{label}: {value}'


def _components(graph):
    if graph.is_directed():
        return nx.number_weakly_connected_components(graph), nx.number_strongly_connected_components(graph)
    return nx.number_connected_components(graph), None


def _overview(graph):
    n, m = graph.number_of_nodes(), graph.number_of_edges()
    weak, strong = _components(graph) if n else (0, 0 if graph.is_directed() else None)
    lines = [_line('Vertices', n), _line('Arcs' if graph.is_directed() else 'Edges', m),
             _line('Density', f'{nx.density(graph):.3f}' if n > 1 else '—')]
    if graph.is_directed():
        lines.extend((_line('Weak components', weak), _line('Strong components', strong)))
        families = (('In-degree', dict(graph.in_degree()).values()),
                    ('Out-degree', dict(graph.out_degree()).values()))
    else:
        lines.append(_line('Components', weak))
        families = (('Degree', dict(graph.degree()).values()),)
    for title, degrees in families:
        values = list(degrees)
        if values:
            lines.append(_line(title + ' min / avg / max',
                               f'{min(values)} / {sum(values) / len(values):.3f} / {max(values)}'))
        else:
            lines.append(_line(title + ' min / avg / max', '—'))
    return lines


def _structure(graph):
    if not graph:
        return ['Structure: — (empty graph)']
    simple = graph.to_undirected() if graph.is_directed() else graph
    if graph.is_directed():
        weak = [len(component) for component in nx.weakly_connected_components(graph)]
        strong = [len(component) for component in nx.strongly_connected_components(graph)]
        lines = [_line('Weak components', f'{len(weak)} (largest: {max(weak)})'),
                 _line('Strong components', f'{len(strong)} (largest: {max(strong)})')]
    else:
        sizes = [len(component) for component in nx.connected_components(graph)]
        lines = [_line('Components', f'{len(sizes)} (largest: {max(sizes)})')]
    lines.extend([_line('Bipartite', 'Yes' if nx.is_bipartite(simple) else 'No'),
             _line('Planar', 'Yes' if nx.is_planar(simple) else 'No'),
             _line('Tree', 'Yes' if nx.is_tree(simple) else 'No'),
             _line('Forest', 'Yes' if nx.is_forest(simple) else 'No'),
             _line('Eulerian', 'Yes' if nx.is_eulerian(graph) else 'No')])
    n = len(simple)
    if n <= 200:
        lines.append(_line('Average clustering', f'{nx.average_clustering(simple):.3f}'))
    else:
        estimate = nx.algorithms.approximation.average_clustering(simple, trials=128, seed=0)
        lines.append(_line('Average clustering', f'≈ {estimate:.3f} (128 samples)'))
    if graph.is_directed():
        lines.append('Bipartite, planar, tree, forest and clustering ignore arrow directions.')
    return lines


def _distances(graph):
    n = len(graph)
    if not n:
        return ['Diameter: — (empty graph)', 'Radius: —', 'Mean shortest-path length: —']
    if n == 1:
        return ['Diameter: 0', 'Radius: 0', 'Mean shortest-path length: 0.000']
    connected = nx.is_strongly_connected(graph) if graph.is_directed() else nx.is_connected(graph)
    if not connected:
        reason = 'not strongly connected' if graph.is_directed() else 'disconnected'
        return [f'Diameter: ∞ ({reason})', 'Radius: ∞', 'Mean shortest-path length: ∞']
    if n <= EXACT_DISTANCE_LIMIT:
        eccentricities = nx.eccentricity(graph)
        return [_line('Diameter', max(eccentricities.values())),
                _line('Radius', min(eccentricities.values())),
                _line('Mean shortest-path length', f'{nx.average_shortest_path_length(graph):.3f}')]
    sources = random.Random(0).sample(list(graph), min(DISTANCE_SAMPLE_SIZE, n))
    lengths = {source: nx.single_source_shortest_path_length(graph, source)
               for source in sources}
    eccentricities = {source: max(distances.values()) for source, distances in lengths.items()}
    totals = [sum(distances.values()) / (n - 1) for distances in lengths.values()]
    diameter_bound = max(eccentricities.values())
    if not graph.is_directed():
        diameter_bound = max(diameter_bound, nx.algorithms.approximation.diameter(graph, seed=0))
    return [_line('Diameter', f'≥ {diameter_bound} (lower bound)'),
            _line('Radius', f'≤ {min(eccentricities.values())} (upper bound)'),
            _line('Mean shortest-path length',
                  f'≈ {sum(totals) / len(totals):.3f} ({len(sources)} sampled sources)')]


def _greedy_clique(graph):
    """Build several actual cliques; their sizes are certified lower bounds."""
    neighbors = {node: set(graph.neighbors(node)) for node in graph}
    degree_order = sorted(graph, key=lambda node: (-len(neighbors[node]), str(node)))
    best = set()
    for start in degree_order[:min(len(degree_order), 12)]:
        clique = {start}
        candidates = neighbors[start].copy()
        while candidates:
            chosen = max(candidates, key=lambda node: (len(candidates & neighbors[node]), len(neighbors[node])))
            clique.add(chosen)
            candidates.intersection_update(neighbors[chosen])
        if len(clique) > len(best):
            best = clique
    return best


def _greedy_independent_set(graph):
    neighbors = {node: set(graph.neighbors(node)) for node in graph}
    remaining = set(graph)
    chosen = set()
    while remaining:
        node = min(remaining, key=lambda candidate: (len(remaining & neighbors[candidate]), str(candidate)))
        chosen.add(node)
        remaining.discard(node)
        remaining.difference_update(neighbors[node])
    return chosen


def _bounds(graph):
    simple = graph.to_undirected() if graph.is_directed() else graph
    if not simple:
        return ['Clique number ω: 0', 'Independence number α: 0', 'Chromatic number: 0 ≤ χ ≤ 0']
    clique = _greedy_clique(simple)
    independent = _greedy_independent_set(simple)
    colorings = [nx.coloring.greedy_color(simple, strategy='largest_first')]
    if len(simple) <= 500:
        colorings.append(nx.coloring.greedy_color(simple, strategy='DSATUR'))
    colors_used = min(max(colors.values(), default=-1) + 1 for colors in colorings)
    lines = [_line('Clique number ω', f'≥ {len(clique)} (clique found)'),
             _line('Independence number α', f'≥ {len(independent)} (independent set found)'),
             _line('Chromatic number', f'{len(clique)} ≤ χ ≤ {colors_used}')]
    if graph.is_directed():
        lines.append('Bounds ignore arrow directions.')
    return lines


ANALYSES = {'Overview': _overview, 'Structure': _structure,
            'Distances': _distances, 'Bounds': _bounds}


def analyze(graph, kind):
    """Compute one view as plain text lines, leaving graph and settings intact."""
    if kind not in ANALYSES:
        raise ValueError(f'Unknown graph information view: {kind}')
    return ANALYSES[kind](graph)


def topology_payload(graph):
    """Keep worker messages small and independent of user attributes."""
    return {'directed': graph.is_directed(), 'nodes': list(graph),
            'edges': [list(edge) for edge in graph.edges]}


def graph_from_payload(payload):
    graph = nx.DiGraph() if payload['directed'] else nx.Graph()
    graph.add_nodes_from(payload['nodes'])
    graph.add_edges_from(payload['edges'])
    return graph


def _worker():
    kind = sys.argv[2]
    graph = graph_from_payload(json.load(sys.stdin))
    json.dump(analyze(graph, kind), sys.stdout)


if __name__ == '__main__' and len(sys.argv) == 3 and sys.argv[1] == '--worker':
    _worker()
