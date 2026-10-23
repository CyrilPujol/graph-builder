"""Graph operations and file format checks, independent of Qt."""
import tempfile
import unittest
from math import hypot, sqrt
from pathlib import Path

import networkx as nx

from graph_builder import complement, contract, degree_summary, randomize, rotate, switch, twin
from graph_builder_lib import (
    _edge_curve_points, _set_edge_curve_points, convert_from_file,
    copy_graph_selection, empty_graph, paste_graph_selection, set_edge_label,
    nearest_grid_point, radial_grid_divisions, triangular_grid_lines,
    triangular_grid_point, vertex_label, write_graph_file,
)
from tikz_export import graph_to_tikz, write_tikz


class GraphTests(unittest.TestCase):
    def test_triangular_grid_nearest_point_and_negative_ties(self):
        unit = 20
        height = unit * sqrt(3) / 2
        self.assertEqual(nearest_grid_point((10, 0), 'triangular', unit=unit), (0, 0))
        self.assertEqual(nearest_grid_point((-10, 0), 'triangular', unit=unit), (-20, 0))
        self.assertEqual(nearest_grid_point((11, height - 1), 'triangular', unit=unit),
                         triangular_grid_point(0, 1, unit=unit))
        self.assertEqual(nearest_grid_point((-11, -height + 1), 'triangular', unit=unit),
                         triangular_grid_point(0, -1, unit=unit))

    def test_triangular_grid_precision_is_nested_and_lines_match_points(self):
        unit = 20
        for i, j in ((0, 0), (1, -2), (-3, 4)):
            point = triangular_grid_point(i, j, unit=2 * unit)
            self.assertEqual(point, triangular_grid_point(2 * i, 2 * j, unit=unit))
            self.assertEqual(nearest_grid_point(point, 'triangular', unit=unit), point)
        lines = list(triangular_grid_lines((-50, -50, 50, 50), unit=unit))
        self.assertEqual({family for family, index, _, _ in lines if index == 0},
                         {0, 1, 2})
        point = triangular_grid_point(1, 0, unit=unit)
        for family, index in ((0, 0), (1, 1), (2, 1)):
            _, _, start, end = next(line for line in lines if line[:2] == (family, index))
            cross = ((point[0] - start[0]) * (end[1] - start[1]) -
                     (point[1] - start[1]) * (end[0] - start[0]))
            self.assertAlmostEqual(cross, 0)
            self.assertLessEqual(hypot(point[0] - start[0], point[1] - start[1]),
                                 hypot(end[0] - start[0], end[1] - start[1]))

    def test_radial_grid_uses_square_cell_threshold(self):
        self.assertEqual(radial_grid_divisions(3, 5), 20)

    def test_graphml_round_trip_preserves_graph_and_item_attributes(self):
        graph = empty_graph(graph_type='graph', num_edge_colors=3, num_vertex_colors=4)
        graph.add_node('a', position=(1.5, 2.5), col=2, label='same')
        graph.add_node('b', position=(3.0, 4.0), col=1, label='same')
        graph.add_edge('a', 'b', col=2)
        graph.add_edge('b', 'a', col=2)
        set_edge_label(graph, 'a', 'b', 'e_1')
        _set_edge_curve_points(graph, 'a', 'b', [(2.0, 1.0)])
        with tempfile.TemporaryDirectory() as folder:
            path = write_graph_file(graph, Path(folder) / 'drawing.graphml')
            loaded = convert_from_file(path)
        self.assertEqual(loaded.nodes['a']['position'], (1.5, 2.5))
        self.assertEqual(loaded.nodes['a']['col'], 2)
        self.assertEqual(vertex_label(loaded, 'a'), vertex_label(loaded, 'b'))
        self.assertEqual(loaded.edges['a', 'b']['col'], 2)
        self.assertEqual(loaded.edges['b', 'a']['label'], 'e_1')
        self.assertEqual(len(_edge_curve_points(loaded, 'a', 'b')), 1)
        self.assertEqual(loaded.graph['num_edge_colors'], 3)

    def test_import_plain_undirected_graphml_creates_paired_arcs(self):
        graph = nx.Graph()
        graph.add_node('a', position_x=0, position_y=0)
        graph.add_node('b', position_x=40, position_y=0)
        graph.add_edge('a', 'b', col=1, label='edge')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'plain.graphml'
            nx.write_graphml(graph, path)
            loaded = convert_from_file(path)
        self.assertTrue(loaded.has_edge('a', 'b'))
        self.assertTrue(loaded.has_edge('b', 'a'))
        self.assertEqual(loaded.edges['b', 'a']['label'], 'edge')

    def test_tikz_export_uses_visible_labels_and_escapes_latex(self):
        graph = empty_graph(graph_type='graph')
        graph.add_node('internal-a', position=(0, 0), col=0, label='x_1')
        graph.add_node('internal-b', position=(10, 0), col=1, label='x_1')
        graph.add_edge('internal-a', 'internal-b', col=0)
        graph.add_edge('internal-b', 'internal-a', col=0)
        set_edge_label(graph, 'internal-a', 'internal-b', 'e_1')
        with tempfile.TemporaryDirectory() as folder:
            output = write_tikz(graph, Path(folder) / 'drawing.tex')
            tikz = output.read_text(encoding='utf-8')
        self.assertIn(r'\begin{tikzpicture}', tikz)
        self.assertIn(r'{x\_1}', tikz)
        self.assertIn(r'{e\_1}', tikz)
        self.assertEqual(tikz, graph_to_tikz(graph))
        graph.graph['show_labels'] = False
        hidden_tikz = graph_to_tikz(graph)
        self.assertNotIn(r'x\_1', hidden_tikz)
        self.assertNotIn(r'e\_1', hidden_tikz)

    def test_transformations_keep_undirected_pairs(self):
        graph = nx.DiGraph(graph_type='graph', num_edge_colors=3, num_vertex_colors=4)
        for node, position in [('0', (0, 0)), ('1', (20, 0)), ('2', (40, 0))]:
            graph.add_node(node, position=position, col=1)
        graph.add_edge('0', '1', col=0)
        graph.add_edge('1', '0', col=0)

        twin(graph, {'0', '1'})
        self.assertEqual(graph.number_of_nodes(), 5)
        self.assertTrue(graph.has_edge('3', '1') and graph.has_edge('1', '3'))
        self.assertTrue(graph.has_edge('4', '0') and graph.has_edge('0', '4'))
        switch(graph, {'0'})
        self.assertEqual(graph.edges['0', '1']['col'], graph.edges['1', '0']['col'])
        switch(graph, {'0', '1'})
        self.assertEqual(graph.edges['0', '1']['col'], graph.edges['1', '0']['col'])
        complement(graph, {'0', '2'})
        self.assertTrue(graph.has_edge('0', '2') and graph.has_edge('2', '0'))
        contracted = contract(graph, {'0', '1'})
        self.assertEqual(contracted.number_of_nodes(), 4)
        self.assertIn('Degree', degree_summary(contracted))

    def test_rotate_moves_edge_curve_points(self):
        graph = empty_graph(graph_type='graph')
        graph.add_node('0', position=(0, 0), col=0)
        graph.add_node('1', position=(10, 0), col=0)
        graph.add_edge('0', '1', col=0)
        graph.add_edge('1', '0', col=0)
        _set_edge_curve_points(graph, '0', '1', [(5, 2)])
        rotate(graph, {'0'}, 90)
        self.assertAlmostEqual(graph.nodes['1']['position'][0], 0)
        self.assertAlmostEqual(graph.nodes['1']['position'][1], 10)
        point = _edge_curve_points(graph, '0', '1')[0]
        self.assertAlmostEqual(point[0], -2)
        self.assertAlmostEqual(point[1], 5)

    def test_randomize_changes_only_induced_edges(self):
        graph = empty_graph(graph_type='graph')
        for node in ('0', '1', '2'):
            graph.add_node(node, position=(0, 0), col=0)
        graph.add_edge('0', '2', col=1)
        graph.add_edge('2', '0', col=1)
        randomize(graph, {'0', '1'}, random_source=lambda: .25)
        self.assertTrue(graph.has_edge('0', '1') and graph.has_edge('1', '0'))
        self.assertTrue(graph.has_edge('0', '2') and graph.has_edge('2', '0'))

    def test_copy_paste_keeps_internal_and_boundary_edges(self):
        graph = empty_graph()
        for node, x in (('0', 0), ('1', 30), ('2', 60)):
            graph.add_node(node, position=(x, 0), col=0)
        graph.add_edges_from((('0', '1'), ('1', '0'), ('0', '2'), ('2', '0')))
        clipboard = copy_graph_selection(graph, {'0', '1'})
        pasted, new_nodes = paste_graph_selection(graph, clipboard, (20, -20))
        self.assertEqual(new_nodes, {'3', '4'})
        self.assertTrue(pasted.has_edge('3', '4') and pasted.has_edge('4', '3'))
        self.assertTrue(pasted.has_edge('3', '2') and pasted.has_edge('2', '3'))
        self.assertEqual(pasted.nodes['3']['position'], (20, -20))


if __name__ == '__main__':
    unittest.main()
