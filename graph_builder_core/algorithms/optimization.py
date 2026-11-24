"""Bounded graph optimization with certified results.

Hard invariants use the optional CP-SAT solver. Matching and edge cover use
exact NetworkX algorithms. Time limits retain witnesses and rigorous bounds
rather than claiming an optimum.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor
import time

import networkx as nx

from graph_builder_core.model.edges import edge_records


MAX_VERTICES = 180
MAX_COLOR_VARIABLES = 12_000
MAX_EDGE_COLOR_EDGES = 400
DEFAULT_SECONDS = 60.0
DEFAULT_WORKERS = 4


@dataclass(frozen=True)
class OptimizationResult:
    """Certified bounds and a best-known witness from one optimization run.

    Attributes
    ----------
    lower, upper : int
        Proven bounds. Equality certifies the optimum.
    witness : object
        Best-known solution, such as a vertex set for ``'independent'``.
    optimal : bool
        Whether the optimum was proved.
    elapsed : float
        Time spent in seconds.
    name, note : str
        Human-readable problem name and optional explanation.
    """

    name: str
    lower: int
    upper: int
    witness: object
    optimal: bool
    elapsed: float
    note: str = ''


def _solver(seconds, workers):
    try:
        from ortools.sat.python import cp_model
    except ImportError as error:
        raise RuntimeError('The optional OR-Tools solver is not installed.') from error

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.01, float(seconds))
    solver.parameters.num_workers = max(1, int(workers))
    return cp_model, solver


def _integer_upper(bound):
    return floor(float(bound) + 1e-6)


def _integer_lower(bound):
    return ceil(float(bound) - 1e-6)


def _greedy_independent(graph):
    remaining = set(graph)
    chosen = set()
    while remaining:
        node = min(remaining, key=lambda vertex: (len(remaining & set(graph[vertex])), str(vertex)))
        chosen.add(node)
        remaining.difference_update(set(graph[node]) | {node})
    return chosen


def _greedy_clique(graph):
    """Find a certified clique lower bound used by quick and exact metrics."""
    neighbors = {node: set(graph.neighbors(node)) for node in graph}
    degree_order = sorted(graph, key=lambda node: (-len(neighbors[node]), str(node)))
    best = set()
    for start in degree_order[:min(len(degree_order), 12)]:
        clique = {start}
        candidates = neighbors[start].copy()
        while candidates:
            chosen = max(candidates, key=lambda node: (
                len(candidates & neighbors[node]), len(neighbors[node])))
            clique.add(chosen)
            candidates.intersection_update(neighbors[chosen])
        if len(clique) > len(best):
            best = clique
    return best


def _independent(graph, name, seconds, workers):
    cp_model, solver = _solver(seconds, workers)
    nodes = list(graph)
    model = cp_model.CpModel()
    selected = {node: model.new_bool_var(f's_{index}') for index, node in enumerate(nodes)}
    for first, second in graph.edges():
        model.add(selected[first] + selected[second] <= 1)
    model.maximize(sum(selected.values()))
    heuristic = _greedy_independent(graph)
    for node in nodes:
        model.add_hint(selected[node], int(node in heuristic))
    started = time.monotonic()
    status = solver.solve(model)
    elapsed = time.monotonic() - started
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE, cp_model.UNKNOWN):
        raise RuntimeError(f'The solver could not process the {name} model.')
    witness = ({node for node in nodes if solver.value(selected[node])}
               if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else heuristic)
    upper = (len(witness) if status == cp_model.OPTIMAL else
             min(len(nodes), _integer_upper(solver.best_objective_bound))
             if status == cp_model.FEASIBLE else len(nodes))
    upper = max(len(witness), upper)
    return OptimizationResult(name, len(witness), upper, witness,
                              status == cp_model.OPTIMAL or len(witness) == upper, elapsed)


def _coloring(graph, clique_lower, seconds, workers):
    nodes = list(graph)
    if not nodes:
        return OptimizationResult('Chromatic number χ', 0, 0, {}, True, 0.0)
    greedy = nx.coloring.greedy_color(graph, strategy='DSATUR')
    colors = max(greedy.values()) + 1
    if clique_lower == colors:
        return OptimizationResult('Chromatic number χ', colors, colors, greedy, True, 0.0)
    if len(nodes) * colors > MAX_COLOR_VARIABLES:
        return OptimizationResult('Chromatic number χ', clique_lower, colors,
                                  greedy, False, 0.0, 'model-size limit')
    cp_model, solver = _solver(seconds, workers)
    model = cp_model.CpModel()
    assignments = {(node, color): model.new_bool_var(f'c_{index}_{color}')
                   for index, node in enumerate(nodes) for color in range(colors)}
    used = [model.new_bool_var(f'used_{color}') for color in range(colors)]
    for node in nodes:
        model.add_exactly_one(assignments[node, color] for color in range(colors))
        for color in range(colors):
            model.add(assignments[node, color] <= used[color])
            model.add_hint(assignments[node, color], int(greedy[node] == color))
    for first, second in graph.edges():
        for color in range(colors):
            model.add(assignments[first, color] + assignments[second, color] <= 1)
    for color in range(colors):
        model.add_hint(used[color], 1)
    model.minimize(sum(used))
    started = time.monotonic()
    status = solver.solve(model)
    elapsed = time.monotonic() - started
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE, cp_model.UNKNOWN):
        raise RuntimeError('The solver could not process the coloring model.')
    witness = ({node: next(color for color in range(colors)
                           if solver.value(assignments[node, color])) for node in nodes}
               if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else greedy)
    upper = len(set(witness.values()))
    lower = (upper if status == cp_model.OPTIMAL else
             max(clique_lower, _integer_lower(solver.best_objective_bound))
             if status == cp_model.FEASIBLE else clique_lower)
    return OptimizationResult('Chromatic number χ', min(lower, upper), upper,
                              witness, status == cp_model.OPTIMAL or lower == upper, elapsed)


def _dominating_set_greedy(graph):
    uncovered = set(graph)
    chosen = set()
    while uncovered:
        node = max(graph, key=lambda vertex: len(uncovered & (set(graph[vertex]) | {vertex})))
        chosen.add(node)
        uncovered.difference_update(set(graph[node]) | {node})
    return chosen


def _domination(graph, seconds, workers):
    name = 'Domination number γ'
    if not graph:
        return OptimizationResult(name, 0, 0, set(), True, 0.0)
    heuristic = _dominating_set_greedy(graph)
    degrees = graph.out_degree() if graph.is_directed() else graph.degree()
    lower = ceil(len(graph) / (max(dict(degrees).values()) + 1))
    if lower == len(heuristic):
        return OptimizationResult(name, lower, lower, heuristic, True, 0.0)
    cp_model, solver = _solver(seconds, workers)
    model = cp_model.CpModel()
    chosen = {node: model.new_bool_var(f'd_{index}') for index, node in enumerate(graph)}
    for node in graph:
        predecessors = graph.predecessors(node) if graph.is_directed() else graph[node]
        model.add(sum(chosen[neighbor] for neighbor in set(predecessors) | {node}) >= 1)
        model.add_hint(chosen[node], int(node in heuristic))
    model.minimize(sum(chosen.values()))
    started = time.monotonic()
    status = solver.solve(model)
    elapsed = time.monotonic() - started
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE, cp_model.UNKNOWN):
        raise RuntimeError('The solver could not process the domination model.')
    witness = ({node for node in graph if solver.value(chosen[node])}
               if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else heuristic)
    lower = (len(witness) if status == cp_model.OPTIMAL else
             max(lower, _integer_lower(solver.best_objective_bound))
             if status == cp_model.FEASIBLE else lower)
    upper = len(witness)
    return OptimizationResult(name, min(lower, upper), upper, witness,
                              status == cp_model.OPTIMAL or lower == upper, elapsed)


def _domatic(graph, seconds, workers):
    name = 'Domatic number d'
    if not graph:
        return OptimizationResult(name, 0, 0, {}, True, 0.0)
    degrees = graph.in_degree() if graph.is_directed() else graph.degree()
    upper = min(dict(degrees).values()) + 1
    if upper == 1:
        return OptimizationResult(name, 1, 1, {node: 0 for node in graph}, True, 0.0)
    cp_model, solver = _solver(seconds, workers)
    model = cp_model.CpModel()
    nodes = list(graph)
    assigned = {(node, color): model.new_bool_var(f'd_{index}_{color}')
                for index, node in enumerate(nodes) for color in range(upper)}
    used = [model.new_bool_var(f'used_{color}') for color in range(upper)]
    for index, node in enumerate(nodes):
        model.add_exactly_one(assigned[node, color] for color in range(upper))
        for color in range(upper):
            model.add(assigned[node, color] <= used[color])
            predecessors = graph.predecessors(node) if graph.is_directed() else graph[node]
            model.add(sum(assigned[neighbor, color]
                          for neighbor in set(predecessors) | {node}) >= used[color])
            model.add_hint(assigned[node, color], int(color == 0))
    for color in range(upper - 1):
        model.add(used[color] >= used[color + 1])
    for color in range(upper):
        model.add_hint(used[color], int(color == 0))
    model.maximize(sum(used))
    started = time.monotonic()
    status = solver.solve(model)
    elapsed = time.monotonic() - started
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE, cp_model.UNKNOWN):
        raise RuntimeError('The solver could not process the domatic model.')
    witness = ({node: next(color for color in range(upper)
                           if solver.value(assigned[node, color])) for node in nodes}
               if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else
               {node: 0 for node in nodes})
    lower = len(set(witness.values()))
    upper = (lower if status == cp_model.OPTIMAL else
             min(upper, _integer_upper(solver.best_objective_bound))
             if status == cp_model.FEASIBLE else upper)
    return OptimizationResult(name, lower, max(lower, upper), witness,
                              status == cp_model.OPTIMAL or lower == upper, elapsed)


def _edge_chromatic(graph, seconds, workers):
    name = 'Edge chromatic number χ′'
    if nx.number_of_selfloops(graph):
        raise ValueError('A loop cannot receive a proper edge coloring.')
    multi = nx.MultiGraph()
    multi.add_nodes_from(graph)
    identities = {}
    for serial, (source, target, key, _) in enumerate(edge_records(graph)):
        multi.add_edge(source, target, key=serial)
        identities[serial] = (source, target, key)
    if not multi.number_of_edges():
        return OptimizationResult(name, 0, 0, {}, True, 0.0)
    lower = max(dict(multi.degree()).values())
    if multi.number_of_edges() > MAX_EDGE_COLOR_EDGES:
        return OptimizationResult(name, lower, multi.number_of_edges(), {}, False, 0.0,
                                  'model-size limit')
    line_graph = nx.Graph(nx.line_graph(multi))
    result = _coloring(line_graph, lower, seconds, workers)
    witness = {identities[edge[2]]: color for edge, color in result.witness.items()}
    return OptimizationResult(name, result.lower, result.upper, witness,
                              result.optimal, result.elapsed, result.note)


def _existing_edge(graph, source, target):
    """Choose one actual arc or parallel edge for an undirected witness pair."""
    if not graph.has_edge(source, target):
        source, target = target, source
    key = next(iter(graph[source][target])) if graph.is_multigraph() else None
    return source, target, key


def _matching(graph):
    simple = nx.Graph(graph)
    simple.remove_edges_from(nx.selfloop_edges(simple))
    pairs = nx.max_weight_matching(simple, maxcardinality=True)
    witness = {_existing_edge(graph, u, v) for u, v in pairs}
    size = len(witness)
    return OptimizationResult('Maximum matching ν', size, size, witness, True, 0.0)


def _vertex_cover(graph, seconds, workers):
    """The complement of an independent set is a vertex cover."""
    simple = nx.Graph(graph)
    forced = {node for node, _ in nx.selfloop_edges(simple)}
    simple.remove_nodes_from(forced)
    heuristic = _greedy_independent(simple)
    lower = len(forced) + len(nx.max_weight_matching(simple, maxcardinality=True))
    upper = len(graph) - len(heuristic)
    if lower == upper:
        return OptimizationResult('Minimum vertex cover τ', lower, upper,
                                  set(graph) - heuristic, True, 0.0)
    independent = _independent(simple, 'Independence number α', seconds, workers)
    size = len(graph)
    witness = set(graph) - set(independent.witness)
    return OptimizationResult('Minimum vertex cover τ', size - independent.upper,
                              size - independent.lower, witness,
                              independent.optimal, independent.elapsed, independent.note)


def _edge_cover(graph):
    """A minimum edge cover follows from maximum matching, including loops."""
    simple = nx.Graph(graph)
    try:
        cover = nx.algorithms.covering.min_edge_cover(simple)
    except nx.NetworkXException as error:
        raise ValueError('No edge cover exists because a vertex has no incident edge.') from error
    witness = {_existing_edge(graph, u, v) for u, v in cover}
    size = len(witness)
    return OptimizationResult('Minimum edge cover ρ', size, size, witness, True, 0.0)


def optimize(graph, seconds=DEFAULT_SECONDS, workers=DEFAULT_WORKERS):
    """Return certified bounds and witnesses for clique, independence, coloring.

    Requires the optional ``ortools`` package. Directed edges are treated as
    undirected, parallel edges as one. A loop makes proper coloring impossible.
    The input graph is never modified.

    Example::

        from graph_builder import optimize_graph
        clique, independent, coloring = optimize_graph(graph, seconds=5)
        print(coloring.lower, coloring.upper, coloring.witness)
    """
    try:
        from ortools.sat.python import cp_model  # noqa: F401
    except ImportError as error:
        raise RuntimeError('The optional OR-Tools solver is not installed.') from error
    simple = nx.Graph(graph)
    loops = nx.number_of_selfloops(simple)
    simple.remove_edges_from(nx.selfloop_edges(simple))
    if len(simple) > MAX_VERTICES:
        raise ValueError(f'Optimization is limited to {MAX_VERTICES} vertices for now.')
    if not simple:
        empty = OptimizationResult('Clique number ω', 0, 0, set(), True, 0.0)
        return (empty, OptimizationResult('Independence number α', 0, 0, set(), True, 0.0),
                OptimizationResult('Chromatic number χ', 0, 0, {}, True, 0.0))
    deadline = time.monotonic() + max(0.03, float(seconds))
    # One shared independent-set formulation. Complementing the graph turns
    # independent sets into cliques in the original graph.
    clique = _independent(nx.complement(simple), 'Clique number ω',
                          max(0.01, (deadline - time.monotonic()) / 3), workers)
    independent = _independent(simple, 'Independence number α',
                               max(0.01, (deadline - time.monotonic()) / 2), workers)
    coloring = (None if loops else _coloring(simple, clique.lower,
                                            max(0.01, deadline - time.monotonic()), workers))
    return clique, independent, coloring
PROBLEMS = ('clique', 'independent', 'chromatic', 'edge_chromatic',
            'vertex_cover', 'edge_cover', 'matching', 'domination', 'domatic',
            'treewidth')


def optimize_one(graph, problem, seconds=DEFAULT_SECONDS, workers=DEFAULT_WORKERS):
    """Compute certified bounds for one graph invariant.

    Parameters
    ----------
    graph : networkx.Graph
        Graph to analyze. The accepted directedness depends on the problem.
    problem : str
        One of ``'clique'``, ``'independent'``, ``'chromatic'``,
        ``'edge_chromatic'``, ``'vertex_cover'``, ``'edge_cover'``,
        ``'matching'``, ``'domination'``, ``'domatic'``, or ``'treewidth'``.
    seconds : float, optional
        Solver time limit in seconds, defaulting to 60.
    workers : int, optional
        Number of solver workers, defaulting to 4.

    Returns
    -------
    OptimizationResult
        Proven lower and upper bounds and a best-known witness. A timed-out
        run may still have a usable witness without proving optimality.

    Examples
    --------
    ``answer = optimize_one(graph, 'independent', seconds=2)`` returns a
    vertex set in ``answer.witness`` and bounds in ``answer.lower`` and
    ``answer.upper``.
    """
    if problem not in PROBLEMS:
        raise ValueError(f'Unknown optimization problem: {problem}')
    if problem == 'treewidth':
        from graph_builder_core.algorithms.treewidth import solve
        return solve(graph, seconds)
    if problem in ('matching', 'edge_cover'):
        return _matching(graph) if problem == 'matching' else _edge_cover(graph)
    simple = nx.Graph(graph)
    loops = nx.number_of_selfloops(simple)
    simple.remove_edges_from(nx.selfloop_edges(simple))
    if len(simple) > MAX_VERTICES:
        raise ValueError(f'Optimization is limited to {MAX_VERTICES} vertices for now.')
    if not simple:
        name = {'clique': 'Clique number ω', 'independent': 'Independence number α',
                'chromatic': 'Chromatic number χ', 'edge_chromatic': 'Edge chromatic number χ′',
                'vertex_cover': 'Minimum vertex cover τ',
                'domination': 'Domination number γ', 'domatic': 'Domatic number d'}[problem]
        return OptimizationResult(name, 0, 0, {} if problem in ('chromatic', 'domatic', 'edge_chromatic')
                                  else set(), True, 0.0)
    if problem == 'clique':
        return _independent(nx.complement(simple), 'Clique number ω', seconds, workers)
    if problem == 'independent':
        return _independent(simple, 'Independence number α', seconds, workers)
    if problem in ('domination', 'domatic'):
        domination_graph = nx.DiGraph(graph) if graph.is_directed() else simple
        domination_graph.remove_edges_from(nx.selfloop_edges(domination_graph))
        return (_domination(domination_graph, seconds, workers) if problem == 'domination'
                else _domatic(domination_graph, seconds, workers))
    if problem == 'edge_chromatic':
        return _edge_chromatic(graph, seconds, workers)
    if problem == 'vertex_cover':
        return _vertex_cover(graph, seconds, workers)
    if loops:
        raise ValueError('No proper coloring exists for a graph with a loop.')
    clique_lower = len(_greedy_clique(simple))
    return _coloring(simple, clique_lower, seconds, workers)


def result_payload(result):
    """JSON-safe result, including the complete witness for an apply action."""
    witness = (result.witness if result.name == 'Tree-width tw' else
               list(result.witness.items()) if isinstance(result.witness, dict)
               else list(result.witness))
    return {'name': result.name, 'lower': result.lower, 'upper': result.upper,
            'optimal': result.optimal or result.lower == result.upper,
            'note': result.note, 'witness': witness}


def format_results(graph, seconds=DEFAULT_SECONDS, workers=DEFAULT_WORKERS):
    """Human-readable solver report for the Properties panel."""
    try:
        results = optimize(graph, seconds, workers)
    except (RuntimeError, ValueError) as error:
        return [str(error)]
    lines = []
    for result in results:
        if result is None:
            lines.append('Chromatic number χ: no proper coloring exists with a loop')
            continue
        symbol = result.name.rsplit(' ', 1)[-1]
        value = (str(result.lower) if result.lower == result.upper else
                 f'{result.lower} ≤ {symbol} ≤ {result.upper}')
        lines.append(f'{result.name}: {value}' +
                     (' (proved)' if result.optimal else
                      f' ({result.note or "time-limited bounds"})'))
    for result in results:
        if result is None:
            continue
        if isinstance(result.witness, dict):
            preview = [f'{node}→{color + 1}' for node, color in
                       sorted(result.witness.items(), key=lambda item: str(item[0]))[:20]]
            title = 'Coloring'
        else:
            preview = [str(node) for node in sorted(result.witness, key=str)[:20]]
            title = 'Clique' if 'Clique' in result.name else 'Independent set'
        suffix = ', …' if len(result.witness) > 20 else ''
        lines.append(f'{title} found: {", ".join(preview)}{suffix}')
    if graph.is_directed():
        lines.append('Arrow directions are ignored.')
    if graph.is_multigraph():
        lines.append('Parallel edges are treated as one.')
    return lines
