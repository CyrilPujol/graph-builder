"""Cross-feature checks for styled graphs, custom actions, files and canvas."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from graph_builder_lib import (_edge_curve_points, _set_edge_curve_points, button,
                               convert_from_file, write_graph_file)
from graph_builder_qt import GraphBuilderQt
from graph_styles import effective_style, set_overrides, set_palette_style
from tikz_export import graph_to_tikz


class FeatureIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = GraphBuilderQt()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.scene.selectionChanged.disconnect(self.window.selection_changed)
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()

    def test_style_types_refresh_vertex_geometry(self):
        window = self.window
        window.add_node(QPointF(0, 0))
        set_palette_style(window.graph, 'vertex', 1,
                          {'shape': 'square', 'size': 90, 'fill': '#abcdef'})
        window.last_canvas_position = QPointF(0, 0)
        old_width = window.node_items['0'].boundingRect().width()
        window.change_type(1)
        self.assertEqual(window.graph.nodes['0']['col'], 1)
        self.assertGreater(window.node_items['0'].boundingRect().width(), old_width)
        window.change_vertex_colors(1)
        self.assertEqual(window.graph.nodes['0']['col'], 0)
        self.assertLess(window.node_items['0'].boundingRect().width(), 90)

    def test_edge_creation_preview_uses_type_style(self):
        window = self.window
        window.add_node(QPointF(10, 10))
        set_palette_style(window.graph, 'edge', 0,
                          {'stroke': '#ee1188', 'width': 5, 'pattern': 'solid'})
        window.scene.edge_sources = ('0',)
        window.scene.edge_position = QPointF(90, 10)
        image = QImage(100, 25, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.white)
        painter = QPainter(image)
        window.scene.drawForeground(painter, QRectF(0, 0, 100, 25))
        painter.end()
        self.assertEqual(image.pixelColor(50, 10), QColor('#ee1188'))

    def test_directed_styles_custom_function_round_trip_and_undo(self):
        window = self.window
        window.add_node(QPointF(0, 0))
        window.add_node(QPointF(100, 0))
        set_palette_style(window.graph, 'vertex', 1,
                          {'fill': '#abcdef', 'shape': 'square'})
        set_palette_style(window.graph, 'edge', 1,
                          {'stroke': '#123456', 'pattern': 'dash'})
        window.graph.nodes['0']['col'] = 1
        set_overrides(window.graph.nodes['0'], {'latex_label': True})
        window.graph.nodes['0']['label'] = r'\alpha'
        window.set_directed(True)
        window.graph.add_edge('0', '1', col=1, label='arc')
        _set_edge_curve_points(window.graph, '0', '1', [(50, 30)])
        window.rebuild_scene()
        window.commit_change()

        @button('Extend')
        def extend(graph):
            graph.add_edge('1', 'new', col=1)

        before = window._history_index
        window.run_extension(extend.__graph_button__)
        self.assertEqual(window._history_index, before + 1)
        self.assertEqual(window.selection.nodes, {'new'})
        self.assertEqual(window.graph.nodes['new']['col'], 0)
        self.assertEqual(effective_style(window.graph, 'vertex', window.graph.nodes['0'])['fill'],
                         '#abcdef')
        self.assertEqual(effective_style(window.graph, 'edge', window.graph.edges['1', 'new'])['stroke'],
                         '#123456')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'combined.graphml'
            write_graph_file(window.graph, path)
            restored = convert_from_file(path)
        self.assertEqual(restored.graph['graph_type'], 'digraph')
        self.assertEqual(restored.nodes['0']['label'], r'\alpha')
        self.assertEqual(effective_style(restored, 'vertex', restored.nodes['0'])['shape'], 'square')
        self.assertEqual(effective_style(restored, 'edge', restored.edges['1', 'new'])['pattern'], 'dash')
        self.assertEqual(_edge_curve_points(restored, '0', '1'), [(50, 30)])
        tikz = graph_to_tikz(restored)
        self.assertIn(r'\alpha', tikz)
        self.assertIn('123456', tikz)
        self.assertIn('dashed', tikz)
        self.assertIn('plot coordinates', tikz)
        self.assertIn('->', tikz)
        window.undo()
        self.assertNotIn('new', window.graph)
        window.redo()
        self.assertIn('new', window.graph)

    def test_standard_graph_inherits_type_style_without_replacing_document(self):
        window = self.window
        window.add_node(QPointF(300, 100))
        set_palette_style(window.graph, 'vertex', 2,
                          {'fill': '#456789', 'shape': 'diamond'})
        window.vertex_color = 2
        original = set(window.graph)
        added = window.add_standard_graph('path', {'n': 3})
        self.assertEqual(len(added), 3)
        self.assertTrue(original <= set(window.graph))
        self.assertEqual(window.selection.nodes, added)
        self.assertTrue(all(effective_style(window.graph, 'vertex', window.graph.nodes[node])['shape']
                            == 'diamond' for node in added))
        window.undo()
        self.assertEqual(set(window.graph), original)


if __name__ == '__main__':
    unittest.main()
