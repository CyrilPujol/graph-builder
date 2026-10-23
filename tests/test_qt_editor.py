"""End-to-end checks for the Qt editor's core editing paths."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QInputDialog

from graph_builder import editor_actions
from graph_builder_lib import (
    ContextAction, _edge_curve_points, _set_edge_curve_points, convert_from_file,
    nearest_grid_point,
)
from graph_builder_qt import GraphBuilderQt, StepControl
from graph_builder_qt_canvas import COORDINATE_UNIT, DEFAULT_GRID_PRECISION
from tikz_export import graph_to_tikz


class QtEditorTests(unittest.TestCase):
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

    def position(self, x, y):
        return self.window.view.mapFromScene(QPointF(x, y))

    def test_pointer_creation_selection_and_undo(self):
        canvas = self.window.view.viewport()
        QTest.mouseClick(canvas, Qt.LeftButton, pos=self.position(0, 0))
        QTest.mouseClick(canvas, Qt.LeftButton, pos=self.position(120, 0))
        QTest.mousePress(canvas, Qt.RightButton, pos=self.position(0, 0))
        QTest.mouseMove(canvas, pos=self.position(120, 0))
        QTest.mouseRelease(canvas, Qt.RightButton, pos=self.position(120, 0))
        self.assertEqual(self.window.graph.number_of_nodes(), 2)
        self.assertEqual(self.window.graph.number_of_edges(), 2)

        QTest.mouseClick(canvas, Qt.LeftButton, pos=self.position(60, 0))
        self.assertEqual(len(self.window.selection.edges), 1)
        self.window.add_curve_point()
        self.assertEqual(len(_edge_curve_points(self.window.graph, '0', '1')), 1)
        self.assertEqual(_edge_curve_points(self.window.graph, '0', '1')[0][1], 0)
        self.window.undo()
        self.assertEqual(_edge_curve_points(self.window.graph, '0', '1'), [])
        self.window.redo()
        self.assertEqual(len(_edge_curve_points(self.window.graph, '0', '1')), 1)

    def test_labels_files_and_custom_action(self):
        self.window.add_node(QPointF(0, 0))
        self.window.add_node(QPointF(100, 0))
        self.window.toggle_edge('0', '1')
        with patch.object(QInputDialog, 'getText', return_value=('same_1', True)):
            self.window.rename_node('0')
            self.window.rename_node('1')
        with patch.object(QInputDialog, 'getText', return_value=('edge_1', True)):
            self.window.rename_edge('0', '1')
        self.assertEqual(self.window.graph.nodes['0']['label'], self.window.graph.nodes['1']['label'])
        tikz = graph_to_tikz(self.window.graph)
        self.assertIn(r'same\_1', tikz)
        self.assertIn(r'edge\_1', tikz)

        with tempfile.TemporaryDirectory() as folder:
            self.window.path = Path(folder) / 'drawing.graphml'
            self.assertTrue(self.window.save_file())
            restored = convert_from_file(self.window.path)
            self.assertEqual(restored.nodes['0']['label'], 'same_1')
            self.assertEqual(restored.edges['1', '0']['label'], 'edge_1')

        action = ContextAction(
            lambda context: context.graph.nodes['0'].update(label='from Python'),
            name='Custom label',
        )
        self.window.run_extension(action)
        self.assertEqual(self.window.graph.nodes['0']['label'], 'from Python')
        self.window.undo()
        self.assertEqual(self.window.graph.nodes['0']['label'], 'same_1')

    def test_double_click_renames_vertex_and_edge(self):
        self.window.add_node(QPointF(0, 0))
        self.window.add_node(QPointF(100, 0))
        self.window.toggle_edge('0', '1')
        canvas = self.window.view.viewport()
        with patch.object(QInputDialog, 'getText', return_value=('vertex name', True)):
            QTest.mouseDClick(canvas, Qt.LeftButton, pos=self.position(0, 0))
        self.assertEqual(self.window.graph.nodes['0']['label'], 'vertex name')
        QTest.mouseClick(canvas, Qt.LeftButton, pos=self.position(70, 0))
        with patch.object(QInputDialog, 'getText', return_value=('edge name', True)):
            QTest.mouseDClick(canvas, Qt.LeftButton, pos=self.position(70, 0))
        self.assertEqual(self.window.graph.edges['0', '1']['label'], 'edge name')

    def test_shift_selection_and_group_edge_gesture(self):
        for x in (0, 100, 200):
            self.window.add_node(QPointF(x, 0))
        canvas = self.window.view.viewport()
        QTest.mouseClick(canvas, Qt.LeftButton, pos=self.position(0, 0))
        QTest.mouseClick(canvas, Qt.LeftButton, Qt.ShiftModifier, pos=self.position(100, 0))
        self.assertEqual(self.window.selection.nodes, {'0', '1'})
        QTest.mouseClick(canvas, Qt.LeftButton, Qt.ControlModifier | Qt.ShiftModifier,
                         pos=self.position(100, 0))
        self.assertEqual(self.window.selection.nodes, {'0'})
        QTest.mouseClick(canvas, Qt.LeftButton, Qt.ShiftModifier, pos=self.position(100, 0))
        QTest.mousePress(canvas, Qt.RightButton, pos=self.position(0, 0))
        QTest.mouseMove(canvas, pos=self.position(200, 0))
        QTest.mouseRelease(canvas, Qt.RightButton, pos=self.position(200, 0))
        self.assertTrue(self.window.graph.has_edge('0', '2'))
        self.assertTrue(self.window.graph.has_edge('1', '2'))

    def test_ctrl_drag_creates_edge(self):
        self.window.add_node(QPointF(0, 0))
        self.window.add_node(QPointF(100, 0))
        canvas = self.window.view.viewport()
        QTest.mousePress(canvas, Qt.LeftButton, Qt.ControlModifier, pos=self.position(0, 0))
        QTest.mouseMove(canvas, pos=self.position(100, 0))
        QTest.mouseRelease(canvas, Qt.LeftButton, Qt.ControlModifier,
                           pos=self.position(100, 0))
        self.assertTrue(self.window.graph.has_edge('0', '1'))

    def test_secondary_click_deletes_only_without_a_selection(self):
        self.window.add_node(QPointF(0, 0))
        canvas = self.window.view.viewport()
        QTest.mouseClick(canvas, Qt.RightButton, pos=self.position(0, 0))
        self.assertEqual(self.window.graph.number_of_nodes(), 0)

        self.window.add_node(QPointF(0, 0))
        self.window.add_node(QPointF(100, 0))
        QTest.mouseClick(canvas, Qt.LeftButton, pos=self.position(0, 0))
        QTest.mouseClick(canvas, Qt.RightButton, pos=self.position(100, 0))
        self.assertEqual(self.window.graph.number_of_nodes(), 2)
        self.assertEqual(self.window.selection.nodes, {'1'})

    def test_empty_click_deselects_without_creating_when_selected(self):
        self.window.add_node(QPointF(0, 0))
        canvas = self.window.view.viewport()
        QTest.mouseClick(canvas, Qt.LeftButton, pos=self.position(0, 0))
        QTest.mouseClick(canvas, Qt.LeftButton, pos=self.position(120, 80))
        self.assertEqual(self.window.graph.number_of_nodes(), 1)
        self.assertFalse(self.window.selection.nodes)

    def test_grid_snap_and_directed_toggle(self):
        self.window.set_grid('radial')
        self.window.add_node(QPointF(0, -29))
        origin = self.window.grid_origin
        self.assertEqual(self.window.graph.nodes['0']['position'],
                         (origin.x(), origin.y() - self.window.grid_unit))
        self.window.add_node(QPointF(90, 0))
        self.window.toggle_edge('0', '1')
        self.window.set_directed(True)
        self.assertTrue(self.window.is_directed)
        self.assertEqual(len(self.window.edge_items), 2)
        self.window.set_directed(False)
        self.assertEqual(len(self.window.edge_items), 1)
        self.window.grid_radial_action.trigger()
        self.assertIsNone(self.window.grid_mode)

    def test_grid_keeps_untouched_vertices_and_uses_power_of_two_precision(self):
        self.window.add_node(QPointF(12, 8))
        self.window.set_grid('square')
        self.assertEqual(self.window.graph.nodes['0']['position'], (12.0, 8.0))
        self.window.add_node(QPointF(48, 48))
        self.assertEqual(self.window.grid_origin.toTuple(), (0.0, 0.0))
        self.assertEqual(self.window.grid_unit, DEFAULT_GRID_PRECISION)
        self.assertEqual(self.window.graph.nodes['0']['position'], (12.0, 8.0))
        self.assertEqual(self.window.graph.nodes['1']['position'],
                         (DEFAULT_GRID_PRECISION, DEFAULT_GRID_PRECISION))
        self.window.change_grid_unit(2)
        self.assertEqual(self.window.grid_unit, COORDINATE_UNIT / 2)
        self.assertEqual(self.window.graph.nodes['0']['position'], (12.0, 8.0))
        self.assertEqual(self.window.graph.nodes['1']['position'],
                         (DEFAULT_GRID_PRECISION, DEFAULT_GRID_PRECISION))

    def test_triangular_grid_switching_snapping_and_precision(self):
        self.window.add_node(QPointF(12, 8))
        self.window.grid_triangular_action.trigger()
        self.assertEqual(self.window.grid_mode, 'triangular')
        self.assertTrue(self.window.grid_triangular_action.isChecked())
        self.assertTrue(self.window.grid_unit_label_action.isVisible())
        self.assertFalse(self.window.radial_label_action.isVisible())
        self.assertEqual(self.window.graph.nodes['0']['position'], (12.0, 8.0))

        created = QPointF(48, 48)
        expected = nearest_grid_point(created.toTuple(), 'triangular', unit=DEFAULT_GRID_PRECISION)
        self.window.add_node(created)
        self.assertEqual(self.window.graph.nodes['1']['position'], expected)
        self.window.node_items['1'].setSelected(True)
        self.window.node_items['1'].setPos(QPointF(60, 50))
        self.window.finish_pointer_change()
        moved = nearest_grid_point((60, 50), 'triangular', unit=DEFAULT_GRID_PRECISION)
        self.assertEqual(self.window.graph.nodes['1']['position'], moved)

        self.window.change_grid_unit(2)
        self.assertEqual(self.window.grid_unit, COORDINATE_UNIT / 2)
        self.assertEqual(self.window.graph.nodes['0']['position'], (12.0, 8.0))
        self.assertEqual(self.window.graph.nodes['1']['position'], moved)
        self.window.grid_triangular_action.trigger()
        self.assertIsNone(self.window.grid_mode)
        self.window.grid_radial_action.trigger()
        self.assertTrue(self.window.radial_label_action.isVisible())
        self.window.grid_triangular_action.trigger()
        self.assertFalse(self.window.radial_label_action.isVisible())

    def test_grid_precision_buttons_and_grid_order(self):
        grid_actions = self.window.menu_tabs.widget(2).actions()
        self.assertEqual([action.text() for action in grid_actions[:4]],
                         ['No grid', 'Square grid', 'Radial grid', 'Triangular grid'])
        self.window.set_grid('triangular')
        original = self.window.grid_unit
        self.window.grid_up_action.trigger()
        self.assertEqual(self.window.grid_unit, original / 2)
        self.window.grid_down_action.trigger()
        self.assertEqual(self.window.grid_unit, original)
        self.assertEqual(self.window.grid_unit_label.text().strip(), 'Grid precision:')
        for control in self.window.findChildren(StepControl):
            self.assertIn(control.decrease.text(), ('-', ' '))
            self.assertIn(control.increase.text(), ('+', ' '))
            self.assertLessEqual(control.width(), 60)
            self.assertEqual(control.decrease.size(), control.increase.size())
            self.assertGreaterEqual(control.decrease.font().pixelSize(), 18)
        self.window.set_grid_unit(COORDINATE_UNIT / 64)
        self.assertFalse(self.window.grid_up_action.isEnabled())
        self.assertTrue(self.window.grid_down_action.isEnabled())
        self.window.set_grid_unit(COORDINATE_UNIT * 16)
        self.assertTrue(self.window.grid_up_action.isEnabled())
        self.assertFalse(self.window.grid_down_action.isEnabled())

    def test_standard_graph_form_remembers_parameters_and_validates(self):
        self.assertEqual(self.window.menu_tabs.tabText(4), 'Standard graphs')
        selector = self.window.standard_graph_choice
        self.assertEqual(selector.palette().color(QPalette.Text).name(), '#111111')
        kneser = selector.findData('kneser')
        selector.setCurrentIndex(kneser)
        n_input = self.window.standard_parameter_inputs['kneser']['n']
        k_input = self.window.standard_parameter_inputs['kneser']['k']
        n_input.setValue(6)
        k_input.setValue(3)
        self.assertTrue(self.window.standard_add_action.isEnabled())
        self.assertIn('20 vertices', self.window.standard_info_label.text())
        selector.setCurrentIndex(selector.findData('path'))
        selector.setCurrentIndex(kneser)
        self.assertEqual((n_input.value(), k_input.value()), (6, 3))
        k_input.setValue(6)
        self.assertFalse(self.window.standard_add_action.isEnabled())
        self.assertIn('k < n', self.window.standard_info_label.text())
        k_input.setValue(2)
        self.assertTrue(self.window.standard_add_action.isEnabled())
        selector.setCurrentIndex(selector.findData('paley'))
        self.window.standard_parameter_inputs['paley']['p'].setValue(9)
        self.assertFalse(self.window.standard_add_action.isEnabled())
        self.assertIn('prime', self.window.standard_info_label.text())

    def test_standard_graph_insert_center_selection_history_and_export(self):
        self.window.add_node(QPointF(15, 25))
        self.window.set_grid('square')
        self.window.view.zoom_by_delta(240, QPointF(250, 200))
        self.window.view.centerOn(500, -300)
        self.app.processEvents()
        viewport_center = self.window.view.mapToScene(
            self.window.view.viewport().rect().center())
        original_position = self.window.graph.nodes['0']['position']
        inserted = self.window.add_standard_graph('path', {'n': 4})
        self.assertEqual(len(inserted), 4)
        self.assertEqual(self.window.selection.nodes, inserted)
        self.assertFalse(self.window.selection.edges)
        self.assertNotIn('0', inserted)
        self.assertEqual(self.window.graph.nodes['0']['position'], original_position)
        self.assertEqual(self.window.graph.number_of_edges(), 6)
        xs = [self.window.graph.nodes[node]['position'][0] for node in inserted]
        ys = [self.window.graph.nodes[node]['position'][1] for node in inserted]
        self.assertAlmostEqual((min(xs)+max(xs))/2, viewport_center.x(), delta=2)
        self.assertAlmostEqual((min(ys)+max(ys))/2, viewport_center.y(), delta=2)
        self.assertTrue(any(x % self.window.grid_unit for x in xs))
        self.assertEqual({self.window.graph.nodes[node]['label'] for node in inserted},
                         {'0', '1', '2', '3'})
        with tempfile.TemporaryDirectory() as folder:
            self.window.path = Path(folder) / 'standard.graphml'
            self.assertTrue(self.window.save_file())
            loaded = convert_from_file(self.window.path)
            self.assertEqual(loaded.number_of_nodes(), 5)
            self.assertEqual(loaded.number_of_edges(), 6)
            self.assertEqual({loaded.nodes[node]['label'] for node in inserted},
                             {'0', '1', '2', '3'})
        tikz = graph_to_tikz(self.window.graph)
        self.assertIn('3', tikz)
        self.window.undo()
        self.assertEqual(self.window.graph.number_of_nodes(), 1)
        self.window.redo()
        self.assertEqual(self.window.graph.number_of_nodes(), 5)

    def test_standard_graph_adds_bidirectional_edges_in_directed_document(self):
        self.window.set_directed(True)
        inserted = self.window.add_standard_graph('clique', {'n': 3})
        self.assertEqual(len(inserted), 3)
        self.assertEqual(self.window.graph.number_of_edges(), 6)
        for source, target in self.window.graph.edges:
            self.assertTrue(self.window.graph.has_edge(target, source))

    def test_new_standard_graph_selection_drags_as_one_group(self):
        inserted = self.window.add_standard_graph('path', {'n': 3})
        before = {node: self.window.graph.nodes[node]['position'] for node in inserted}
        start = self.position(*before[min(inserted)])
        finish = start + QPointF(55, 35).toPoint()
        canvas = self.window.view.viewport()
        QTest.mousePress(canvas, Qt.LeftButton, pos=start)
        QTest.mouseMove(canvas, pos=finish)
        QTest.mouseRelease(canvas, Qt.LeftButton, pos=finish)
        after = {node: self.window.graph.nodes[node]['position'] for node in inserted}
        self.assertEqual(self.window.selection.nodes, inserted)
        self.assertTrue(all(after[node] != before[node] for node in inserted))

    def test_menu_tabs_collapse_and_reopen(self):
        tabs = self.window.menu_tabs
        bar = tabs.tabBar()
        QTest.mouseClick(bar, Qt.LeftButton, pos=bar.tabRect(0).center())
        self.app.processEvents()
        self.assertEqual(tabs._open_index, -1)
        QTest.mouseClick(bar, Qt.LeftButton, pos=bar.tabRect(2).center())
        self.app.processEvents()
        self.assertEqual(tabs._open_index, 2)
        self.assertEqual(tabs.currentIndex(), 2)

    def test_zoom_is_slow_and_reversible(self):
        view = self.window.view
        anchor = QPointF(213, 173)
        anchor_before = view.mapToScene(anchor.toPoint())
        center_before = view.mapToScene(view.viewport().rect().center())
        view.zoom_by_delta(120, anchor)
        self.assertLess(view.transform().m11(), 1.12)
        view.zoom_by_delta(-120, anchor)
        anchor_after = view.mapToScene(anchor.toPoint())
        center_after = view.mapToScene(view.viewport().rect().center())
        self.assertAlmostEqual(view.transform().m11(), 1.0, places=10)
        self.assertAlmostEqual(anchor_after.x(), anchor_before.x(), delta=.05)
        self.assertAlmostEqual(anchor_after.y(), anchor_before.y(), delta=.05)
        self.assertAlmostEqual(center_after.x(), center_before.x(), delta=.05)
        self.assertAlmostEqual(center_after.y(), center_before.y(), delta=.05)

    def test_radial_limit_is_99(self):
        self.window.set_grid('radial')
        self.window.set_radials(99)
        self.assertFalse(self.window.radial_up_action.isEnabled())
        self.assertTrue(self.window.radial_down_action.isEnabled())

    def test_add_and_delete_curve_point(self):
        self.window.add_node(QPointF(0, 0))
        self.window.add_node(QPointF(100, 0))
        self.window.toggle_edge('0', '1')
        canvas = self.window.view.viewport()
        QTest.mouseClick(canvas, Qt.LeftButton, pos=self.position(50, 0))
        self.assertEqual(len(self.window.selection.edges), 1)
        self.window.add_curve_action.trigger()
        self.assertEqual(len(_edge_curve_points(self.window.graph, '0', '1')), 1)
        self.window.view.setFocus()
        QTest.keyClick(self.window.view, Qt.Key_Delete)
        self.assertEqual(_edge_curve_points(self.window.graph, '0', '1'), [])

    def test_curve_point_button_uses_existing_curved_path(self):
        self.window.add_node(QPointF(0, 0))
        self.window.add_node(QPointF(100, 0))
        self.window.toggle_edge('0', '1')
        self.window.add_curve_point_at('0', '1', QPointF(50, 40))
        self.window.deselect()
        edge = self.window.edge_items[self.window.edge_key('0', '1')]
        expected = edge.path().pointAtPercent(.5)
        edge.setSelected(True)
        self.window.add_curve_action.trigger()
        points = _edge_curve_points(self.window.graph, '0', '1')
        self.assertEqual(len(points), 2)
        self.assertAlmostEqual(points[0][0], expected.x())
        self.assertAlmostEqual(points[0][1], expected.y())

    def test_drag_inserts_curve_point_between_existing_controls(self):
        self.window.add_node(QPointF(0, 0))
        self.window.add_node(QPointF(120, 0))
        self.window.toggle_edge('0', '1')
        original = [(80, 65), (35, 115), (90, 155)]
        _set_edge_curve_points(self.window.graph, '0', '1', original)
        self.window.rebuild_scene()
        edge = self.window.edge_items[self.window.edge_key('0', '1')]
        edge.setSelected(True)
        middle = edge.path().elementAt(48)  # Halfway from control 0 to 1.
        start = self.position(middle.x, middle.y)
        end = start + QPointF(12, 15).toPoint()
        canvas = self.window.view.viewport()
        QTest.mousePress(canvas, Qt.LeftButton, pos=start)
        QTest.mouseMove(canvas, pos=end)
        QTest.mouseRelease(canvas, Qt.LeftButton, pos=end)
        points = _edge_curve_points(self.window.graph, '0', '1')
        self.assertEqual(len(points), 4)
        self.assertEqual(points[0], original[0])
        self.assertEqual(points[2:], original[1:])

    def test_deselect_stays_on_escape_without_toolbar_button(self):
        basic_row = self.window.menu_tabs.widget(1)
        self.assertNotIn(self.window.deselect_action, basic_row.actions())
        self.window.add_node(QPointF(0, 0))
        self.window.node_items['0'].setSelected(True)
        self.window.view.setFocus()
        QTest.keyClick(self.window.view, Qt.Key_Escape)
        self.assertFalse(self.window.selection.nodes)

    def test_drag_selected_edge_creates_moves_and_secondary_click_deletes_curve_point(self):
        self.window.add_node(QPointF(0, 0))
        self.window.add_node(QPointF(100, 0))
        self.window.toggle_edge('0', '1')
        canvas = self.window.view.viewport()
        QTest.mouseClick(canvas, Qt.LeftButton, pos=self.position(50, 0))

        QTest.mousePress(canvas, Qt.LeftButton, pos=self.position(50, 0))
        QTest.mouseMove(canvas, pos=self.position(55, 35))
        QTest.mouseRelease(canvas, Qt.LeftButton, pos=self.position(55, 35))
        points = _edge_curve_points(self.window.graph, '0', '1')
        self.assertEqual(len(points), 1)
        self.assertAlmostEqual(points[0][0], 55, delta=2)
        self.assertAlmostEqual(points[0][1], 35, delta=2)

        handle = self.window.curve_handles[0]
        start = self.position(*handle.pos().toTuple())
        QTest.mousePress(canvas, Qt.LeftButton, pos=start)
        QTest.mouseMove(canvas, pos=self.position(65, 45))
        QTest.mouseRelease(canvas, Qt.LeftButton, pos=self.position(65, 45))
        points = _edge_curve_points(self.window.graph, '0', '1')
        self.assertAlmostEqual(points[0][0], 65, delta=2)
        self.assertAlmostEqual(points[0][1], 45, delta=2)

        handle = self.window.curve_handles[0]
        QTest.mouseClick(canvas, Qt.RightButton, pos=self.position(*handle.pos().toTuple()))
        self.assertEqual(_edge_curve_points(self.window.graph, '0', '1'), [])

    def test_option_drag_pans_without_editing_graph(self):
        self.window.add_node(QPointF(0, 0))
        before = self.window.graph.nodes['0']['position']
        canvas = self.window.view.viewport()
        camera_before = self.window.view.mapToScene(canvas.rect().center()).toTuple()
        start = self.position(180, 100)
        QTest.mousePress(canvas, Qt.LeftButton, Qt.AltModifier, pos=start)
        QTest.mouseMove(canvas, pos=start + QPointF(80, 40).toPoint())
        QTest.mouseRelease(canvas, Qt.LeftButton, Qt.AltModifier,
                           pos=start + QPointF(80, 40).toPoint())
        self.assertEqual(self.window.graph.nodes['0']['position'], before)
        self.assertNotEqual(self.window.view.mapToScene(canvas.rect().center()).toTuple(),
                            camera_before)

    def test_plain_drag_moves_vertices(self):
        self.window.add_node(QPointF(0, 0))
        self.window.add_node(QPointF(100, 0))
        canvas = self.window.view.viewport()
        start = self.position(0, 0)
        QTest.mousePress(canvas, Qt.LeftButton, pos=start)
        QTest.mouseMove(canvas, pos=start + QPointF(40, 20).toPoint())
        QTest.mouseRelease(canvas, Qt.LeftButton, pos=start + QPointF(40, 20).toPoint())
        self.assertNotEqual(self.window.graph.nodes['0']['position'], (0.0, 0.0))
        start = self.position(100, 0)
        QTest.mousePress(canvas, Qt.LeftButton, pos=start)
        QTest.mouseMove(canvas, pos=start + QPointF(30, 25).toPoint())
        QTest.mouseRelease(canvas, Qt.LeftButton, pos=start + QPointF(30, 25).toPoint())
        self.assertNotEqual(self.window.graph.nodes['1']['position'], (100.0, 0.0))

    def test_select_all_vertices_shortcut(self):
        self.window.add_node(QPointF(0, 0))
        self.window.add_node(QPointF(100, 0))
        self.window.toggle_edge('0', '1')
        self.window.edge_items[self.window.edge_key('0', '1')].setSelected(True)
        self.window.view.setFocus()
        # Qt maps its Control modifier to the Command key on macOS.
        QTest.keyClick(self.window.view, Qt.Key_A, Qt.ControlModifier)
        self.assertEqual(self.window.selection.nodes, {'0', '1'})
        self.assertFalse(self.window.selection.edges)
        QTest.keyClick(self.window.view, Qt.Key_Space)
        self.assertEqual(self.window.graph.number_of_nodes(), 2)

    def test_named_graph_saves_on_close(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'autosaved.graphml'
            self.window.path = path
            self.window.add_node(QPointF(12, 34))
            self.window.close()
            loaded = convert_from_file(path)
        self.assertEqual(loaded.nodes['0']['position'], (12.0, 34.0))

    def test_custom_twin_selects_new_vertex_and_contract_accepts_edge(self):
        self.window.add_node(QPointF(0, 0))
        self.window.add_node(QPointF(100, 0))
        self.window.toggle_edge('0', '1')
        self.window.node_items['0'].setSelected(True)
        actions = {action.display_name(self.window.context()): action for action in editor_actions()}
        self.window.run_extension(actions['Twin'])
        self.assertEqual(self.window.selection.nodes, {'2'})
        self.window.deselect()
        self.window.edge_items[self.window.edge_key('0', '1')].setSelected(True)
        self.window.run_extension(actions['Contract'])
        self.assertNotIn('0', self.window.graph)
        self.assertNotIn('1', self.window.graph)

    def test_color_button_uses_last_canvas_pointer(self):
        self.window.add_node(QPointF(0, 0))
        self.window.menu_tabs.setCurrentIndex(1)
        canvas = self.window.view.viewport()
        QTest.mouseMove(canvas, pos=self.position(0, 0))
        button = self.window.menu_tabs.widget(1).widgetForAction(self.window.color_action)
        QTest.mouseClick(button, Qt.LeftButton)
        self.assertEqual(self.window.graph.nodes['0']['col'], 1)
        self.assertIn('C', button.toolTip())

    def test_color_during_group_edge_drag_changes_edge_color(self):
        self.window.add_node(QPointF(0, 0))
        self.window.node_items['0'].setSelected(True)
        self.window.scene.edge_sources = ('0',)
        self.window.next_color()
        self.window.scene.edge_sources = ()
        self.assertEqual(self.window.edge_color, 1)
        self.assertEqual(self.window.graph.nodes['0']['col'], 0)

    def test_select_rectangle_ignores_edges_and_delete_key(self):
        self.window.add_node(QPointF(0, 0))
        self.window.add_node(QPointF(100, 0))
        self.window.toggle_edge('0', '1')
        canvas = self.window.view.viewport()
        before = self.window.graph.number_of_nodes()
        QTest.mouseClick(canvas, Qt.LeftButton, pos=self.position(180, 80))
        self.assertEqual(self.window.graph.number_of_nodes(), before + 1)
        QTest.mousePress(canvas, Qt.LeftButton, pos=self.position(-35, -35))
        QTest.mouseMove(canvas, pos=self.position(135, 35))
        self.assertFalse(self.window.edge_items[self.window.edge_key('0', '1')].isSelected())
        QTest.mouseRelease(canvas, Qt.LeftButton, pos=self.position(135, 35))
        self.assertEqual(self.window.selection.nodes, {'0', '1'})
        self.assertEqual(len(self.window.selection.edges), 0)
        self.window.view.setFocus()
        # The small Mac key labelled "delete" is Backspace, not forward Delete.
        QTest.keyClick(self.window.view, Qt.Key_Backspace)
        self.assertEqual(self.window.graph.number_of_nodes(), 1)

    def test_shift_rectangle_adds_vertices_to_selection(self):
        for x in (0, 100, 200):
            self.window.add_node(QPointF(x, 0))
        canvas = self.window.view.viewport()
        QTest.mouseClick(canvas, Qt.LeftButton, pos=self.position(0, 0))
        QTest.mousePress(canvas, Qt.LeftButton, Qt.ShiftModifier, pos=self.position(65, -30))
        QTest.mouseMove(canvas, pos=self.position(135, 30))
        QTest.mouseRelease(canvas, Qt.LeftButton, Qt.ShiftModifier,
                           pos=self.position(135, 30))
        self.assertEqual(self.window.selection.nodes, {'0', '1'})
        QTest.mousePress(canvas, Qt.LeftButton, Qt.ControlModifier | Qt.ShiftModifier,
                         pos=self.position(65, -30))
        QTest.mouseMove(canvas, pos=self.position(135, 30))
        QTest.mouseRelease(canvas, Qt.LeftButton, Qt.ControlModifier | Qt.ShiftModifier,
                           pos=self.position(135, 30))
        self.assertEqual(self.window.selection.nodes, {'0'})

    def test_shift_lasso_adds_vertices_to_selection(self):
        for x in (0, 100, 200):
            self.window.add_node(QPointF(x, 0))
        canvas = self.window.view.viewport()
        QTest.mouseClick(canvas, Qt.LeftButton, pos=self.position(0, 0))
        QTest.mousePress(canvas, Qt.RightButton, Qt.ShiftModifier,
                         pos=self.position(70, -30))
        for x, y in ((130, -30), (130, 30), (70, 30)):
            QTest.mouseMove(canvas, pos=self.position(x, y))
        QTest.mouseRelease(canvas, Qt.RightButton, Qt.ShiftModifier,
                           pos=self.position(70, -30))
        self.assertEqual(self.window.selection.nodes, {'0', '1'})


if __name__ == '__main__':
    unittest.main()
