"""Read-only graph information for the Qt editor.

The functions accept ordinary NetworkX Graph/DiGraph instances. The command
line worker receives only topology, so expensive analysis can be stopped
without ever changing the editor's document.
"""
from __future__ import annotations

import json
import random
import sys
from math import ceil, isinf
from pathlib import Path

import networkx as nx


ANALYSIS_TIMEOUT_MS = 2000
OPTIMIZATION_TIMEOUT_MS = 62000
EXACT_DISTANCE_LIMIT = 120
DISTANCE_SAMPLE_SIZE = 24
BOUND_PROBLEMS = ('clique', 'independent', 'chromatic', 'edge_chromatic',
                  'vertex_cover', 'edge_cover', 'matching', 'domination', 'domatic',
                  'treewidth')
BOUND_SYMBOLS = {'clique': 'ω', 'independent': 'α', 'chromatic': 'χ',
                 'edge_chromatic': 'χ′', 'vertex_cover': 'τ',
                 'edge_cover': 'ρ', 'matching': 'ν',
                 'domination': 'γ', 'domatic': 'd', 'treewidth': 'tw'}
DIRECT_BOUNDS = frozenset({'edge_cover', 'matching'})
SHOWABLE_BOUNDS = frozenset(BOUND_PROBLEMS)


def _line(label, value):
    return f'{label}: {value}'


def _bounded_line(name, symbol, lower, upper):
    if lower == upper:
        return _line(f'{name} {symbol}', lower)
    return _line(name, f'{lower} ≤ {symbol} ≤ {upper}')


def _components(graph):
    if graph.is_directed():
        return nx.number_weakly_connected_components(graph), nx.number_strongly_connected_components(graph)
    return nx.number_connected_components(graph), None


def _overview(graph):
    n, m = graph.number_of_nodes(), graph.number_of_edges()
    weak, strong = _components(graph) if n else (0, 0 if graph.is_directed() else None)
    lines = [_line('Vertices', n), _line('Arcs' if graph.is_directed() else 'Edges', m)]
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
            lines.extend((_line('Minimum ' + title.lower(), min(values)),
                          _line('Average ' + title.lower(), f'{sum(values) / len(values):.3f}'),
                          _line('Maximum ' + title.lower(), max(values))))
        else:
            lines.extend(_line(label + ' ' + title.lower(), '—')
                         for label in ('Minimum', 'Average', 'Maximum'))
    if nx.number_of_selfloops(graph):
        girth = 1
    elif (graph.is_multigraph() and not graph.is_directed() and
          graph.number_of_edges() > nx.Graph(graph).number_of_edges()):
        girth = 2
    else:
        girth = nx.girth(nx.Graph(graph))
    lines.append(_line('Girth', '∞' if isinf(girth) else girth))
    lines.extend(_distances(graph))
    return lines


def _structure(graph):
    from .perfect import perfect_status

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
             _line('Perfect', perfect_status(simple)),
             _line('Eulerian', 'Yes' if nx.is_eulerian(graph) else 'No')])
    if graph.is_directed():
        lines.append('Bipartite, planar, tree and forest ignore arrow directions.')
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
    from .optimization import MAX_EDGE_COLOR_EDGES, _dominating_set_greedy, _greedy_clique
    from .treewidth import quick_bounds

    simple = nx.Graph(graph)
    if not simple:
        return ['Clique number ω: 0', 'Independence number α: 0',
                _bounded_line('Chromatic number', 'χ', 0, 0),
                _bounded_line('Edge chromatic number', 'χ′', 0, 0),
                _bounded_line('Minimum vertex cover', 'τ', 0, 0),
                'Minimum edge cover ρ: 0', 'Maximum matching ν: 0',
                _bounded_line('Domination number', 'γ', 0, 0),
                _bounded_line('Domatic number', 'd', 0, 0),
                _bounded_line('Tree-width', 'tw', 0, 0)]
    loop_nodes = {node for node, _ in nx.selfloop_edges(simple)}
    has_loop = bool(loop_nodes)
    if has_loop:
        simple = simple.copy()
        simple.remove_edges_from(nx.selfloop_edges(simple))
    clique = _greedy_clique(simple)
    independent = _greedy_independent_set(simple)
    colorings = [nx.coloring.greedy_color(simple, strategy='largest_first')]
    if len(simple) <= 500:
        colorings.append(nx.coloring.greedy_color(simple, strategy='DSATUR'))
    colors_used = min(max(colors.values(), default=-1) + 1 for colors in colorings)
    multi = nx.MultiGraph()
    multi.add_nodes_from(graph)
    multi.add_edges_from(graph.edges())
    edge_degree = max(dict(multi.degree()).values(), default=0)
    if not multi.number_of_edges():
        edge_colors = 0
    elif multi.number_of_edges() > MAX_EDGE_COLOR_EDGES:
        edge_colors = multi.number_of_edges()
    else:
        line_graph = nx.Graph(nx.line_graph(multi))
        greedy_edges = nx.coloring.greedy_color(line_graph, strategy='DSATUR')
        edge_colors = max(greedy_edges.values(), default=-1) + 1
    maximum_matching = len(nx.max_weight_matching(simple, maxcardinality=True))
    cover_remainder = simple.subgraph(set(simple) - loop_nodes)
    cover_matching = len(nx.max_weight_matching(cover_remainder, maxcardinality=True))
    cover_independent = _greedy_independent_set(cover_remainder)
    cover_lower = len(loop_nodes) + cover_matching
    cover_upper = len(simple) - len(cover_independent)
    try:
        edge_cover_size = len(nx.algorithms.covering.min_edge_cover(nx.Graph(graph)))
    except nx.NetworkXException:
        edge_cover_size = None
    domination_upper = len(_dominating_set_greedy(simple))
    domination_lower = ceil(len(simple) / (max(dict(simple.degree()).values()) + 1))
    domatic_upper = min(dict(simple.degree()).values()) + 1
    tree_lower, tree_upper, _ = quick_bounds(simple)
    lines = [_line('Clique number ω', f'≥ {len(clique)} (clique found)'),
             _line('Independence number α', f'≥ {len(independent)} (independent set found)'),
              ('Chromatic number: no proper coloring exists with a loop' if has_loop else
              _bounded_line('Chromatic number', 'χ', len(clique), colors_used)),
             ('Edge chromatic number: no proper edge coloring exists with a loop'
              if has_loop else
              _bounded_line('Edge chromatic number', 'χ′', edge_degree, edge_colors)),
             _bounded_line('Minimum vertex cover', 'τ', cover_lower, cover_upper),
             _line('Minimum edge cover ρ', edge_cover_size if edge_cover_size is not None
                   else '— (isolated vertex)'),
             _line('Maximum matching ν', maximum_matching),
             _bounded_line('Domination number', 'γ', domination_lower, domination_upper),
             _bounded_line('Domatic number', 'd', 1, domatic_upper),
             _bounded_line('Tree-width', 'tw', tree_lower, tree_upper)]
    if graph.is_directed():
        lines.append('Bounds ignore arrow directions.')
    if graph.is_multigraph():
        lines.append('Parallel edges count separately for edge coloring and once for other bounds.')
    return lines


ANALYSES = {'Overview': _overview, 'Structure': _structure,
            'Distances': _distances, 'Bounds': _bounds}


def analyze(graph, kind):
    """Compute one view as plain text lines, leaving graph and settings intact."""
    if kind not in ANALYSES:
        raise ValueError(f'Unknown graph information view: {kind}')
    if kind == 'Overview':
        return ANALYSES[kind](graph)
    if graph.is_multigraph() and kind not in ('Overview', 'Bounds'):
        simple = nx.DiGraph(graph) if graph.is_directed() else nx.Graph(graph)
        lines = analyze(simple, kind)
        return lines + ['Parallel edges are treated as one for these metrics.']
    return ANALYSES[kind](graph)


def topology_payload(graph):
    """Keep worker messages small and independent of user attributes."""
    return {'directed': graph.is_directed(), 'multiedges': graph.is_multigraph(), 'nodes': list(graph),
            'edges': [list(edge) for edge in (
                graph.edges(keys=True) if graph.is_multigraph() else graph.edges())]}


def graph_from_payload(payload):
    if payload.get('multiedges'):
        graph = nx.MultiDiGraph() if payload['directed'] else nx.MultiGraph()
    else:
        graph = nx.DiGraph() if payload['directed'] else nx.Graph()
    graph.add_nodes_from(payload['nodes'])
    graph.add_edges_from(payload['edges'])
    return graph


def worker_from_files(kind, input_path, output_path):
    """Run a bounded analysis without console streams in a windowed app."""
    payload = json.loads(Path(input_path).read_text(encoding='utf-8'))
    graph = graph_from_payload(payload)
    if kind in ('Morphism', 'Minor'):
        from .morphism import find_morphism
        from .minor import find_minor
        try:
            search = find_morphism if kind == 'Morphism' else find_minor
            result = search(graph, payload['source_nodes'], payload['target_nodes'])
        except (RuntimeError, ValueError) as error:
            result = {'error': str(error)}
    elif kind.startswith('Solve:'):
        from .optimization import optimize_one, result_payload
        try:
            result = result_payload(optimize_one(graph, kind.split(':', 1)[1]))
        except (RuntimeError, ValueError) as error:
            result = {'error': str(error)}
    else:
        result = analyze(graph, kind)
    Path(output_path).write_text(json.dumps(result), encoding='utf-8')


if __name__ == '__main__' and len(sys.argv) == 5 and sys.argv[1] == '--worker':
    worker_from_files(sys.argv[2], sys.argv[3], sys.argv[4])
