"""The user extension boundary: normal NetworkX input, repair, and rollback."""
import copy
import math
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import networkx as nx
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPointF, QTimer

from graph_builder_custom import normalize_graph, public_graph
from graph_builder_lib import (button, discover_buttons, main, edit_graph, empty_graph, EdgeRef,
                               EditorContext, SelectionState, execute_action,
                               _edge_curve_points, _set_edge_curve_points,
                               write_graph_file, convert_from_file)
from graph_builder_qt import GraphBuilderQt
from tikz_export import graph_to_tikz


class CustomButtonTests(unittest.TestCase):
    def setUp(self):
        graph = empty_graph()
        graph.add_node('0', position=(10, 20), col=1, label='existing')
        graph.add_node('1', position=(110, 20), col=0)
        graph.add_edge('0', '1', col=1, label='edge')
        graph.add_edge('1', '0', col=1, label='edge')
        self.context = EditorContext(graph, SelectionState(), None)

    def run_button(self, function):
        return execute_action(function.__graph_button__, self.context)

    def test_discovery_names_and_explicit_registration(self):
        @button
        def color_graph(graph):
            return graph
        self.assertEqual(color_graph.__graph_button__.name, 'Color graph')
        self.assertIs(color_graph(self.context.graph), self.context.graph)
        self.assertEqual(discover_buttons({'one': color_graph, 'alias': color_graph, 'ignored': lambda g: g}),
                         [color_graph.__graph_button__])
        with patch('graph_builder_qt.launch') as launch:
            main(actions=[color_graph], graph_file='example.graphml')
            self.assertEqual(launch.call_args.kwargs['actions'], [color_graph.__graph_button__])
            globals()['_test_button'] = color_graph
            try:
                main(graph_file='example.graphml')
                self.assertIn(color_graph.__graph_button__, launch.call_args.kwargs['actions'])
            finally:
                del globals()['_test_button']

    def test_edit_graph_returns_an_independent_graph(self):
        original = nx.Graph()
        original.add_edge('a', 'b')
        original.graph['show_labels'] = False
        app = QApplication.instance() or QApplication([])

        def finish():
            window = next(widget for widget in app.topLevelWidgets()
                          if isinstance(widget, GraphBuilderQt) and widget.isVisible())
            window.add_node(QPointF(50, 50))
            window.close()

        QTimer.singleShot(0, finish)
        with patch('graph_builder_qt.QMessageBox.question', side_effect=AssertionError('Unexpected save prompt')):
            result = edit_graph(original, actions=[])
        self.assertIs(type(result), nx.Graph)
        self.assertEqual(len(result), 3)
        self.assertEqual(set(original), {'a', 'b'})
        self.assertFalse(result.graph['show_labels'])
        self.assertEqual(result.nodes['a']['label'], 'a')

    def test_edit_graph_handles_empty_and_directed_inputs(self):
        app = QApplication.instance() or QApplication([])

        def finish():
            window = next(widget for widget in app.topLevelWidgets()
                          if isinstance(widget, GraphBuilderQt) and widget.isVisible())
            window.close()

        for source, kind in ((None, nx.Graph), (nx.DiGraph([(0, 1)]), nx.DiGraph)):
            QTimer.singleShot(0, finish)
            result = edit_graph(source, actions=[])
            self.assertIs(type(result), kind)
        with self.assertRaisesRegex(TypeError, 'NetworkX Graph'):
            edit_graph('not a graph', actions=[])

    def test_ordinary_graph_in_place_mutation_and_missing_attributes(self):
        original = copy.deepcopy(self.context.graph)
        @button
        def add(graph: str):  # Wrong annotation does not restrict Python values.
            self.assertIs(type(graph), nx.Graph)
            self.assertEqual(graph.number_of_edges(), 1)
            graph.add_edge('0', ('new', 1))
        self.run_button(add)
        graph = self.context.graph
        self.assertEqual(graph.nodes['0'], original.nodes['0'])
        self.assertEqual(self.context.selection.nodes, {'2'})
        self.assertEqual(graph.nodes['2']['label'], "('new', 1)")
        self.assertEqual(graph.nodes['2']['col'], 0)
        self.assertEqual(graph.edges['0', '2']['label'], '')
        self.assertEqual(graph.edges['0', '2'], graph.edges['2', '0'])
        self.assertGreaterEqual(math.dist(graph.nodes['2']['position'], graph.nodes['0']['position']), 45)

    def test_fresh_graph_preserves_settings_existing_attributes_and_unique_ids(self):
        @button('Replacement', shortcut='G')
        def replace(graph):
            result = nx.Graph()
            result.add_nodes_from(['0', '2', 2, (2,)])
            result.add_edge('0', 2, col='6')
            return result
        self.run_button(replace)
        graph = self.context.graph
        self.assertEqual(len(graph), 4)
        self.assertTrue(all(isinstance(n, str) for n in graph))
        self.assertEqual(graph.nodes['0']['position'], (10, 20))
        self.assertEqual(graph.graph['num_vertex_colors'], 4)
        self.assertEqual(graph.graph['num_edge_colors'], 7)
        self.assertEqual(len(self.context.selection.nodes), 3)

    def test_numeric_coercion_curves_and_file_round_trip(self):
        _set_edge_curve_points(self.context.graph, '0', '1', [(35, 70), (85, -10)])
        @button
        def edit(graph):
            graph.nodes['0']['position'] = ['10', '20']
            graph.nodes['0']['col'] = '2'
            # Reverse iteration order without changing node identities.
            result = nx.Graph()
            result.add_nodes_from(reversed(list(graph.nodes(data=True))))
            result.add_edges_from(graph.edges(data=True))
            return result
        self.run_button(edit)
        graph = self.context.graph
        self.assertEqual(_edge_curve_points(graph, '0', '1'), [(35, 70), (85, -10)])
        self.assertEqual(graph.nodes['0']['col'], 2)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'custom.graphml'
            write_graph_file(graph, path)
            loaded = convert_from_file(path)
            normalized, _ = normalize_graph(public_graph(loaded), loaded)
            self.assertEqual(normalized.nodes['0']['label'], 'existing')
            self.assertIn('existing', graph_to_tikz(normalized))

    def test_selection_contracts(self):
        seen = []
        @button(selection='vertex')
        def vertex(graph, node):
            seen.append(node)
        @button(selection='vertices')
        def vertices(graph, nodes):
            seen.append(nodes)
        @button(selection='edge')
        def edge(graph, endpoints):
            seen.append(endpoints)
        self.assertFalse(self.run_button(vertex))
        self.assertFalse(self.run_button(edge))
        self.run_button(vertices)
        self.assertEqual(seen.pop(), set())
        self.context.selection.nodes.add('0')
        self.run_button(vertex)
        self.assertEqual(seen.pop(), '0')
        self.context.selection.clear()
        self.context.selection.edges.add(EdgeRef('0', '1', False))
        self.run_button(edge)
        self.assertEqual(seen.pop(), ('0', '1'))

    def test_directed_input_and_new_edges(self):
        self.context.graph.graph['graph_type'] = 'digraph'
        @button
        def edit(graph):
            self.assertIs(type(graph), nx.DiGraph)
            graph.add_edge('1', '2')
        self.run_button(edit)
        self.assertTrue(self.context.graph.has_edge('1', '2'))
        self.assertFalse(self.context.graph.has_edge('2', '1'))

    def test_coloring_example_uses_one_edge_per_undirected_pair(self):
        from graph_builder import graph_coloring
        self.run_button(graph_coloring)
        self.assertNotEqual(self.context.graph.nodes['0']['col'],
                            self.context.graph.nodes['1']['col'])

    def test_distance_two_colors_checks_each_component_and_reports_missing_colors(self):
        from graph_builder import distance_two_colors, missing_colors_within_two

        graph = nx.DiGraph()
        graph.add_nodes_from((str(node), {'col': node, 'label': f'v{node}'})
                             for node in range(4))
        graph.add_node('other', col=9)
        graph.add_edges_from((str(node + 1), str(node)) for node in range(3))
        self.assertEqual(missing_colors_within_two(graph, {'0', '1', 'other'}),
                         {'0': {3}, '1': set(), 'other': set()})
        messages = []
        box = SimpleNamespace(write=lambda message, **kwargs: messages.append(message))
        context = EditorContext(graph, SelectionState({'0', '1', 'other'}, set()), box)
        self.assertTrue(distance_two_colors.is_available(context))
        self.assertTrue(execute_action(distance_two_colors, context))
        self.assertIn('1 of 3', messages[-1])
        self.assertIn('v0 (ID 0): missing 3', messages[-1])
        self.assertFalse(distance_two_colors.is_available(
            EditorContext(graph, SelectionState(), box)))

        context.selection.nodes = {'1', 'other'}
        execute_action(distance_two_colors, context)
        self.assertIn('Yes: all 2 selected vertices', messages[-1])

    def test_clear_errors_without_partial_changes(self):
        cases = [
            (lambda g: {}, 'NetworkX'),
            (lambda g: nx.MultiGraph(), 'Parallel edges'),
            (lambda g: nx.DiGraph(), 'directedness'),
            (lambda g: g.add_edge('0', '0'), 'Self-loops'),
            (lambda g: g.add_node('2', position='here'), 'position'),
            (lambda g: g.add_node('2', position=(float('nan'), 0)), 'position'),
            (lambda g: g.add_node('2', col=-2), 'color'),
            (lambda g: g.add_node('2', col='blue'), 'color'),
            (lambda g: g.add_node('2', custom=[]), 'cannot be saved'),
            (lambda g, required: g, 'required'),
        ]
        for function, message in cases:
            with self.subTest(message=message):
                before = copy.deepcopy(self.context.graph)
                with self.assertRaisesRegex((ValueError, TypeError), message):
                    self.run_button(button(function))
                self.assertTrue(nx.utils.graphs_equal(self.context.graph, before))


class CustomButtonQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_custom_docstring_appears_in_button_tooltip(self):
        @button('Explain', shortcut='G')
        def explain(graph):
            """Add an explanation to the tooltip.

            Further documentation stays in the source file.
            """
            return graph

        window = GraphBuilderQt(actions=(explain.__graph_button__,))
        try:
            action = next(action for definition, action in window.extension_actions
                          if definition.id == explain.__graph_button__.id)
            self.assertIn('Explain', action.toolTip())
            self.assertIn('Add an explanation to the tooltip.', action.toolTip())
            self.assertNotIn('Further documentation', action.toolTip())
        finally:
            window.scene.selectionChanged.disconnect(window.selection_changed)
            window.deleteLater()
            self.app.processEvents()

    def test_custom_button_undo_redo_and_uncaught_error(self):
        @button('Add leaf', selection='vertex')
        def add_leaf(graph, vertex):
            graph.add_edge(vertex, 'leaf')

        @button('Fail after mutation')
        def fail_after_mutation(graph):
            graph.clear()
            raise RuntimeError('custom failure')

        window = GraphBuilderQt(actions=(add_leaf.__graph_button__, fail_after_mutation.__graph_button__))
        try:
            window.add_node(QPointF(100, 100))
            window.view.centerOn(350, -200)
            before = copy.deepcopy(window.graph)
            window.selection.nodes = {'0'}
            history_size = len(window._history)
            window.run_extension(add_leaf.__graph_button__)
            self.assertEqual(len(window.graph), 2)
            self.assertEqual(window.selection.nodes, {'leaf'})
            self.assertEqual(len(window._history), history_size + 1)
            window.undo()
            self.assertTrue(nx.utils.graphs_equal(window.graph, before))
            window.redo()
            self.assertEqual(len(window.graph), 2)
            @button
            def isolated(graph):
                graph.add_node('isolated')
            window.view.centerOn(1000, -1000)
            center = window.view.mapToScene(window.view.viewport().rect().center())
            old_positions = {node: data['position'] for node, data in window.graph.nodes(data=True)}
            window.run_extension(isolated.__graph_button__)
            self.assertEqual(window.graph.nodes['isolated']['position'], tuple(center.toTuple()))
            self.assertTrue(all(window.graph.nodes[n]['position'] == p for n, p in old_positions.items()))
            before = copy.deepcopy(window.graph)
            selected = copy.deepcopy(window.selection)
            history_size = len(window._history)
            with self.assertRaisesRegex(RuntimeError, 'custom failure'):
                window.run_extension(fail_after_mutation.__graph_button__)
            self.assertTrue(nx.utils.graphs_equal(window.graph, before))
            self.assertEqual(window.selection, selected)
            self.assertEqual(len(window._history), history_size)
        finally:
            window.scene.selectionChanged.disconnect(window.selection_changed)
            window.deleteLater()
            self.app.processEvents()
