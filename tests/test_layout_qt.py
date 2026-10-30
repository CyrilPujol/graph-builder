"""Layout menu integration, direct application, and undo behavior."""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from graph_builder_qt import GraphBuilderQt
from graph_layout import PIN_ATTRIBUTE


class LayoutEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = GraphBuilderQt()
        self.window.show()
        self.app.processEvents()
        for x in (0, 50, 100, 150):
            self.window.add_node(QPointF(x, 0))
        for a, b in (('0', '1'), ('1', '2'), ('2', '3')):
            self.window.toggle_edge(a, b)

    def tearDown(self):
        self.window.scene.selectionChanged.disconnect(self.window.selection_changed)
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()

    def test_layout_menu_applies_immediately_and_undoes(self):
        tabs = self.window.menu_tabs
        self.assertIn('Layout', [tabs.tabText(i) for i in range(tabs.count())])
        original = {node: self.window.graph.nodes[node]['position'] for node in self.window.graph}
        history = self.window._history_index
        self.window.node_items['1'].setSelected(True)
        self.window.node_items['2'].setSelected(True)
        self.assertTrue(self.window.arrange_graph())
        self.assertEqual(self.window._history_index, history + 1)
        self.assertEqual(self.window.graph.nodes['0']['position'], original['0'])
        self.assertEqual(self.window.graph.nodes['3']['position'], original['3'])
        self.window.undo()
        self.assertEqual({node: self.window.graph.nodes[node]['position']
                          for node in self.window.graph}, original)

    def test_pin_is_undoable_and_manual_drag_remains_available(self):
        self.window.node_items['1'].setSelected(True)
        self.window.pin_selection()
        self.assertTrue(self.window.graph.nodes['1'][PIN_ATTRIBUTE])
        self.assertTrue(self.window.node_items['1'].flags() &
                        self.window.node_items['1'].GraphicsItemFlag.ItemIsMovable)
        self.window.undo()
        self.assertNotIn(PIN_ATTRIBUTE, self.window.graph.nodes['1'])

    def test_live_relaxation_moves_neighbors_but_not_pins_and_undoes_together(self):
        original = {node: self.window.graph.nodes[node]['position'] for node in self.window.graph}
        self.window.node_items['2'].setSelected(True)
        self.window.pin_selection()
        self.window.scene.clearSelection()
        self.window.live_layout_action.trigger()
        history = self.window._history_index
        canvas = self.window.view.viewport()
        start = self.window.view.mapFromScene(QPointF(*original['0']))
        end = self.window.view.mapFromScene(QPointF(0, 70))
        QTest.mousePress(canvas, Qt.LeftButton, pos=start)
        QTest.mouseMove(canvas, pos=end)
        QTest.mouseRelease(canvas, Qt.LeftButton, pos=end)
        self.assertEqual(self.window.graph.nodes['2']['position'], original['2'])
        self.assertNotEqual(self.window.graph.nodes['1']['position'], original['1'])
        self.assertEqual(self.window._history_index, history + 1)
        self.window.undo()
        self.assertEqual({node: self.window.graph.nodes[node]['position']
                          for node in self.window.graph}, original)

    def test_holding_vertex_relaxes_neighbors_without_pointer_movement(self):
        self.window.node_items['2'].setPos(100, 150)
        self.window.commit_change()
        original = {node: self.window.graph.nodes[node]['position'] for node in self.window.graph}
        self.window.live_layout_action.trigger()
        history = self.window._history_index
        canvas = self.window.view.viewport()
        point = self.window.view.mapFromScene(QPointF(*original['0']))
        QTest.mousePress(canvas, Qt.LeftButton, pos=point)
        QTest.qWait(180)
        self.assertEqual(self.window.graph.nodes['0']['position'], original['0'])
        self.assertNotEqual(self.window.graph.nodes['1']['position'], original['1'])
        self.assertEqual(self.window.graph.nodes['2']['position'], original['2'])
        QTest.mouseRelease(canvas, Qt.LeftButton, pos=point)
        self.assertEqual(self.window._history_index, history + 1)
        settled = {node: self.window.graph.nodes[node]['position'] for node in self.window.graph}
        QTest.qWait(120)
        self.assertEqual({node: self.window.graph.nodes[node]['position']
                          for node in self.window.graph}, settled)
        self.window.undo()
        self.assertEqual({node: self.window.graph.nodes[node]['position']
                          for node in self.window.graph}, original)


if __name__ == '__main__':
    unittest.main()
