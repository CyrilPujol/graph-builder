"""Graph information semantics and its bounded, read-only UI path."""
import copy
import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import networkx as nx
from PySide6.QtCore import QPointF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from graph_builder_custom import public_graph
from graph_builder_lib import empty_graph
from graph_builder_qt import GraphBuilderQt
from graph_info import analyze, graph_from_payload, topology_payload


class GraphInfoTests(unittest.TestCase):
    def test_undirected_arcs_are_counted_once(self):
        internal = empty_graph()
        internal.add_nodes_from(('a', 'b'))
        internal.add_edge('a', 'b')
        internal.add_edge('b', 'a')
        graph = public_graph(internal)
        lines = analyze(graph, 'Overview')
        self.assertIn('Edges: 1', lines)
        self.assertIn('Density: 1.000', lines)
        self.assertEqual(graph_from_payload(topology_payload(graph)).number_of_edges(), 1)

    def test_disconnected_distances_are_infinite(self):
        graph = nx.Graph()
        graph.add_nodes_from((0, 1))
        self.assertEqual(analyze(graph, 'Distances'),
                         ['Diameter: ∞ (disconnected)', 'Radius: ∞',
                          'Mean shortest-path length: ∞'])
        directed = nx.DiGraph([(0, 1)])
        self.assertIn('Diameter: ∞ (not strongly connected)', analyze(directed, 'Distances'))
        self.assertIn('Radius: ∞', analyze(directed, 'Distances'))
        self.assertIn('Mean shortest-path length: ∞', analyze(directed, 'Distances'))
        self.assertEqual(analyze(nx.Graph(), 'Distances')[0], 'Diameter: — (empty graph)')
        self.assertEqual(analyze(nx.path_graph(1), 'Distances'),
                         ['Diameter: 0', 'Radius: 0', 'Mean shortest-path length: 0.000'])

    def test_exact_and_sampled_distances(self):
        self.assertEqual(analyze(nx.path_graph(5), 'Distances'),
                         ['Diameter: 4', 'Radius: 2', 'Mean shortest-path length: 2.000'])
        lines = analyze(nx.path_graph(125), 'Distances')
        self.assertIn('Diameter: ≥ 124', lines[0])
        self.assertTrue(lines[1].startswith('Radius: ≤ '))
        self.assertIn('≈', lines[2])
        self.assertIn('24 sampled sources', lines[2])
        self.assertEqual(len(lines), 3)

    def test_directed_radius_uses_outgoing_distances(self):
        graph = nx.DiGraph([(0, 1), (1, 2), (2, 0), (2, 1)])
        lines = analyze(graph, 'Distances')
        self.assertIn('Radius: 1', lines)
        self.assertIn('Diameter: 2', lines)

    def test_structure_and_bounds_keep_their_meaning(self):
        cycle = nx.cycle_graph(5)
        structure = analyze(cycle, 'Structure')
        self.assertIn('Components: 1 (largest: 5)', structure)
        self.assertIn('Planar: Yes', structure)
        self.assertIn('Bipartite: No', structure)
        self.assertFalse(any('Isolated' in line or 'Bridge' in line or 'Articulation' in line
                             for line in structure + analyze(cycle, 'Overview')))
        lines = analyze(nx.complete_graph(4), 'Bounds')
        self.assertIn('Clique number ω: ≥ 4', lines[0])
        self.assertIn('Independence number α: ≥ 1', lines[1])
        self.assertEqual(lines[2], 'Chromatic number: 4 ≤ χ ≤ 4')
        directed = nx.DiGraph([(0, 1), (1, 0)])
        self.assertIn('Strong components: 1 (largest: 2)', analyze(directed, 'Structure'))
        self.assertTrue(analyze(directed, 'Structure')[-1].startswith('Bipartite'))


class GraphInfoQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = GraphBuilderQt()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.scene.selectionChanged.disconnect(self.window.selection_changed)
        if self.window._info_process is not None:
            self.window._invalidate_info()
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()

    def wait_for_result(self):
        for _ in range(100):
            if self.window._info_has_result:
                return
            QTest.qWait(20)
        self.fail('Graph information worker did not finish')

    def test_info_menu_selection_and_stale_results(self):
        tabs = self.window.menu_tabs
        self.assertEqual(tabs.tabText(6), 'Info')
        self.window.add_node(QPointF(0, 0))
        self.window.add_node(QPointF(100, 0))
        self.window.show_graph_info('Overview')
        self.assertIn('Vertices: 2', self.window.info_text.toPlainText())
        self.window.copy_graph_info()
        self.assertIn('Vertices: 2', QApplication.clipboard().text())
        self.window.add_node(QPointF(200, 0))
        self.assertIn('Outdated', self.window.info_text.toPlainText())
        self.window.info_scope.setCurrentIndex(1)
        self.assertFalse(self.window.info_actions['Overview'].isEnabled())
        self.window.node_items['0'].setSelected(True)
        self.assertTrue(self.window.info_actions['Overview'].isEnabled())
        self.window.show_graph_info('Overview')
        self.assertIn('1 selected vertices', self.window.info_text.toPlainText())
        self.assertIn('Vertices: 1', self.window.info_text.toPlainText())
        self.window.node_items['0'].setSelected(False)
        self.assertIn('Outdated', self.window.info_text.toPlainText())

    def test_worker_returns_infinity_and_time_limit(self):
        self.window.add_node(QPointF(0, 0))
        self.window.add_node(QPointF(100, 0))
        before = copy.deepcopy(self.window.graph)
        self.window.show_graph_info('Distances')
        self.wait_for_result()
        self.assertIn('Diameter: ∞', self.window.info_text.toPlainText())
        self.assertTrue(nx.utils.graphs_equal(self.window.graph, before))
        with patch('graph_builder_qt.ANALYSIS_TIMEOUT_MS', 1):
            self.window.show_graph_info('Bounds')
            self.wait_for_result()
        self.assertIn('Not computed within', self.window.info_text.toPlainText())
        self.assertTrue(nx.utils.graphs_equal(self.window.graph, before))


if __name__ == '__main__':
    unittest.main()
