"""Continuous secondary-drag path creation with Shift held mid-gesture."""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from graph_builder_qt import GraphBuilderQt


class PathGestureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = GraphBuilderQt()
        self.window.show()
        self.app.processEvents()
        for x, y in ((0, 0), (100, 0), (100, 100), (0, 100)):
            self.window.add_node(QPointF(x, y))
        self.canvas = self.window.view.viewport()

    def tearDown(self):
        self.window.scene.selectionChanged.disconnect(self.window.selection_changed)
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()

    def point(self, node):
        return self.window.view.mapFromScene(
            QPointF(*self.window.graph.nodes[node]['position']))

    def move(self, node, modifiers=Qt.NoModifier, buttons=Qt.RightButton):
        local = QPointF(self.point(node))
        global_point = QPointF(self.canvas.mapToGlobal(local.toPoint()))
        event = QMouseEvent(QEvent.MouseMove, local, global_point,
                            Qt.NoButton, buttons, modifiers)
        QApplication.sendEvent(self.canvas, event)

    def test_shift_path_creates_each_segment_immediately_and_undoes_once(self):
        history = self.window._history_index
        QTest.mousePress(self.canvas, Qt.RightButton, Qt.ShiftModifier,
                         pos=self.point('0'))
        self.move('1', Qt.ShiftModifier)
        self.assertTrue(self.window.graph.has_edge('0', '1'))
        self.move('1', Qt.ShiftModifier)
        self.assertTrue(self.window.graph.has_edge('0', '1'))
        self.move('2', Qt.ShiftModifier)
        self.assertTrue(self.window.graph.has_edge('1', '2'))
        self.move('3', Qt.ShiftModifier)
        self.assertTrue(self.window.graph.has_edge('2', '3'))
        QTest.mouseRelease(self.canvas, Qt.RightButton, Qt.ShiftModifier,
                           pos=self.point('3'))
        self.assertEqual(self.window.graph.number_of_edges(), 6)
        self.assertEqual(self.window._history_index, history + 1)
        self.window.undo()
        self.assertEqual(self.window.graph.number_of_edges(), 0)

    def test_shift_can_be_enabled_after_normal_drag_starts(self):
        QTest.mousePress(self.canvas, Qt.RightButton, pos=self.point('0'))
        self.move('1')
        self.assertEqual(self.window.graph.number_of_edges(), 0)
        self.move('1', Qt.ShiftModifier)
        self.assertTrue(self.window.graph.has_edge('0', '1'))
        self.move('2')
        self.assertFalse(self.window.graph.has_edge('1', '2'))
        self.move('2', Qt.ShiftModifier)
        self.assertTrue(self.window.graph.has_edge('1', '2'))
        QTest.mouseRelease(self.canvas, Qt.RightButton, pos=self.point('3'))
        self.assertTrue(self.window.graph.has_edge('2', '3'))
        self.assertEqual(self.window.graph.number_of_edges(), 6)

    def test_selected_group_fans_out_only_at_first_path_vertex(self):
        self.window.node_items['0'].setSelected(True)
        self.window.node_items['3'].setSelected(True)
        QTest.mousePress(self.canvas, Qt.RightButton, Qt.ShiftModifier,
                         pos=self.point('0'))
        self.move('1', Qt.ShiftModifier)
        self.move('2', Qt.ShiftModifier)
        QTest.mouseRelease(self.canvas, Qt.RightButton, Qt.ShiftModifier,
                           pos=self.point('2'))
        self.assertTrue(self.window.graph.has_edge('0', '1'))
        self.assertTrue(self.window.graph.has_edge('3', '1'))
        self.assertTrue(self.window.graph.has_edge('1', '2'))
        self.assertFalse(self.window.graph.has_edge('3', '2'))

    def test_fast_motion_still_visits_vertex_crossed_between_mouse_events(self):
        self.window.add_node(QPointF(200, 0))
        QTest.mousePress(self.canvas, Qt.RightButton, Qt.ShiftModifier,
                         pos=self.point('0'))
        self.move('4', Qt.ShiftModifier)
        QTest.mouseRelease(self.canvas, Qt.RightButton, Qt.ShiftModifier,
                           pos=self.point('4'))
        self.assertTrue(self.window.graph.has_edge('0', '1'))
        self.assertTrue(self.window.graph.has_edge('1', '4'))
        self.assertFalse(self.window.graph.has_edge('0', '4'))

    def test_control_shift_left_drag_works_for_trackpad_without_breaking_remove_click(self):
        modifiers = Qt.ControlModifier | Qt.ShiftModifier
        self.window.node_items['0'].setSelected(True)
        QTest.mouseClick(self.canvas, Qt.LeftButton, modifiers, pos=self.point('0'))
        self.assertFalse(self.window.selection.nodes)
        QTest.mousePress(self.canvas, Qt.LeftButton, modifiers, pos=self.point('0'))
        self.move('1', modifiers, Qt.LeftButton)
        self.move('2', modifiers, Qt.LeftButton)
        QTest.mouseRelease(self.canvas, Qt.LeftButton, modifiers, pos=self.point('2'))
        self.assertTrue(self.window.graph.has_edge('0', '1'))
        self.assertTrue(self.window.graph.has_edge('1', '2'))

    def test_path_toggles_existing_edges_and_undo_restores_them(self):
        self.window.toggle_edge('0', '1')
        QTest.mousePress(self.canvas, Qt.RightButton, Qt.ShiftModifier,
                         pos=self.point('0'))
        self.move('1', Qt.ShiftModifier)
        self.move('2', Qt.ShiftModifier)
        QTest.mouseRelease(self.canvas, Qt.RightButton, Qt.ShiftModifier,
                           pos=self.point('2'))
        self.assertFalse(self.window.graph.has_edge('0', '1'))
        self.assertTrue(self.window.graph.has_edge('1', '2'))
        self.window.undo()
        self.assertTrue(self.window.graph.has_edge('0', '1'))
        self.assertFalse(self.window.graph.has_edge('1', '2'))


if __name__ == '__main__':
    unittest.main()
