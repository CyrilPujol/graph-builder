"""Properties dialog and canvas styling integration."""
import os
import json
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QPointF
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from graph_builder_qt import GraphBuilderQt
from graph_style_ui import PropertiesDialog, StylesDialog
from graph_styles import effective_style, set_overrides, set_palette_style, set_preset


class StyleQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = GraphBuilderQt()
        self.window.show()
        self.app.processEvents()
        self.window.add_node(QPointF(0, 0))
        self.window.add_node(QPointF(100, 0))
        self.window.toggle_edge('0', '1')

    def tearDown(self):
        self.window.scene.selectionChanged.disconnect(self.window.selection_changed)
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()

    def test_bulk_type_change_preserves_individual_looks_and_undoes_once(self):
        set_overrides(self.window.graph.nodes['0'], {'fill': '#123456'})
        set_overrides(self.window.graph.nodes['1'], {'fill': '#654321'})
        self.window.rebuild_scene()
        self.window.node_items['0'].setSelected(True)
        self.window.node_items['1'].setSelected(True)
        before = self.window._history_index

        def accept(dialog):
            self.assertTrue(dialog.bulk)
            self.assertIsNone(dialog.label_edit)
            self.assertEqual(dialog.look_mode.currentData(), 'keep')
            dialog.change_type(1)
            return QDialog.Accepted

        with patch.object(PropertiesDialog, 'exec', accept):
            self.window.edit_node_properties('0')
        self.assertEqual(self.window._history_index, before + 1)
        self.assertEqual(effective_style(self.window.graph, 'vertex', self.window.graph.nodes['0'])['fill'], '#123456')
        self.assertEqual(effective_style(self.window.graph, 'vertex', self.window.graph.nodes['1'])['fill'], '#654321')
        self.assertEqual(self.window.graph.nodes['0']['col'], 1)
        self.assertEqual(self.window.graph.nodes['1']['col'], 1)
        self.assertEqual(self.window.selection.nodes, {'0', '1'})
        self.window.undo()
        self.assertEqual(self.window.graph.nodes['0']['col'], 0)

    def test_cancel_and_shape_free_vertex_remains_hittable(self):
        before = self.window._history_index
        with patch.object(PropertiesDialog, 'exec', return_value=QDialog.Rejected):
            self.window.edit_node_properties('0')
        self.assertEqual(self.window._history_index, before)
        set_overrides(self.window.graph.nodes['0'], {'shape': 'none', 'size': 4})
        self.window.rebuild_scene()
        self.assertTrue(self.window.node_items['0'].shape().contains(QPointF(0, 0)))
        self.assertGreaterEqual(self.window.node_items['0'].shape().boundingRect().width(), 34)
        set_overrides(self.window.graph.nodes['0'], {'size': 200})
        self.window.rebuild_scene()
        self.assertLess(self.window.node_items['0'].shape().boundingRect().width(), 60)

    def test_inherited_look_controls_are_disabled_until_custom_look(self):
        dialog = PropertiesDialog(self.window.graph, 'vertex',
                                  [dict(self.window.graph.nodes['0'], label='0')], parent=self.window)
        value = dialog.controls['fill']
        self.assertEqual(dialog.look_mode.currentText(), 'Inherit from type 0')
        self.assertFalse(value.isEnabled())
        dialog.look_mode.setCurrentIndex(dialog.look_mode.findData('custom'))
        self.assertTrue(value.isEnabled())
        value.setText('#abcdef')
        self.assertEqual(dialog.changes()['fill'], '#abcdef')
        dialog.look_mode.setCurrentIndex(dialog.look_mode.findData('inherit'))
        self.assertFalse(value.isEnabled())
        self.assertIsNone(dialog.changes()['fill'])

    def test_type_change_refreshes_inherited_look_without_creating_overrides(self):
        set_palette_style(self.window.graph, 'vertex', 1, {'fill': '#abcdef'})
        dialog = PropertiesDialog(self.window.graph, 'vertex',
                                  [dict(self.window.graph.nodes['0'], label='0')], parent=self.window)
        dialog.change_type(1)
        self.assertEqual(dialog.type_values(), [1])
        self.assertEqual(dialog.look_mode.currentText(), 'Inherit from type 1')
        self.assertEqual(dialog.controls['fill'].text(), '#abcdef')
        self.assertFalse(dialog.controls['fill'].isEnabled())
        self.assertEqual(dialog.changes(), {})

    def test_label_change_does_not_flatten_existing_custom_look(self):
        set_overrides(self.window.graph.nodes['0'], {'fill': '#123456'})
        self.window.rebuild_scene()

        def accept(dialog):
            self.assertEqual(dialog.look_mode.currentData(), 'custom')
            dialog.label_edit.setText('New label')
            return QDialog.Accepted

        with patch.object(PropertiesDialog, 'exec', accept):
            self.window.edit_node_properties('0')
        self.assertEqual(json.loads(self.window.graph.nodes['0']['style_overrides']),
                         {'fill': '#123456'})

    def test_double_click_on_selected_group_opens_bulk_properties(self):
        canvas = self.window.view.viewport()
        self.window.node_items['0'].setSelected(True)
        self.window.node_items['1'].setSelected(True)
        point = self.window.view.mapFromScene(QPointF(0, 0))
        seen = []

        def reject(dialog):
            seen.append(dialog.bulk)
            return QDialog.Rejected

        with patch.object(PropertiesDialog, 'exec', reject):
            QTest.mouseClick(canvas, Qt.LeftButton, pos=point)
            QTest.mouseDClick(canvas, Qt.LeftButton, pos=point)
            QTest.mouseRelease(canvas, Qt.LeftButton, pos=point)
        self.assertEqual(seen, [True])
        self.assertEqual(self.window.selection.nodes, {'0', '1'})

    def test_double_click_on_selected_edges_opens_bulk_properties(self):
        self.window.add_node(QPointF(200, 0))
        self.window.toggle_edge('1', '2')
        for item in self.window.edge_items.values():
            item.setSelected(True)
        point = self.window.view.mapFromScene(QPointF(50, 0))
        seen = []

        def reject(dialog):
            seen.append(dialog.bulk)
            return QDialog.Rejected

        with patch.object(PropertiesDialog, 'exec', reject):
            QTest.mouseClick(self.window.view.viewport(), Qt.LeftButton, pos=point)
            QTest.mouseDClick(self.window.view.viewport(), Qt.LeftButton, pos=point)
            QTest.mouseRelease(self.window.view.viewport(), Qt.LeftButton, pos=point)
        self.assertEqual(seen, [True])

    def test_edge_style_copy_paste_preserves_labels_and_curves(self):
        self.window.add_node(QPointF(200, 0))
        self.window.toggle_edge('1', '2')
        self.window.graph.edges['0', '1']['label'] = 'first'
        self.window.graph.edges['1', '2']['label'] = 'second'
        from graph_builder_lib import _edge_curve_points, _set_edge_curve_points
        _set_edge_curve_points(self.window.graph, '1', '2', [(150, 35)])
        set_overrides(self.window.graph.edges['0', '1'], {'stroke': '#123456', 'width': 5})
        from graph_builder_lib import EdgeRef
        self.window.selection.edges = {EdgeRef('0', '1', False)}
        self.window.copy_selected_style()
        self.window.selection.edges = {EdgeRef('1', '2', False)}
        self.window.paste_selected_style()
        self.assertEqual(self.window.graph.edges['1', '2']['label'], 'second')
        self.assertEqual(_edge_curve_points(self.window.graph, '1', '2'), [(150, 35)])
        self.assertEqual(effective_style(self.window.graph, 'edge', self.window.graph.edges['1', '2'])['width'], 5)
        self.assertEqual(self.window.graph.edges['1', '2']['style_overrides'],
                         self.window.graph.edges['2', '1']['style_overrides'])

    def test_shared_palette_style_is_undoable(self):
        before = self.window._history_index

        def accept(dialog):
            set_palette_style(dialog.graph, 'vertex', 0, {'fill': '#abcdef'})
            return QDialog.Accepted

        with patch.object(StylesDialog, 'exec', accept):
            self.window.edit_shared_styles()
        self.assertEqual(self.window._history_index, before + 1)
        self.assertEqual(effective_style(self.window.graph, 'vertex', self.window.graph.nodes['0'])['fill'], '#abcdef')
        self.window.undo()
        self.assertNotEqual(effective_style(self.window.graph, 'vertex', self.window.graph.nodes['0'])['fill'], '#abcdef')

    def test_named_preset_can_be_applied_to_selected_vertices(self):
        set_preset(self.window.graph, 'vertex', 'marked', 'Marked', {'shape': 'square'})
        self.window.commit_change()
        self.window.node_items['0'].setSelected(True)
        self.window.node_items['1'].setSelected(True)

        def accept(dialog):
            dialog.look_mode.setCurrentIndex(dialog.look_mode.findData('preset'))
            dialog.preset_choice.setCurrentIndex(dialog.preset_choice.findData('marked'))
            return QDialog.Accepted

        with patch.object(PropertiesDialog, 'exec', accept):
            self.window.edit_node_properties('0')
        for node in ('0', '1'):
            self.assertEqual(self.window.graph.nodes[node]['style_preset'], 'marked')
            self.assertEqual(effective_style(self.window.graph, 'vertex', self.window.graph.nodes[node])['shape'], 'square')


if __name__ == '__main__':
    unittest.main()
