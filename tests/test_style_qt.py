"""Properties dialog and canvas styling integration."""
import os
import json
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QEvent, QObject, QPointF
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

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

        dialog = self.window.edit_node_properties('0')
        self.assertTrue(dialog.bulk)
        self.assertIsNone(dialog.label_edit)
        self.assertEqual(dialog.look_mode.currentData(), 'keep')
        dialog.change_type(1)
        dialog._accept()
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
        self.window.edit_node_properties('0').reject()
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

        dialog = self.window.edit_node_properties('0')
        self.assertEqual(dialog.look_mode.currentData(), 'custom')
        dialog.label_edit.setText('New label')
        dialog._accept()
        self.assertEqual(json.loads(self.window.graph.nodes['0']['style_overrides']),
                         {'fill': '#123456'})

    def test_advanced_collapse_resizes_without_stretching_type_control(self):
        previous = PropertiesDialog.advanced_open
        try:
            PropertiesDialog.advanced_open = False
            dialog = PropertiesDialog(self.window.graph, 'vertex',
                                      [dict(self.window.graph.nodes['0'], label='0')],
                                      parent=self.window)
            dialog.show()
            dialog.advanced_toggle.setChecked(True)
            self.app.processEvents()
            expanded_height = dialog.height()
            step = dialog.findChild(QWidget, 'type_step')
            self.assertEqual((step.width(), step.height()), (62, 31))
            dialog.advanced_toggle.setChecked(False)
            self.app.processEvents()
            self.assertLess(dialog.height(), expanded_height / 2)
            self.assertEqual((step.width(), step.height()), (62, 31))
            self.assertLess(dialog.advanced_toggle.y(), 100)
            dialog.close()
        finally:
            PropertiesDialog.advanced_open = previous

    def test_properties_children_never_open_as_separate_windows(self):
        shown_as_window = []

        class WindowSpy(QObject):
            def eventFilter(self, widget, event):
                if event.type() == QEvent.Show and isinstance(widget, QWidget):
                    relevant = (widget.objectName() == 'style_advanced_panel' or
                                isinstance(widget, QPushButton) and widget.text() == 'Style ▾')
                    if relevant and widget.isWindow():
                        shown_as_window.append(widget)
                return False

        spy = WindowSpy()
        previous = PropertiesDialog.advanced_open
        self.app.installEventFilter(spy)
        try:
            for expanded in (False, True):
                PropertiesDialog.advanced_open = expanded
                dialog = PropertiesDialog(self.window.graph, 'vertex',
                                          [dict(self.window.graph.nodes['0'], label='0')],
                                          parent=self.window)
                dialog.show()
                self.app.processEvents()
                self.assertIs(dialog.advanced_toggle.parent(), dialog)
                self.assertIs(dialog.advanced_widget.parent(), dialog)
                dialog.close()
        finally:
            self.app.removeEventFilter(spy)
            PropertiesDialog.advanced_open = previous
        self.assertEqual(shown_as_window, [])

    def test_double_click_on_selected_group_opens_bulk_properties(self):
        canvas = self.window.view.viewport()
        self.window.node_items['0'].setSelected(True)
        self.window.node_items['1'].setSelected(True)
        point = self.window.view.mapFromScene(QPointF(0, 0))
        QTest.mouseClick(canvas, Qt.LeftButton, pos=point)
        QTest.mouseDClick(canvas, Qt.LeftButton, pos=point)
        QTest.mouseRelease(canvas, Qt.LeftButton, pos=point)
        self.assertTrue(self.window._active_style_dialog.isVisible())
        self.assertTrue(self.window._active_style_dialog.bulk)
        self.window._active_style_dialog.reject()
        self.assertEqual(self.window.selection.nodes, {'0', '1'})

    def test_double_click_on_selected_edges_opens_bulk_properties(self):
        self.window.add_node(QPointF(200, 0))
        self.window.toggle_edge('1', '2')
        for item in self.window.edge_items.values():
            item.setSelected(True)
        point = self.window.view.mapFromScene(QPointF(50, 0))
        QTest.mouseClick(self.window.view.viewport(), Qt.LeftButton, pos=point)
        QTest.mouseDClick(self.window.view.viewport(), Qt.LeftButton, pos=point)
        QTest.mouseRelease(self.window.view.viewport(), Qt.LeftButton, pos=point)
        self.assertTrue(self.window._active_style_dialog.isVisible())
        self.assertTrue(self.window._active_style_dialog.bulk)
        self.window._active_style_dialog.reject()

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

        dialog = self.window.edit_shared_styles()
        dialog.editor.controls['fill'].setText('#abcdef')
        dialog._accept()
        self.assertEqual(self.window._history_index, before + 1)
        self.assertEqual(effective_style(self.window.graph, 'vertex', self.window.graph.nodes['0'])['fill'], '#abcdef')
        self.window.undo()
        self.assertNotEqual(effective_style(self.window.graph, 'vertex', self.window.graph.nodes['0'])['fill'], '#abcdef')

    def test_type_reset_button_restores_builtin_look_and_undoes(self):
        set_palette_style(self.window.graph, 'vertex', 0, {'fill': '#abcdef'})
        self.window.rebuild_scene()
        self.window.commit_change()
        dialog = self.window.edit_shared_styles()
        self.assertEqual(dialog.editor.controls['fill'].text(), '#abcdef')
        dialog.reset_button.click()
        self.assertEqual(dialog.editor.controls['fill'].text(), '#ffffff')
        dialog._accept()
        self.assertEqual(effective_style(self.window.graph, 'vertex', self.window.graph.nodes['0'])['fill'], '#ffffff')
        self.assertNotIn('vertex_styles', self.window.graph.graph)
        self.window.undo()
        self.assertEqual(effective_style(self.window.graph, 'vertex', self.window.graph.nodes['0'])['fill'], '#abcdef')

    def test_type_styles_browse_with_embedded_preview_and_no_second_window(self):
        dialog = StylesDialog(self.window.graph, self.window)
        self.assertFalse(dialog.editor.isWindow())
        dialog.editor.controls['fill'].setText('#abcdef')
        dialog.slot.setValue(1)
        self.assertEqual(effective_style(dialog.graph, 'vertex', {'col': 0})['fill'], '#abcdef')
        self.assertEqual(dialog.editor.preview_style()['fill'],
                         effective_style(dialog.graph, 'vertex', {'col': 1})['fill'])
        dialog.slot.setValue(0)
        self.assertEqual(dialog.editor.controls['fill'].text(), '#abcdef')
        dialog.kind.setCurrentText('edge')
        self.assertFalse(dialog.editor.isWindow())
        self.assertEqual(dialog.editor.kind, 'edge')
        self.assertIn('stroke', dialog.editor.controls)
        dialog.reject()
        self.assertNotEqual(effective_style(self.window.graph, 'vertex', self.window.graph.nodes['0'])['fill'], '#abcdef')

    def test_style_editors_use_normal_parented_windows(self):
        properties = self.window.edit_node_properties('0')
        self.assertTrue(properties.isVisible())
        self.assertTrue(properties.isWindow())
        self.assertIs(properties.parent(), self.window)
        self.assertEqual(properties.windowModality(), Qt.ApplicationModal)
        properties.reject()
        self.assertIsNone(self.window._active_style_dialog)
        styles = self.window.edit_shared_styles()
        self.assertTrue(styles.isVisible())
        self.assertTrue(styles.isWindow())
        self.assertIs(styles.parent(), self.window)
        self.assertEqual(styles.windowModality(), Qt.ApplicationModal)
        styles.reject()

    def test_style_section_exposes_types_not_named_presets(self):
        dialog = StylesDialog(self.window.graph, self.window)
        for kind in ('vertex', 'edge'):
            dialog.kind.setCurrentText(kind)
            self.assertEqual(dialog.windowTitle(), 'Type styles')
            self.assertFalse(hasattr(dialog, 'preset'))
        properties = PropertiesDialog(self.window.graph, 'vertex',
                                      [dict(self.window.graph.nodes['0'], label='0')], parent=self.window)
        self.assertEqual(properties.advanced_toggle.text(), 'Style ▾')
        self.assertEqual(properties.look_mode.findData('preset'), -1)
        self.assertFalse(hasattr(properties, 'preset_choice'))

    def test_apply_custom_look_to_vertex_type_is_one_undoable_action(self):
        before = self.window._history_index

        dialog = self.window.edit_node_properties('0')
        dialog.look_mode.setCurrentIndex(dialog.look_mode.findData('custom'))
        dialog.controls['fill'].setText('#abcdef')
        dialog.apply_look_to_type()
        self.assertEqual(dialog.look_mode.currentData(), 'inherit')
        self.assertEqual(dialog.shared_style_update[0], 0)
        dialog._accept()
        self.assertEqual(self.window._history_index, before + 1)
        for node in ('0', '1'):
            self.assertEqual(effective_style(self.window.graph, 'vertex', self.window.graph.nodes[node])['fill'], '#abcdef')
        self.assertNotIn('style_overrides', self.window.graph.nodes['0'])
        self.window.undo()
        self.assertNotEqual(effective_style(self.window.graph, 'vertex', self.window.graph.nodes['1'])['fill'], '#abcdef')

    def test_cancel_after_apply_to_type_does_not_change_graph(self):
        before = self.window._history_index

        dialog = self.window.edit_node_properties('0')
        dialog.look_mode.setCurrentIndex(dialog.look_mode.findData('custom'))
        dialog.controls['fill'].setText('#abcdef')
        dialog.apply_look_to_type()
        dialog.reject()
        self.assertEqual(self.window._history_index, before)
        self.assertNotEqual(effective_style(self.window.graph, 'vertex', self.window.graph.nodes['1'])['fill'], '#abcdef')

    def test_apply_custom_look_to_edge_type_updates_other_edges(self):
        self.window.add_node(QPointF(200, 0))
        self.window.toggle_edge('1', '2')

        dialog = self.window.edit_edge_properties('0', '1')
        dialog.look_mode.setCurrentIndex(dialog.look_mode.findData('custom'))
        dialog.controls['width'].setValue(6)
        dialog.apply_look_to_type()
        dialog._accept()
        for edge in (('0', '1'), ('1', '2')):
            self.assertEqual(effective_style(self.window.graph, 'edge', self.window.graph.edges[edge])['width'], 6)

    def test_legacy_named_preset_remains_readable_but_is_not_in_menu(self):
        set_preset(self.window.graph, 'vertex', 'marked', 'Marked', {'shape': 'square'})
        self.window.graph.nodes['0']['style_preset'] = 'marked'
        dialog = PropertiesDialog(self.window.graph, 'vertex',
                                  [dict(self.window.graph.nodes['0'], label='0')], parent=self.window)
        self.assertEqual(dialog.look_mode.currentData(), 'custom')
        self.assertEqual(dialog.look_mode.findData('preset'), -1)
        self.assertEqual(dialog.preview_style()['shape'], 'square')


if __name__ == '__main__':
    unittest.main()
