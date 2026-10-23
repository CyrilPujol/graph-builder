"""Generator structure, labels, layouts, and validation without Qt."""
import unittest
from unittest.mock import patch
from math import cos, hypot, pi, sin

import networkx as nx

from standard_graphs import (
    GRAPH_BY_KEY, STANDARD_GRAPHS, generate_standard_graph, validate_standard_graph,
)


class StandardGraphTests(unittest.TestCase):
    def test_every_generator_has_complete_structure_and_positions(self):
        expected = {
            'petersen': (10, 15),
            'clique': (5, 10),
            'bipartite': (6, 9),
            'path': (5, 4),
            'cycle': (5, 5),
            'star': (6, 5),
            'grid': (12, 17),
            'hypercube': (8, 12),
            'dodecahedron': (20, 30),
            'icosahedron': (12, 30),
            'kneser': (10, 15),
            'paley': (5, 5),
        }
        self.assertEqual(set(GRAPH_BY_KEY), expected.keys() | {'random'})
        self.assertEqual(len(STANDARD_GRAPHS), len(expected) + 1)
        for key, counts in expected.items():
            with self.subTest(graph=key):
                result = generate_standard_graph(key)
                self.assertEqual((result.graph.number_of_nodes(), result.graph.number_of_edges()),
                                 counts)
                self.assertEqual(set(result.positions), set(result.graph))
                self.assertEqual(set(result.labels), set(result.graph))
                self.assertTrue(all(isinstance(label, str) and label for label in result.labels.values()))
                self.assertFalse(result.graph.is_directed())
                self.assertEqual(nx.number_of_selfloops(result.graph), 0)

    def test_parameterized_counts_and_meaningful_labels(self):
        cases = (
            ('clique', {'n': 6}, (6, 15)),
            ('bipartite', {'a': 2, 'b': 4}, (6, 8)),
            ('path', {'n': 1}, (1, 0)),
            ('cycle', {'n': 7}, (7, 7)),
            ('star', {'n': 8}, (9, 8)),
            ('grid', {'rows': 2, 'columns': 5}, (10, 13)),
            ('hypercube', {'d': 4}, (16, 32)),
            ('kneser', {'n': 6, 'k': 2}, (15, 45)),
            ('paley', {'p': 13}, (13, 39)),
        )
        for key, parameters, counts in cases:
            with self.subTest(graph=key):
                generated = generate_standard_graph(key, parameters)
                self.assertEqual((generated.graph.number_of_nodes(),
                                  generated.graph.number_of_edges()), counts)
        self.assertEqual(generate_standard_graph('kneser').labels[(0, 1)], '0,1')
        self.assertEqual(generate_standard_graph('grid').labels[(1, 2)], '1,2')
        self.assertEqual(generate_standard_graph('hypercube').labels[(0, 1, 0)], '010')
        self.assertEqual(generate_standard_graph('star').labels[0], 'c')

    def test_seeded_random_is_reproducible(self):
        first = generate_standard_graph('random', {'n': 12, 'p': .3, 'seed': 17})
        second = generate_standard_graph('random', {'n': 12, 'p': .3, 'seed': 17})
        self.assertEqual(set(first.graph.edges), set(second.graph.edges))
        self.assertEqual(first.positions, second.positions)
        self.assertEqual(first.graph.number_of_nodes(), 12)

    def test_paley_vertices_follow_numeric_clockwise_order(self):
        positions = generate_standard_graph('paley', {'p': 13}).positions
        radius = hypot(*positions[0])
        for number in range(13):
            angle = 2*pi*number/13
            self.assertAlmostEqual(positions[number][0], radius*sin(angle))
            self.assertAlmostEqual(positions[number][1], -radius*cos(angle))

    def test_kneser_cyclic_symmetry_and_petersen_spokes(self):
        for n, k in ((5, 2), (7, 3)):
            generated = generate_standard_graph('kneser', {'n': n, 'k': k})
            for subset, (x, y) in generated.positions.items():
                successor = tuple(sorted((value + 1) % n for value in subset))
                angle = 2*pi/n
                expected = (x*cos(angle) - y*sin(angle),
                            x*sin(angle) + y*cos(angle))
                actual = generated.positions[successor]
                self.assertAlmostEqual(actual[0], expected[0])
                self.assertAlmostEqual(actual[1], expected[1])
        petersen = generate_standard_graph('kneser', {'n': 5, 'k': 2})
        outer = [subset for subset in petersen.graph
                 if (subset[1] - subset[0]) % 5 in (2, 3)]
        self.assertEqual(len(outer), 5)
        for subset in outer:
            inner_neighbors = [neighbor for neighbor in petersen.graph[subset]
                               if hypot(*petersen.positions[neighbor]) < 2]
            self.assertEqual(len(inner_neighbors), 1)
            x, y = petersen.positions[subset]
            u, v = petersen.positions[inner_neighbors[0]]
            self.assertAlmostEqual(x*v - y*u, 0)
            self.assertGreater(x*u + y*v, 0)

    def test_kneser_short_orbits_keep_distinct_positions(self):
        generated = generate_standard_graph('kneser', {'n': 6, 'k': 2})
        positions = {(round(x, 9), round(y, 9)) for x, y in generated.positions.values()}
        self.assertEqual(len(positions), generated.graph.number_of_nodes())

    def test_kneser_fallback_for_older_networkx(self):
        with patch.object(nx, 'kneser_graph', None):
            generated = generate_standard_graph('kneser', {'n': 5, 'k': 2})
        self.assertEqual(generated.graph.number_of_nodes(), 10)
        self.assertEqual(generated.graph.number_of_edges(), 15)

    def test_invalid_parameters_and_size_guards(self):
        invalid = (
            ('cycle', {'n': 2}),
            ('kneser', {'n': 5, 'k': 5}),
            ('paley', {'p': 7}),
            ('paley', {'p': 9}),
            ('random', {'n': 10, 'p': 1.2}),
            ('random', {'n': 10, 'p': .5, 'seed': -2}),
            ('clique', {'n': 200}),
            ('hypercube', {'d': 20}),
            ('grid', {'rows': 20, 'columns': 20}),
        )
        for key, parameters in invalid:
            with self.subTest(graph=key, parameters=parameters):
                with self.assertRaises(ValueError):
                    validate_standard_graph(key, parameters)
                with self.assertRaises(ValueError):
                    generate_standard_graph(key, parameters)


if __name__ == '__main__':
    unittest.main()
