"""Graph operations and file format checks, independent of Qt."""
import tempfile
import unittest
from math import hypot, sqrt
from pathlib import Path

import networkx as nx

from graph_builder import randomize, switch, twin
from graph_builder_custom import public_graph
from graph_info import analyze
from graph_builder_lib import (
    _edge_curve_points, _set_edge_curve_points, axis_alignment_offset,
    axis_alignment_plan, convert_from_file,
    complement, contract, copy_graph_selection, empty_graph, fuse,
    flip_horizontal, flip_vertical, paste_graph_selection, pendant, rotate,
    scale_selection, set_directed, set_edge_label,
    nearest_grid_point, radial_grid_divisions, radial_grid_new_spokes,
    triangular_grid_lines,
    triangular_grid_point, vertex_label, write_graph_file,
)
from tikz_export import graph_to_tikz, write_tikz


class GraphTests(unittest.TestCase):
    def test_axis_alignment_uses_screen_distance_and_decays_with_separation(self):
        self.assertEqual(axis_alignment_offset([(408, 106)], [(68, 100)]), (0.0, -6))
        self.assertEqual(axis_alignment_offset([(408, 110)], [(68, 100)]), (0.0, 0.0))
        self.assertEqual(axis_alignment_offset([(408, 102)], [(-4592, 100)]), (0.0, 0.0))
        self.assertEqual(axis_alignment_offset([(204, 53)], [(34, 50)], 2), (0.0, -3))

    def test_axis_alignment_can_use_different_references_for_each_coordinate(self):
        self.assertEqual(axis_alignment_offset([(105, 105)], [(100, 300), (300, 100)]),
                         (-5, -5))

    def test_axis_alignment_plan_includes_guides_and_axis_targets(self):
        offset, guides = axis_alignment_plan([(300, 106)], [(200, 100)])
        self.assertEqual(offset, (0.0, -6))
        self.assertEqual(guides, (((200, 100), (300, 100)),))
        offset, guides = axis_alignment_plan([(6, 7)], [],
                                             axis_visible=(True, True),
                                             origin_visible=True)
        self.assertEqual(offset, (-6, -7))
        self.assertEqual(guides, (((0.0, 0.0), (0.0, 7)),
                                  ((0.0, 0.0), (6, 0.0))))
        self.assertEqual(axis_alignment_plan([(200, 5)], [],
                                             axis_visible=(False, True))[0],
                         (0.0, -5))
        self.assertEqual(axis_alignment_plan([(6, 7)], [])[0], (0.0, 0.0))

    def test_axis_alignment_plan_can_report_guide_sources(self):
        offsets, guides, matches = axis_alignment_plan(
            [(300, 106)], [(200, 100)], include_matches=True)
        self.assertEqual(offsets, (0.0, -6))
        self.assertEqual(guides, (((200, 100), (300, 100)),))
        self.assertEqual(matches, ((0, 0),))
        _, _, virtual_matches = axis_alignment_plan(
            [(6, 7)], [], axis_visible=(True, True),
            origin_visible=True, include_matches=True)
        self.assertEqual(virtual_matches, ((0, None), (0, None)))

    def test_directed_pair_keeps_lower_id_arc_when_made_undirected(self):
        graph = empty_graph(graph_type='digraph')
        graph.add_node('a', position=(0, 0), col=0)
        graph.add_node('b', position=(100, 0), col=0)
        graph.add_edge('b', 'a', label='newer', col=2, style_overrides='{"width": 8}')
        graph.add_edge('a', 'b', label='older', col=1, style_overrides='{"width": 3}')
        _set_edge_curve_points(graph, 'a', 'b', [(30, 25), (70, 20)])
        set_directed(graph, False)
        self.assertEqual(graph.graph['graph_type'], 'graph')
        for source, target in (('a', 'b'), ('b', 'a')):
            self.assertEqual(graph.edges[source, target]['label'], 'older')
            self.assertEqual(graph.edges[source, target]['col'], 1)
            self.assertEqual(graph.edges[source, target]['style_overrides'], '{"width": 3}')
        self.assertEqual(_edge_curve_points(graph, 'a', 'b'), [(30, 25), (70, 20)])
        self.assertEqual(_edge_curve_points(graph, 'b', 'a'), [(70, 20), (30, 25)])

    def test_single_directed_arc_survives_undirected_conversion(self):
        graph = empty_graph(graph_type='digraph')
        graph.add_node('a', position=(0, 0))
        graph.add_node('b', position=(100, 0))
        graph.add_edge('b', 'a', label='only arc', col=1)
        set_directed(graph, False)
        self.assertEqual(graph.edges['a', 'b']['label'], 'only arc')
        self.assertEqual(graph.edges['b', 'a']['label'], 'only arc')

    def test_directed_conversion_orders_numeric_internal_ids_numerically(self):
        graph = empty_graph(graph_type='digraph')
        graph.add_node('2', position=(0, 0))
        graph.add_node('10', position=(100, 0))
        graph.add_edge('10', '2', label='reverse')
        graph.add_edge('2', '10', label='forward')
        set_directed(graph, False)
        self.assertEqual(graph.edges['2', '10']['label'], 'forward')
        self.assertEqual(graph.edges['10', '2']['label'], 'forward')

    def test_pendant_grows_outward_and_repeated_uses_extend_a_tree(self):
        graph = empty_graph()
        graph.add_node('0', position=(0, 0), col=0)
        graph.add_node('1', position=(100, 0), col=0)
        graph.add_edge('0', '1', col=0)
        graph.add_edge('1', '0', col=0)
        first = pendant(graph, {'1'}, vertex_color=2, edge_color=1)
        self.assertEqual(len(first), 1)
        child = next(iter(first))
        self.assertAlmostEqual(graph.nodes[child]['position'][0], 200)
        self.assertAlmostEqual(graph.nodes[child]['position'][1], 0)
        self.assertEqual(graph.nodes[child]['col'], 2)
        self.assertTrue(graph.has_edge('1', child))
        self.assertTrue(graph.has_edge(child, '1'))
        self.assertEqual(graph.edges['1', child]['col'], 1)
        grandchild = next(iter(pendant(graph, first)))
        self.assertAlmostEqual(graph.nodes[grandchild]['position'][0], 300)
        self.assertAlmostEqual(graph.nodes[grandchild]['position'][1], 0)
        self.assertEqual(graph.degree[grandchild], 2)

    def test_pendant_uses_one_arc_in_directed_graph(self):
        graph = empty_graph(graph_type='digraph')
        graph.add_node('root', position=(0, 0), col=1)
        child = next(iter(pendant(graph, {'root'})))
        self.assertTrue(graph.has_edge('root', child))
        self.assertFalse(graph.has_edge(child, 'root'))
        self.assertEqual(graph.nodes[child]['col'], 1)

    def test_pendant_adds_distinct_leaves_for_every_selected_parent(self):
        graph = empty_graph()
        graph.add_node('left', position=(-50, 0), col=0)
        graph.add_node('right', position=(50, 0), col=0)
        graph.add_edge('left', 'right', col=0)
        graph.add_edge('right', 'left', col=0)
        leaves = pendant(graph, {'left', 'right'})
        self.assertEqual(len(leaves), 2)
        self.assertEqual(graph.number_of_nodes(), 4)
        self.assertEqual(len({graph.nodes[node]['position'] for node in leaves}), 2)
        self.assertEqual({parent for node in leaves for parent in graph.successors(node)},
                         {'left', 'right'})

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

    def test_one_unit_radial_spokes_keep_their_starting_radius(self):
        spokes = list(radial_grid_new_spokes(4 * 136, 136, 5))
        self.assertIn((2 * 136, 1, 10), spokes)
        self.assertIn((3 * 136, 1, 20), spokes)
        self.assertNotIn((136, 1, 10), spokes)

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
        self.assertTrue(any(line.startswith('Degree min / avg / max:')
                            for line in analyze(public_graph(contracted), 'Overview')))

    def test_twins_share_one_offset_and_keep_original_neighbors(self):
        graph = empty_graph()
        for node, position in [('0', (0, 0)), ('1', (50, 0)), ('2', (100, 0))]:
            graph.add_node(node, position=position, col=1)
        graph.add_edges_from([('0', '1'), ('1', '0'), ('1', '2'), ('2', '1')])
        _, added = twin(graph, {'0', '1'}, return_new_vertices=True)
        self.assertEqual(added, {'3', '4'})
        self.assertEqual(graph.nodes['3']['position'], (20, 20))
        self.assertEqual(graph.nodes['4']['position'], (70, 20))
        self.assertTrue(graph.has_edge('3', '1') and graph.has_edge('1', '3'))
        self.assertTrue(graph.has_edge('4', '0') and graph.has_edge('0', '4'))
        self.assertFalse(graph.has_edge('3', '4'))

    def test_fuse_only_nearby_groups_and_retains_representative_properties(self):
        graph = empty_graph()
        for node, position in [('0', (0, 0)), ('1', (3, 4)),
                               ('2', (50, 0)), ('3', (51, 0)), ('4', (100, 0))]:
            graph.add_node(node, position=position, col=int(node), label=f'V{node}')
        graph.nodes['0']['style_overrides'] = '{"size": 42}'
        graph.add_edge('0', '4', col=1)
        graph.add_edge('4', '0', col=1)
        result, added = fuse(graph, {'0', '1', '2', '3', '4'})
        self.assertEqual(added, {'5', '6'})
        self.assertEqual(set(result), {'4', '5', '6'})
        self.assertEqual(result.nodes['5']['label'], 'V0')
        self.assertEqual(result.nodes['5']['style_overrides'], '{"size": 42}')
        self.assertEqual(result.nodes['5']['position'], (1.5, 2.0))
        self.assertTrue(result.has_edge('5', '4'))

    def test_single_vertex_fuse_includes_unselected_nearby_vertices(self):
        graph = empty_graph()
        for node, position in [('0', (0, 0)), ('1', (2, 0)), ('2', (20, 0))]:
            graph.add_node(node, position=position, col=int(node))
        result, added = fuse(graph, {'1'})
        self.assertEqual(added, {'3'})
        self.assertEqual(set(result), {'2', '3'})
        self.assertEqual(result.nodes['3']['col'], 1)
        self.assertEqual(result.nodes['3']['position'], (1.0, 0.0))

    def test_fuse_without_selection_scans_whole_graph_at_ten_unit_tolerance(self):
        graph = empty_graph()
        for node, position in [('0', (0, 0)), ('1', (9, 0)),
                               ('2', (30, 0)), ('3', (41, 0))]:
            graph.add_node(node, position=position, col=0)
        result, added = fuse(graph, set())
        self.assertEqual(added, {'4'})
        self.assertEqual(set(result), {'2', '3', '4'})
        self.assertEqual(result.nodes['4']['position'], (4.5, 0.0))

    def test_fuse_does_not_chain_vertices_beyond_tolerance(self):
        graph = empty_graph()
        for node, position in [('0', (0, 0)), ('1', (-9, 0)), ('2', (9, 0))]:
            graph.add_node(node, position=position, col=0)
        result, added = fuse(graph, set())
        self.assertEqual(len(added), 1)
        self.assertEqual(len(result), 2)
        result, added = fuse(graph, {'0'})
        self.assertEqual(len(added), 1)
        self.assertEqual(len(result), 2)

    def test_transform_selection_moves_only_selected_vertices_and_internal_curves(self):
        graph = empty_graph(graph_type='graph')
        graph.add_node('0', position=(0, 0), col=0)
        graph.add_node('1', position=(10, 0), col=0)
        graph.add_node('2', position=(20, 0), col=0)
        graph.add_edge('0', '1', col=0)
        graph.add_edge('1', '0', col=0)
        graph.add_edge('1', '2', col=0)
        graph.add_edge('2', '1', col=0)
        _set_edge_curve_points(graph, '0', '1', [(5, 2)])
        _set_edge_curve_points(graph, '1', '2', [(15, 2)])
        rotate(graph, {'0', '1'}, 90)
        self.assertAlmostEqual(graph.nodes['0']['position'][0], 5)
        self.assertAlmostEqual(graph.nodes['0']['position'][1], -5)
        self.assertAlmostEqual(graph.nodes['1']['position'][0], 5)
        self.assertAlmostEqual(graph.nodes['1']['position'][1], 5)
        self.assertEqual(graph.nodes['2']['position'], (20, 0))
        point = _edge_curve_points(graph, '0', '1')[0]
        self.assertAlmostEqual(point[0], 3)
        self.assertAlmostEqual(point[1], 0)
        self.assertEqual(_edge_curve_points(graph, '1', '2'), [(15, 2)])

    def test_reflections_and_half_turn_share_selection_center(self):
        graph = empty_graph(graph_type='graph')
        graph.add_node('0', position=(0, 0), col=0)
        graph.add_node('1', position=(10, 20), col=0)
        graph.add_node('2', position=(30, 40), col=0)
        flip_horizontal(graph, {'0', '1'})
        self.assertEqual(graph.nodes['0']['position'], (10, 0))
        self.assertEqual(graph.nodes['1']['position'], (0, 20))
        flip_vertical(graph, {'0', '1'})
        self.assertEqual(graph.nodes['0']['position'], (10, 20))
        self.assertEqual(graph.nodes['1']['position'], (0, 0))
        rotate(graph, {'0', '1'}, 180)
        self.assertAlmostEqual(graph.nodes['0']['position'][0], 0)
        self.assertAlmostEqual(graph.nodes['0']['position'][1], 0)
        self.assertAlmostEqual(graph.nodes['1']['position'][0], 10)
        self.assertAlmostEqual(graph.nodes['1']['position'][1], 20)
        self.assertEqual(graph.nodes['2']['position'], (30, 40))

    def test_grow_and_shrink_move_internal_curves_but_not_boundary_curves(self):
        graph = empty_graph()
        for node, x in (('0', 0), ('1', 10), ('2', 20)):
            graph.add_node(node, position=(x, 0), col=0)
        for source, target in (('0', '1'), ('1', '2')):
            graph.add_edge(source, target, col=0)
            graph.add_edge(target, source, col=0)
        _set_edge_curve_points(graph, '0', '1', [(5, 2)])
        _set_edge_curve_points(graph, '1', '2', [(15, 2)])
        scale_selection(graph, {'0', '1'}, 1.1)
        self.assertAlmostEqual(graph.nodes['0']['position'][0], -.5)
        self.assertAlmostEqual(graph.nodes['1']['position'][0], 10.5)
        self.assertEqual(graph.nodes['2']['position'], (20, 0))
        internal = _edge_curve_points(graph, '0', '1')[0]
        self.assertAlmostEqual(internal[0], 5)
        self.assertAlmostEqual(internal[1], 2.2)
        self.assertEqual(_edge_curve_points(graph, '1', '2'), [(15, 2)])
        scale_selection(graph, {'0', '1'}, 1 / 1.1)
        self.assertAlmostEqual(graph.nodes['0']['position'][0], 0)
        self.assertAlmostEqual(graph.nodes['1']['position'][0], 10)
        self.assertAlmostEqual(_edge_curve_points(graph, '0', '1')[0][1], 2)
        self.assertEqual(_edge_curve_points(graph, '1', '2'), [(15, 2)])

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
