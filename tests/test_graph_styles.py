"""Inherited appearance, GraphML persistence, and TikZ export."""
import tempfile
import unittest
from pathlib import Path

from graph_builder_lib import convert_from_file, empty_graph, write_graph_file
from graph_styles import (DEFAULT_PRESET_ID, base_style, copy_style, effective_style, paste_style, presets,
                          remove_preset, set_edge_style, set_overrides,
                          reset_palette_style, set_palette_style, set_preset, vertex_boundary_distance)
from tikz_export import graph_to_tikz


class GraphStyleTests(unittest.TestCase):
    def test_type_zero_default_and_reset_restore_white_vertex(self):
        graph = empty_graph()
        graph.add_node('0', position=(0, 0), col=0)
        graph.add_node('1', position=(100, 0), col=0)
        self.assertEqual(base_style('vertex', 0)['fill'], '#ffffff')
        self.assertEqual(base_style('vertex', 0)['outline_width'], 2)
        source = graph_to_tikz(graph)
        self.assertIn('fill=white', source)
        self.assertIn('line width=1pt', source)
        self.assertEqual(source.count('style=vertex_0'), 2)
        set_palette_style(graph, 'vertex', 0, {'fill': '#123456'})
        self.assertEqual(effective_style(graph, 'vertex', graph.nodes['0'])['fill'], '#123456')
        reset_palette_style(graph, 'vertex', 0)
        self.assertEqual(effective_style(graph, 'vertex', graph.nodes['0'])['fill'], '#ffffff')
        self.assertNotIn('vertex_styles', graph.graph)

    def setUp(self):
        self.graph = empty_graph()
        self.graph.add_node('a', position=(0, 0), col=1, label='a')
        self.graph.add_node('b', position=(100, 0), col=1, label='b')
        self.graph.add_edge('a', 'b', col=0, label='')
        self.graph.add_edge('b', 'a', col=0, label='')

    def test_palette_preset_and_override_precedence(self):
        graph = self.graph
        set_palette_style(graph, 'vertex', 1, {'fill': '#123456', 'shape': 'square'})
        set_preset(graph, 'vertex', 'leaf', 'Leaf', {'shape': 'diamond'})
        graph.nodes['a']['style_preset'] = 'leaf'
        set_overrides(graph.nodes['a'], {'fill': '#abcdef'})
        self.assertEqual(effective_style(graph, 'vertex', graph.nodes['a'])['shape'], 'diamond')
        self.assertEqual(effective_style(graph, 'vertex', graph.nodes['a'])['fill'], '#abcdef')
        set_overrides(graph.nodes['a'], {'fill': None})
        self.assertEqual(effective_style(graph, 'vertex', graph.nodes['a'])['fill'], '#123456')
        graph.nodes['a']['col'] = 2
        self.assertNotEqual(effective_style(graph, 'vertex', graph.nodes['a'])['fill'], '#123456')
        set_preset(graph, 'vertex', 'leaf', 'Leaf', {'shape': 'triangle'})
        self.assertEqual(effective_style(graph, 'vertex', graph.nodes['a'])['shape'], 'triangle')

    def test_default_preset_follows_type_style_and_is_not_stored(self):
        graph = self.graph
        for kind in ('vertex', 'edge'):
            self.assertEqual(presets(graph, kind)[DEFAULT_PRESET_ID]['name'], 'Default style')
            self.assertNotIn(f'{kind}_presets', graph.graph)
        graph.nodes['a']['style_preset'] = DEFAULT_PRESET_ID
        set_palette_style(graph, 'vertex', 1, {'fill': '#123456'})
        self.assertEqual(effective_style(graph, 'vertex', graph.nodes['a'])['fill'], '#123456')
        graph.nodes['a']['col'] = 2
        self.assertNotEqual(effective_style(graph, 'vertex', graph.nodes['a'])['fill'], '#123456')
        remove_preset(graph, 'vertex', DEFAULT_PRESET_ID)
        self.assertIn(DEFAULT_PRESET_ID, presets(graph, 'vertex'))

    def test_delete_preset_freezes_appearance_and_copy_is_independent(self):
        graph = self.graph
        set_preset(graph, 'vertex', 'leaf', 'Leaf', {'fill': '#abcdef', 'size': 55})
        graph.nodes['a']['style_preset'] = 'leaf'
        snapshot = copy_style(graph, 'vertex', graph.nodes['a'])
        paste_style(graph.nodes['b'], snapshot)
        remove_preset(graph, 'vertex', 'leaf')
        self.assertNotIn('leaf', presets(graph, 'vertex'))
        self.assertNotIn('style_preset', graph.nodes['a'])
        self.assertEqual(effective_style(graph, 'vertex', graph.nodes['a'])['fill'], '#abcdef')
        self.assertEqual(effective_style(graph, 'vertex', graph.nodes['b'])['size'], 55)
        set_palette_style(graph, 'vertex', 1, {'fill': '#000000'})
        self.assertEqual(effective_style(graph, 'vertex', graph.nodes['b'])['fill'], '#abcdef')

    def test_undirected_edge_style_is_synchronized_and_geometry_depends_on_shape(self):
        set_edge_style(self.graph, 'a', 'b', {'stroke': '#112233', 'width': 5})
        self.assertEqual(self.graph.edges['a', 'b']['style_overrides'],
                         self.graph.edges['b', 'a']['style_overrides'])
        circle = {'shape': 'circle', 'size': 40}
        square = {'shape': 'square', 'size': 40}
        diamond = {'shape': 'diamond', 'size': 40}
        self.assertAlmostEqual(vertex_boundary_distance(circle, 1, 1), 20)
        self.assertGreater(vertex_boundary_distance(square, 1, 1), 20)
        self.assertLess(vertex_boundary_distance(diamond, 1, 1), 20)
        self.assertEqual(vertex_boundary_distance({'shape': 'none', 'size': 40}, 1, 1), 0)

    def test_graphml_round_trip_and_old_graph_compatibility(self):
        graph = self.graph
        set_palette_style(graph, 'vertex', 1, {'fill': '#abcdef'})
        set_preset(graph, 'edge', 'important', 'Important', {'width': 5})
        set_edge_style(graph, 'a', 'b', {'pattern': 'dash'}, 'important')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'styled.graphml'
            write_graph_file(graph, path)
            restored = convert_from_file(path)
            self.assertEqual(effective_style(restored, 'vertex', restored.nodes['a'])['fill'], '#abcdef')
            self.assertEqual(effective_style(restored, 'edge', restored.edges['a', 'b'])['width'], 5)
            self.assertEqual(effective_style(restored, 'edge', restored.edges['b', 'a'])['pattern'], 'dash')
            plain = empty_graph()
            plain.add_node('0', position=(0, 0), col=0)
            write_graph_file(plain, path)
            old = convert_from_file(path)
            self.assertEqual(effective_style(old, 'vertex', old.nodes['0'])['shape'], 'circle')

    def test_tikz_uses_style_latex_label_and_last_raw_options(self):
        graph = self.graph
        graph.nodes['a']['label'] = r'\\alpha'
        set_overrides(graph.nodes['a'], {'fill': 'none', 'shape': 'hollow_square',
                                         'latex_label': True,
                                         'tikz_options': 'rotate=15'})
        set_edge_style(graph, 'a', 'b', {'stroke': '#123456', 'pattern': 'dash',
                                        'tikz_options': 'opacity=.4',
                                        'label_t': .25, 'label_offset': 12})
        source = graph_to_tikz(graph)
        self.assertIn('fill=none', source)
        self.assertIn('rectangle', source)
        self.assertIn(r'\\alpha', source)
        self.assertIn('rotate=15', source)
        self.assertIn('dashed', source)
        self.assertIn('opacity=.4', source)
        self.assertLess(source.index('opacity=1.000'), source.index('opacity=.4'))


if __name__ == '__main__':
    unittest.main()
