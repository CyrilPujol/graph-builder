"""Definitions, validation, and initial drawings for insertable standard graphs.

This module has no Qt dependency. Generator nodes retain their mathematical
names here; the editor assigns fresh internal IDs only when inserting them.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import atan2, ceil, comb, cos, isqrt, pi, sin, sqrt
from random import Random

import networkx as nx


MAX_VERTICES = 200
MAX_EDGES = 4000


@dataclass(frozen=True)
class Parameter:
    key: str
    label: str
    default: int | float
    minimum: int | float
    maximum: int | float
    kind: str = 'int'  # int, probability, or optional_seed


@dataclass(frozen=True)
class GraphDefinition:
    key: str
    title: str
    parameters: tuple[Parameter, ...]
    generate: object
    layout: object
    estimate: object


@dataclass
class GeneratedGraph:
    graph: nx.Graph
    positions: dict
    labels: dict


def _circle_nodes(nodes):
    radius = max(1.0, len(nodes) * 1.5 / (2 * pi))
    return {node: (radius * cos(-pi / 2 + 2 * pi * index / len(nodes)),
                   radius * sin(-pi / 2 + 2 * pi * index / len(nodes)))
            for index, node in enumerate(nodes)}


def _circle(graph, _values=None):
    return _circle_nodes(list(graph))


def _paley_circle(graph, _values=None):
    """Residues 0, 1, 2, ... clockwise, with 0 at twelve o'clock."""
    return _circle_nodes(sorted(graph))


def _shift_subset(subset, amount, modulus):
    return tuple(sorted((value + amount) % modulus for value in subset))


def _kneser_layout(graph, values):
    """Put cyclic-shift orbits on concentric rings.

    Full-length orbits respect the n-fold rotation exactly. Shorter orbits
    cannot do so at distinct planar points, so they use small inner rings.
    """
    n, k = values['n'], values['k']
    if (n, k) == (5, 2):
        # KG(5,2) is the Petersen graph. The disjointness spokes line up when
        # the adjacent-pair orbit is shifted three steps relative to the
        # diagonal-pair orbit.
        positions = {}
        for step in range(5):
            angle = -pi / 2 + 2 * pi * step / 5
            positions[_shift_subset((0, 2), step, 5)] = (
                2.7 * cos(angle), 2.7 * sin(angle))
            positions[_shift_subset((0, 1), step + 3, 5)] = (
                1.2 * cos(angle), 1.2 * sin(angle))
        return positions

    unseen = set(graph)
    orbits = []
    while unseen:
        representative = min(unseen)
        orbit = []
        node = representative
        while node not in orbit:
            orbit.append(node)
            unseen.remove(node)
            node = _shift_subset(node, 1, n)
        orbits.append(orbit)
    short = [orbit for orbit in orbits if len(orbit) < n]
    full = [orbit for orbit in orbits if len(orbit) == n]
    positions = {}
    for ring, orbit in enumerate(short):
        radius = max(1.2, len(orbit) * 1.5 / (2*pi)) + 1.7 * ring
        for step, node in enumerate(orbit):
            angle = -pi/2 + 2*pi*step/len(orbit)
            positions[node] = (radius*cos(angle), radius*sin(angle))
    full_start = max(1.8, n * 1.5 / (2*pi),
                     max((sqrt(x*x+y*y) for x, y in positions.values()), default=0) + 1.8)
    for ring, orbit in enumerate(full):
        # Choose each ring's phase to keep edges to already placed rings short
        # while retaining the exact cyclic rotation of every full orbit.
        phase = 0
        if positions:
            phase = min(range(n), key=lambda offset: sum(
                1 - cos(-pi/2 + 2*pi*(step+offset)/n -
                        atan2(positions[neighbor][1], positions[neighbor][0]))
                for step, node in enumerate(orbit)
                for neighbor in graph[node] if neighbor in positions))
        radius = full_start + 1.7 * ring
        for step, node in enumerate(orbit):
            angle = -pi/2 + 2*pi*(step+phase)/n
            positions[node] = (radius*cos(angle), radius*sin(angle))
    return positions


def _line(graph, _values=None):
    return {node: (1.5 * index, 0.0) for index, node in enumerate(graph)}


def _bipartite(graph, values):
    left = values['a']
    right = values['b']
    return {node: (0.0, 1.5 * (node - (left - 1) / 2)) if node < left else
                  (2.5, 1.5 * (node - left - (right - 1) / 2))
            for node in graph}


def _grid(graph, _values=None):
    return {(row, column): (1.5 * column, 1.5 * row) for row, column in graph}


def _star(graph, _values=None):
    positions = _circle(graph.subgraph(node for node in graph if node != 0))
    positions[0] = (0.0, 0.0)
    return positions


def _petersen(graph, _values=None):
    positions = {}
    for index in range(5):
        angle = -pi / 2 + 2 * pi * index / 5
        positions[index] = (2.7 * cos(angle), 2.7 * sin(angle))
        positions[index + 5] = (1.2 * cos(angle), 1.2 * sin(angle))
    return positions


def _dodecahedron(graph, _values=None):
    """A symmetric Schlegel diagram: pentagon, decagon, pentagon."""
    middle = (4, 5, 6, 7, 8, 9, 10, 11, 18, 17)
    outer = (3, 2, 1, 0, 19)
    inner = (15, 14, 13, 12, 16)
    positions = {}
    for index, node in enumerate(middle):
        angle = -pi / 2 + 2 * pi * index / 10
        positions[node] = (2.8 * cos(angle), 2.8 * sin(angle))
    for index, node in enumerate(outer):
        angle = -pi / 2 + 2 * pi * (2 * index) / 10
        positions[node] = (4.2 * cos(angle), 4.2 * sin(angle))
    for index, node in enumerate(inner):
        angle = -pi / 2 + 2 * pi * (2 * index + 1) / 10
        positions[node] = (1.35 * cos(angle), 1.35 * sin(angle))
    return positions


def _planar(graph, _values=None):
    planar, embedding = nx.check_planarity(graph)
    if not planar:
        return _spring(graph)
    source, target = next(iter(embedding.edges))
    outer_face = embedding.traverse_face(source, target)
    positions = {node: (5 * cos(-pi/2 + 2*pi*i/len(outer_face)),
                        5 * sin(-pi/2 + 2*pi*i/len(outer_face)))
                 for i, node in enumerate(outer_face)}
    interior = [node for node in graph if node not in positions]
    for node in interior:
        positions[node] = (0.0, 0.0)
    # A barycentric embedding keeps every edge inside the outer face and
    # gives the icosahedron a balanced, crossing-free planar drawing.
    for _ in range(1500):
        change = 0.0
        for node in interior:
            x = sum(positions[neighbor][0] for neighbor in graph[node]) / graph.degree(node)
            y = sum(positions[neighbor][1] for neighbor in graph[node]) / graph.degree(node)
            old = positions[node]
            change = max(change, abs(x-old[0]), abs(y-old[1]))
            positions[node] = (x, y)
        if change < 1e-9:
            break
    return positions


def _hypercube(graph, values):
    dimension = values['d']
    columns = max(1, ceil(sqrt(2 ** max(0, dimension - 3))))
    positions = {}
    for bits in graph:
        x = (1.5 * bits[0] if dimension >= 1 else 0)
        y = (1.5 * bits[1] if dimension >= 2 else 0)
        if dimension >= 3:
            x += .8 * bits[2]
            y -= .8 * bits[2]
        tile = sum(bit << index for index, bit in enumerate(bits[3:]))
        positions[bits] = (x + 3.7 * (tile % columns),
                           y + 3.7 * (tile // columns))
    return positions


def _spring(graph, _values=None):
    """Deterministic small-graph force layout without a NumPy dependency."""
    nodes = list(graph)
    if len(nodes) <= 1:
        return {node: (0.0, 0.0) for node in nodes}
    random = Random(1729)
    positions = {node: [3 * cos(2*pi*i/len(nodes)) + random.uniform(-.1, .1),
                        3 * sin(2*pi*i/len(nodes)) + random.uniform(-.1, .1)]
                 for i, node in enumerate(nodes)}
    edges = list(graph.edges)
    for iteration in range(65):
        movement = {node: [0.0, 0.0] for node in nodes}
        for i, source in enumerate(nodes):
            for target in nodes[i + 1:]:
                dx = positions[source][0] - positions[target][0]
                dy = positions[source][1] - positions[target][1]
                distance = max(.01, sqrt(dx*dx + dy*dy))
                force = 2.25 / distance**2
                movement[source][0] += dx * force
                movement[source][1] += dy * force
                movement[target][0] -= dx * force
                movement[target][1] -= dy * force
        for source, target in edges:
            dx = positions[source][0] - positions[target][0]
            dy = positions[source][1] - positions[target][1]
            distance = max(.01, sqrt(dx*dx + dy*dy))
            force = distance / 2.25
            movement[source][0] -= dx * force
            movement[source][1] -= dy * force
            movement[target][0] += dx * force
            movement[target][1] += dy * force
        temperature = max(.015, .6 * (1 - iteration / 65))
        for node in nodes:
            dx, dy = movement[node]
            length = max(.01, sqrt(dx*dx + dy*dy))
            positions[node][0] += dx / length * min(length, temperature)
            positions[node][1] += dy / length * min(length, temperature)
    return {node: tuple(position) for node, position in positions.items()}


def _kneser(n, k):
    generator = getattr(nx, 'kneser_graph', None)
    if callable(generator):
        return generator(n, k)
    graph = nx.Graph()
    graph.add_nodes_from(combinations(range(n), k))
    for source, target in combinations(graph, 2):
        if set(source).isdisjoint(target):
            graph.add_edge(source, target)
    return graph


def _paley(p):
    return nx.Graph(nx.paley_graph(p))


def _is_prime(number):
    return number >= 2 and all(number % divisor for divisor in range(2, isqrt(number) + 1))


def _kneser_counts(values):
    n, k = values['n'], values['k']
    vertices = comb(n, k)
    return vertices, vertices * comb(n-k, k) // 2 if n >= 2*k else 0


def _random_counts(values):
    n = values['n']
    return n, n * (n-1) * values['p'] / 2


N = Parameter('n', 'Vertices', 5, 1, 1000)
STANDARD_GRAPHS = (
    GraphDefinition('petersen', 'Petersen', (), lambda v: nx.petersen_graph(),
                    _petersen, lambda v: (10, 15)),
    GraphDefinition('clique', 'Clique Kₙ', (N,), lambda v: nx.complete_graph(v['n']),
                    _circle, lambda v: (v['n'], v['n']*(v['n']-1)//2)),
    GraphDefinition('bipartite', 'Complete bipartite Kₐ,ᵦ',
                    (Parameter('a', 'Left', 3, 1, 1000), Parameter('b', 'Right', 3, 1, 1000)),
                    lambda v: nx.complete_bipartite_graph(v['a'], v['b']), _bipartite,
                    lambda v: (v['a']+v['b'], v['a']*v['b'])),
    GraphDefinition('path', 'Path Pₙ', (N,), lambda v: nx.path_graph(v['n']),
                    _line, lambda v: (v['n'], v['n']-1)),
    GraphDefinition('cycle', 'Cycle Cₙ', (Parameter('n', 'Vertices', 5, 3, 1000),),
                    lambda v: nx.cycle_graph(v['n']), _circle, lambda v: (v['n'], v['n'])),
    GraphDefinition('star', 'Star Sₙ', (Parameter('n', 'Leaves', 5, 1, 1000),),
                    lambda v: nx.star_graph(v['n']), _star, lambda v: (v['n']+1, v['n'])),
    GraphDefinition('grid', 'Rectangular grid',
                    (Parameter('rows', 'Rows', 3, 1, 1000),
                     Parameter('columns', 'Columns', 4, 1, 1000)),
                    lambda v: nx.grid_2d_graph(v['rows'], v['columns']), _grid,
                    lambda v: (v['rows']*v['columns'],
                               v['rows']*(v['columns']-1)+v['columns']*(v['rows']-1))),
    GraphDefinition('hypercube', 'Hypercube Qₐ',
                    (Parameter('d', 'Dimension', 3, 1, 20),),
                    lambda v: nx.hypercube_graph(v['d']), _hypercube,
                    lambda v: (2**v['d'], v['d']*2**(v['d']-1))),
    GraphDefinition('dodecahedron', 'Dodecahedron', (),
                    lambda v: nx.dodecahedral_graph(), _dodecahedron, lambda v: (20, 30)),
    GraphDefinition('icosahedron', 'Icosahedron', (),
                    lambda v: nx.icosahedral_graph(), _planar, lambda v: (12, 30)),
    GraphDefinition('kneser', 'Kneser KG(n,k)',
                    (Parameter('n', 'n', 5, 2, 1000), Parameter('k', 'k', 2, 1, 1000)),
                    lambda v: _kneser(v['n'], v['k']), _kneser_layout, _kneser_counts),
    GraphDefinition('paley', 'Paley', (Parameter('p', 'Prime p', 5, 5, 1000),),
                    lambda v: _paley(v['p']), _paley_circle,
                    lambda v: (v['p'], v['p']*(v['p']-1)//4)),
    GraphDefinition('random', 'Random G(n,p)',
                    (Parameter('n', 'Vertices', 10, 1, 1000),
                     Parameter('p', 'Probability', .25, 0.0, 1.0, 'probability'),
                     Parameter('seed', 'Seed', -1, -1, 999999999, 'optional_seed')),
                    lambda v: nx.gnp_random_graph(v['n'], v['p'],
                                                  seed=None if v['seed'] == -1 else v['seed']),
                    _spring, _random_counts),
)
GRAPH_BY_KEY = {definition.key: definition for definition in STANDARD_GRAPHS}


def validate_standard_graph(key, supplied=None):
    """Return (normalized parameters, predicted vertices, predicted edges)."""
    definition = GRAPH_BY_KEY[key]
    supplied = supplied or {}
    values = {}
    for parameter in definition.parameters:
        value = supplied.get(parameter.key, parameter.default)
        if parameter.kind == 'optional_seed' and value is None:
            value = -1
        if parameter.kind == 'probability':
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f'{parameter.label} must be a number.')
            value = float(value)
        elif isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f'{parameter.label} must be an integer.')
        if not parameter.minimum <= value <= parameter.maximum:
            raise ValueError(f'{parameter.label} must be between {parameter.minimum} and {parameter.maximum}.')
        values[parameter.key] = value
    if key == 'kneser' and values['k'] >= values['n']:
        raise ValueError('Kneser graphs require 1 ≤ k < n.')
    if key == 'paley' and (values['p'] % 4 != 1 or not _is_prime(values['p'])):
        raise ValueError('Paley p must be prime and congruent to 1 mod 4.')
    vertices, edges = definition.estimate(values)
    if vertices > MAX_VERTICES or edges > MAX_EDGES:
        raise ValueError(f'Too large for interactive editing (limit: {MAX_VERTICES} vertices '
                         f'and {MAX_EDGES} edges).')
    return values, vertices, edges


def generate_standard_graph(key, supplied=None):
    values, _, _ = validate_standard_graph(key, supplied)
    definition = GRAPH_BY_KEY[key]
    graph = definition.generate(values)
    if graph.is_directed():
        graph = nx.Graph(graph)
    if graph.number_of_nodes() > MAX_VERTICES or graph.number_of_edges() > MAX_EDGES:
        raise ValueError('The generated graph exceeds the interactive size limit.')
    positions = definition.layout(graph, values)
    if set(positions) != set(graph):
        raise ValueError('The generator did not position every vertex.')
    labels = {node: (','.join(map(str, node)) if isinstance(node, tuple) else str(node))
              for node in graph}
    if key == 'hypercube':
        labels = {node: ''.join(map(str, node)) for node in graph}
    elif key == 'star':
        labels[0] = 'c'
    elif key == 'bipartite':
        labels = {node: (f'A{node+1}' if node < values['a'] else
                         f'B{node-values["a"]+1}') for node in graph}
    return GeneratedGraph(graph, positions, labels)
