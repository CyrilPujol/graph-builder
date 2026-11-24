"""AppearanceController methods hosted by GraphBuilderQt."""
from __future__ import annotations

import copy

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QInputDialog

from graph_builder_core.model.document import set_edge_label, vertex_label
from graph_builder_core.model.edges import edge_data, has_edge
from graph_builder_core.model.regions import region_by_id, set_region_properties, update_region
from graph_builder_core.model.styles import (
    copy_style, effective_style, paste_style, set_overrides, set_edge_style, set_palette_style,
)
from graph_builder_core.ui.properties import PropertiesDialog, RegionPropertiesDialog, StylesDialog


class AppearanceController:
    def rename_node(self, node):
        from PySide6.QtWidgets import QInputDialog
        label, accepted = QInputDialog.getText(self, 'Rename vertex', 'Visible label:',
                                                text=vertex_label(self.graph, node))
        if accepted:
            self.node_items[node].prepareGeometryChange()
            self.graph.nodes[node]['label'] = label
            self.node_items[node].update()
            self.commit_change()

    def rename_edge(self, source, target, key=None):
        from PySide6.QtWidgets import QInputDialog
        label, accepted = QInputDialog.getText(self, 'Rename edge', 'Visible label:',
                                                text=edge_data(self.graph, source, target, key).get('label', ''))
        if accepted:
            item = self.edge_items.get(self.edge_key(source, target, key))
            if item:
                item.prepareGeometryChange()
            set_edge_label(self.graph, source, target, label, key)
            if item:
                item.update()
            self.commit_change()

    def rename_selection(self):
        if self.selection.single_node() is not None:
            self.rename_node(self.selection.single_node())
        elif len(self.selection.edges) == 1 and not self.selection.nodes:
            edge = next(iter(self.selection.edges))
            self.rename_edge(edge.source, edge.target, edge.key)
        elif len(self.selection.regions) == 1 and not self.selection.nodes and not self.selection.edges:
            self.edit_region_properties(next(iter(self.selection.regions)))

    def edit_node_properties(self, node):
        nodes = ([n for n in self.graph if n in self.selection.nodes]
                 if node in self.selection.nodes and len(self.selection.nodes) > 1 else [node])
        source_graph = self.graph
        editor = PropertiesDialog(self.graph, 'vertex',
                                  [dict(self.graph.nodes[n], label=vertex_label(self.graph, n))
                                   for n in nodes],
                                  bulk=len(nodes) > 1, parent=self)
        editor.preview_changed.connect(
            lambda: self._preview_node_properties(editor, nodes, source_graph))
        editor.finished.connect(
            lambda result: self._finish_node_properties(editor, nodes, source_graph, result))
        self._show_style_editor(editor)
        return editor

    def _write_node_properties(self, graph, dialog, nodes):
        node = nodes[0]
        changes = dialog.changes()
        if dialog.shared_style_update is not None:
            index, style = dialog.shared_style_update
            set_palette_style(graph, 'vertex', index, style)
        for current, color in zip(nodes, dialog.type_values()):
            attributes = graph.nodes[current]
            attributes['style'] = color
            set_overrides(attributes, changes)
            if dialog.clear_preset():
                attributes.pop('style_preset', None)
        if dialog.label_edit is not None and dialog.label_edit.text() != vertex_label(graph, node):
            graph.nodes[node]['label'] = dialog.label_edit.text()

    def _preview_node_properties(self, dialog, nodes, source_graph):
        if not dialog._valid_colors(dialog.changes(), warn=False):
            return
        preview = copy.deepcopy(source_graph)
        self._write_node_properties(preview, dialog, nodes)
        self.graph = preview
        self.rebuild_scene()

    def _finish_node_properties(self, dialog, nodes, source_graph, result):
        before_styles = {node: effective_style(source_graph, 'vertex', source_graph.nodes[node])
                         for node in nodes}
        before_types = {node: source_graph.nodes[node].get('style', 0) for node in nodes}
        self.graph = source_graph
        if result == PropertiesDialog.Accepted:
            self._write_node_properties(self.graph, dialog, nodes)
        self.rebuild_scene()
        if result == PropertiesDialog.Accepted:
            self.commit_change()
            if any(self.graph.nodes[node].get('style', 0) != before_types[node] or
                   effective_style(self.graph, 'vertex', self.graph.nodes[node]) != style
                   for node, style in before_styles.items()):
                self._observe_tutorial('change_appearance')

    def edit_edge_properties(self, source, target, key=None):
        selected = self.edge_key(source, target, key)
        edges = ([(edge.source, edge.target, edge.key) for edge in self.selection.edges]
                 if any(self.edge_key(edge.source, edge.target, edge.key) == selected
                        for edge in self.selection.edges) and len(self.selection.edges) > 1
                 else [(source, target, key)])
        source_graph = self.graph
        editor = PropertiesDialog(self.graph, 'edge',
                                  [edge_data(self.graph, *pair) for pair in edges],
                                  bulk=len(edges) > 1, parent=self)
        editor.preview_changed.connect(
            lambda: self._preview_edge_properties(editor, edges, source_graph))
        editor.finished.connect(
            lambda result: self._finish_edge_properties(editor, edges, source_graph, result))
        self._show_style_editor(editor)
        return editor

    def _write_edge_properties(self, graph, dialog, edges):
        source, target, key = edges[0]
        if dialog.shared_style_update is not None:
            index, style = dialog.shared_style_update
            set_palette_style(graph, 'edge', index, style)
        for (first, second, edge_id), color in zip(edges, dialog.type_values()):
            edge_data(graph, first, second, edge_id)['style'] = color
            if graph.graph.get('graph_type') == 'graph' and has_edge(graph, second, first, edge_id):
                edge_data(graph, second, first, edge_id)['style'] = color
            set_edge_style(graph, first, second, dialog.changes(),
                           '' if dialog.clear_preset() else None, key=edge_id)
        if dialog.label_edit is not None:
            set_edge_label(graph, source, target, dialog.label_edit.text(), key)

    def _preview_edge_properties(self, dialog, edges, source_graph):
        if not dialog._valid_colors(dialog.changes(), warn=False):
            return
        preview = copy.deepcopy(source_graph)
        self._write_edge_properties(preview, dialog, edges)
        self.graph = preview
        self.rebuild_scene()

    def _finish_edge_properties(self, dialog, edges, source_graph, result):
        self.graph = source_graph
        if result == PropertiesDialog.Accepted:
            self._write_edge_properties(self.graph, dialog, edges)
        self.rebuild_scene()
        if result == PropertiesDialog.Accepted:
            self.commit_change()

    def edit_selection_properties(self):
        if self.selection.nodes:
            self.edit_node_properties(next(iter(self.selection.nodes)))
        elif self.selection.edges:
            edge = next(iter(self.selection.edges))
            self.edit_edge_properties(edge.source, edge.target, edge.key)
        elif self.selection.regions:
            self.edit_region_properties(next(iter(self.selection.regions)))

    def edit_region_properties(self, identifier):
        region = region_by_id(self.graph, identifier)
        if region is None:
            return None
        source_graph = self.graph
        self._regions_without_selection_cue.add(identifier)
        if identifier in self.region_items:
            self.region_items[identifier].update()
        editor = RegionPropertiesDialog(region, source_graph, self)
        editor.preview_changed.connect(
            lambda: self._preview_region_properties(editor, identifier, source_graph))
        editor.finished.connect(
            lambda result: self._finish_region_properties(editor, identifier, source_graph, result))
        self._show_style_editor(editor)
        return editor

    def _preview_region_properties(self, dialog, identifier, source_graph):
        values = dialog.values()
        if any(value != 'none' and not QColor(value).isValid()
               for value in (values['style']['fill'], values['style']['outline'])):
            return
        preview = copy.deepcopy(source_graph)
        try:
            set_region_properties(preview, identifier, values)
        except ValueError:
            return
        self.graph = preview
        self.rebuild_scene()

    def _finish_region_properties(self, dialog, identifier, source_graph, result):
        self._regions_without_selection_cue.discard(identifier)
        self.graph = source_graph
        if result == RegionPropertiesDialog.Accepted:
            set_region_properties(self.graph, identifier, dialog.values())
        self.rebuild_scene()
        if result == RegionPropertiesDialog.Accepted:
            self.commit_change()

    def edit_shared_styles(self):
        source_graph = self.graph
        editor = StylesDialog(self.graph, self)
        editor.preview_changed.connect(lambda: self._preview_type_styles(editor))
        editor.finished.connect(
            lambda result: self._finish_type_styles(editor, source_graph, result))
        self._show_style_editor(editor)
        return editor

    def _preview_type_styles(self, dialog):
        preview = dialog.preview_graph()
        if preview is not None:
            self.graph = preview
            self.rebuild_scene()

    def _finish_type_styles(self, dialog, source_graph, result):
        self.graph = source_graph
        if result == StylesDialog.Accepted:
            self._apply_type_styles(dialog, source_graph)
        else:
            self.rebuild_scene()

    def _show_style_editor(self, editor):
        """Show a normal parented dialog without starting a nested event loop."""
        self._active_style_dialog = editor
        editor.setWindowModality(Qt.ApplicationModal)
        editor.finished.connect(lambda result: self._release_style_editor(editor))
        editor.show()

    def _release_style_editor(self, editor):
        if self._active_style_dialog is editor:
            self._active_style_dialog = None
        editor.deleteLater()

    def _apply_type_styles(self, dialog, source_graph):
        for key in ('vertex_styles', 'edge_styles'):
            if key in dialog.graph.graph:
                self.graph.graph[key] = copy.deepcopy(dialog.graph.graph[key])
            else:
                self.graph.graph.pop(key, None)
        self.rebuild_scene()
        self.commit_change()

    def copy_selected_style(self):
        if len(self.selection.nodes) == 1 and not self.selection.edges and not self.selection.regions:
            node = next(iter(self.selection.nodes))
            self.style_clipboard = ('vertex', copy_style(self.graph, 'vertex', self.graph.nodes[node]))
        elif len(self.selection.edges) == 1 and not self.selection.nodes and not self.selection.regions:
            edge = next(iter(self.selection.edges))
            self.style_clipboard = ('edge', copy_style(self.graph, 'edge',
                                                      edge_data(self.graph, edge.source, edge.target, edge.key)))
        elif len(self.selection.regions) == 1 and not self.selection.nodes and not self.selection.edges:
            region = region_by_id(self.graph, next(iter(self.selection.regions)))
            self.style_clipboard = ('region', copy.deepcopy(region['style']))
        self.update_actions()

    def paste_selected_style(self):
        if not self.style_clipboard:
            return
        kind, snapshot = self.style_clipboard
        if kind == 'vertex':
            for node in self.selection.nodes:
                paste_style(self.graph.nodes[node], snapshot)
        elif kind == 'edge':
            for edge in self.selection.edges:
                set_edge_style(self.graph, edge.source, edge.target, snapshot, '', key=edge.key)
        else:
            for identifier in self.selection.regions:
                update_region(self.graph, identifier, {'style': copy.deepcopy(snapshot)})
        self.rebuild_scene()
        self.commit_change()
