"""Automatic layout scope, anchors, and position calculations."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from graph_builder_lib import convert_from_file, empty_graph, write_graph_file
from graph_layout import (PIN_ATTRIBUTE, arrange_positions, movable_vertices,
                          nearby_movable_vertices, neighborhood_distances,
                          pinned_vertices, relaxed_neighborhood_positions)


def path_graph():
    graph = empty_graph()
    for node, x in (('a', 0), ('b', 50), ('c', 100), ('d', 150)):
        graph.add_node(node, position=(x, 0), col=0)
    for a, b in (('a', 'b'), ('b', 'c'), ('c', 'd')):
        graph.add_edge(a, b, col=0)
        graph.add_edge(b, a, col=0)
    return graph


class GraphLayoutTests(unittest.TestCase):
    def test_selection_and_pins_determine_movable_nodes(self):
        graph = path_graph()
        graph.nodes['b'][PIN_ATTRIBUTE] = True
        self.assertEqual(pinned_vertices(graph), {'b'})
        self.assertEqual(movable_vertices(graph), {'a', 'c', 'd'})
        self.assertEqual(movable_vertices(graph, {'a', 'b'}), {'a'})
        self.assertEqual(nearby_movable_vertices(graph, {'a'}), set())

    def test_selected_layout_preserves_fixed_vertices_and_input(self):
        graph = path_graph()
        original = {node: graph.nodes[node]['position'] for node in graph}
        positions = arrange_positions(graph, {'b', 'c'}, iterations=20)
        self.assertEqual(set(positions), {'b', 'c'})
        self.assertEqual({node: graph.nodes[node]['position'] for node in graph}, original)
        self.assertTrue(all(all(isinstance(value, float) for value in point)
                            for point in positions.values()))

    def test_pin_survives_graphml_round_trip(self):
        graph = path_graph()
        graph.nodes['b'][PIN_ATTRIBUTE] = True
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'graph.graphml'
            write_graph_file(graph, path)
            restored = convert_from_file(path)
        self.assertEqual(pinned_vertices(restored), {'b'})

    def test_coincident_vertices_can_be_arranged(self):
        graph = path_graph()
        for node in graph:
            graph.nodes[node]['position'] = (0, 0)
        positions = arrange_positions(graph, set(graph), iterations=30)
        self.assertGreater(len(set(positions.values())), 1)

    def test_live_relaxation_moves_only_direct_neighbors_with_distance_two_anchors(self):
        graph = path_graph()
        self.assertEqual(neighborhood_distances(graph, {'a'}),
                         {'a': 0, 'b': 1})

        def proposal(local_graph, movable, **kwargs):
            self.assertEqual(set(local_graph), {'a', 'b', 'c'})
            self.assertEqual(movable, {'b'})
            return {node: (graph.nodes[node]['position'][0] + 20, 0)
                    for node in movable}

        with patch('graph_layout.arrange_positions', side_effect=proposal):
            positions = relaxed_neighborhood_positions(graph, {'a'})
        self.assertEqual(set(positions), {'b'})
        self.assertAlmostEqual(positions['b'][0], 56)
        self.assertEqual(graph.nodes['c']['position'], (100, 0))
        self.assertEqual(graph.nodes['d']['position'], (150, 0))

    def test_distance_two_anchor_changes_neighbor_force_without_moving(self):
        graph = path_graph()
        original = {node: graph.nodes[node]['position'] for node in graph}
        first = relaxed_neighborhood_positions(graph, {'a'}).get('b', original['b'])
        graph.nodes['c']['position'] = (100, 150)
        second = relaxed_neighborhood_positions(graph, {'a'})['b']
        self.assertNotEqual(first, second)
        self.assertEqual(graph.nodes['a']['position'], original['a'])
        self.assertEqual(graph.nodes['b']['position'], original['b'])
        self.assertEqual(graph.nodes['d']['position'], original['d'])


if __name__ == '__main__':
    unittest.main()
