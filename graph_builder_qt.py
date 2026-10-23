"""Qt application shell for Graph Builder.

The graph model and custom actions live in ``graph_builder_lib`` and
``graph_builder.py``. Canvas rendering and pointer gestures live in
``graph_builder_qt_canvas``. This module owns menus, controls, history and files.
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QCursor, QKeySequence, QTransform
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QTabWidget, QToolBar, QToolButton,
    QVBoxLayout, QWidget,
)

from graph_builder_lib import (
    Action, EdgeRef, EditorContext, SelectionState, _deserialize_graph,
    _edge_curve_points, _serialize_graph, _set_edge_curve_points,
    convert_from_file, copy_graph_selection, cut_edges_to_rest, empty_graph,
    execute_action, flip_edge, labels_visible, logical_edges, nearest_grid_point,
    paste_graph_selection, set_directed, set_edge_label, unused_label,
    vertex_label, write_graph_file,
)
from graph_builder_qt_canvas import (
    COORDINATE_UNIT, DEFAULT_GRID_PRECISION, CurveHandle, EdgeItem, GraphScene,
    GraphView, NodeItem,
)
from tikz_export import write_tikz


class MessageSurface:
    """Small compatibility surface for custom actions that report on canvas."""
    def __init__(self, window):
        self.window = window

    def write(self, message, duration=5, screen_relative_position=(.8, .2)):
        self.window.report(message, duration)


class StepControl(QWidget):
    """Stable-width decrement/increment pair with one shared container."""
    def __init__(self, decrease, increase, parent=None, show_disabled_labels=False):
        super().__init__(parent)
        self.show_disabled_labels = show_disabled_labels
        self.decrease = QToolButton(self)
        self.increase = QToolButton(self)
        for button, label, action in ((self.decrease, '-', decrease),
                                      (self.increase, '+', increase)):
            button.setText(label)
            button.setFixedSize(26, 24)
            font = button.font()
            font.setPixelSize(18)
            font.setBold(True)
            button.setFont(font)
            button.setToolTip(action.toolTip())
            button.clicked.connect(action.trigger)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)
        layout.addWidget(self.decrease)
        layout.addWidget(self.increase)
        self.setFixedSize(56, 28)
        self.setStyleSheet('''
            StepControl { border: 1px solid #7f858b; border-radius: 5px; }
            StepControl QToolButton { border: 0; border-radius: 3px; background: #e4e6e9;
                                      color: #111111; padding: 0; margin: 0; }
            StepControl QToolButton:hover:enabled { background: #d7dce0; }
            StepControl QToolButton:disabled { color: #777d84; background: #f0f1f2;
                                               border: 0; }
            StepControl:disabled { border-color: #d7dadd; }
        ''')

    def set_limits(self, can_decrease, can_increase):
        self.decrease.setEnabled(can_decrease)
        self.increase.setEnabled(can_increase)
        self.decrease.setText('-' if can_decrease or self.show_disabled_labels else ' ')
        self.increase.setText('+' if can_increase or self.show_disabled_labels else ' ')


class CollapsibleTabWidget(QTabWidget):
    """A compact tab row whose active tab can be clicked closed."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._open_index = -1
        self.tabBarClicked.connect(self._tab_clicked)

    def open_tab(self, index):
        self._open_index = index
        self.tabBar().setProperty('menuOpen', True)
        self.setMaximumHeight(16777215)
        self.setCurrentIndex(index)
        if self.currentWidget() is not None:
            self.currentWidget().show()
        self._refresh_tab_style()

    def close_tab(self):
        self._open_index = -1
        self.tabBar().setProperty('menuOpen', False)
        if self.currentWidget() is not None:
            self.currentWidget().hide()
        self.setMaximumHeight(self.tabBar().sizeHint().height() + 2)
        self._refresh_tab_style()

    def _refresh_tab_style(self):
        self.tabBar().style().unpolish(self.tabBar())
        self.tabBar().style().polish(self.tabBar())
        self.tabBar().update()

    def _tab_clicked(self, index):
        close = index == self._open_index
        QTimer.singleShot(0, self.close_tab if close else lambda: self.open_tab(index))


class GraphBuilderQt(QMainWindow):
    def __init__(self, graph=None, path=None, actions=()):
        super().__init__()
        self.graph = graph if graph is not None else empty_graph()
        self.path = Path(path) if path is not None else None
        self.custom_actions = tuple(actions)
        if any(not isinstance(action, Action) for action in self.custom_actions):
            raise TypeError('Custom actions must be graph_builder_lib.Action values')
        self.node_items = {}
        self.edge_items = {}
        self.curve_handles = []
        self.selection = SelectionState()
        self.clipboard = None
        self.grid_mode = None
        self.grid_origin = QPointF(0, 0)
        self.grid_unit = DEFAULT_GRID_PRECISION
        self.radial_divisions = 5
        self.vertex_color = 0
        self.edge_color = 0
        self.last_canvas_position = QPointF(0, 0)
        self._rebuilding = False
        self._updating_handles = False
        self._history = [copy.deepcopy(_serialize_graph(self.graph))]
        self._history_index = 0
        self._saved_state = copy.deepcopy(self._history[0])
        self.message_surface = MessageSurface(self)

        self.setWindowTitle('Graph Builder')
        self.resize(1160, 800)
        self.scene = GraphScene(self)
        self.scene.selectionChanged.connect(self.selection_changed)
        self.view = GraphView(self.scene)
        self.information_label = QLabel(self.view.viewport())
        self.information_label.setFrameShape(QFrame.StyledPanel)
        self.information_label.setWordWrap(True)
        self.information_label.setFixedWidth(270)
        self.information_label.setStyleSheet('background: rgba(255, 255, 255, 235); color: #111111; padding: 8px; border-radius: 5px; font-size: 13px;')
        self.information_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.information_label.hide()
        self.view.message_label = self.information_label
        self._message_timer = QTimer(self)
        self._message_timer.setSingleShot(True)
        self._message_timer.timeout.connect(self.information_label.hide)
        self._build_actions()
        self._build_controls()
        self.rebuild_scene()
        self.view.centerOn(self.grid_origin)
        self.statusBar().showMessage('Click to create/select/move; secondary-drag vertices for edges; Alt-drag to pan.')
        self.update_actions()

    @property
    def is_directed(self):
        return self.graph.graph.get('graph_type') != 'graph'

    def context(self):
        viewport = self.view.viewport()
        local = viewport.mapFromGlobal(QCursor.pos())
        pointer = self.view.mapToScene(local) if viewport.rect().contains(local) else self.last_canvas_position
        return EditorContext(self.graph, self.selection, self.message_surface, self,
                             tuple(pointer.toTuple()))

    def report(self, message, duration=5):
        self.statusBar().showMessage(str(message).replace('\n', '  ·  '), int(duration * 1000))
        self.information_label.setText(str(message).replace('\n', '<br>'))
        self.information_label.adjustSize()
        self.view.position_message()
        self.information_label.show()
        self._message_timer.start(int(duration * 1000))

    def _action(self, label, callback, shortcut=None, checkable=False):
        action = QAction(label, self)
        action.setCheckable(checkable)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(callback)
        self._set_action_tooltip(action)
        return action

    @staticmethod
    def _set_action_tooltip(action):
        shortcuts = [('Esc' if sequence == QKeySequence(Qt.Key_Escape)
                      else sequence.toString(QKeySequence.NativeText))
                     for sequence in action.shortcuts() if not sequence.isEmpty()]
        suffix = f' — {", ".join(shortcuts)}' if shortcuts else ''
        action.setToolTip(f'{action.text().replace("&", "")}{suffix}')

    def _build_actions(self):
        self.new_action = self._action('New', self.new_file, QKeySequence.New)
        self.open_action = self._action('Open…', self.open_file, QKeySequence.Open)
        self.save_action = self._action('Save', self.save_file, QKeySequence.Save)
        self.save_as_action = self._action('Save As…', self.save_as, QKeySequence.SaveAs)
        self.export_action = self._action('Export to TikZ…', self.export_tikz, 'Ctrl+E')
        self.close_action = self._action('Quit', self.close, QKeySequence.Quit)

        self.undo_action = self._action('Undo', self.undo, QKeySequence.Undo)
        self.redo_action = self._action('Redo', self.redo, QKeySequence.Redo)
        self.copy_action = self._action('Copy', self.copy_selection, QKeySequence.Copy)
        self.paste_action = self._action('Paste', self.paste_selection, QKeySequence.Paste)
        self.select_all_action = self._action('Select all', self.select_all_vertices,
                                              QKeySequence.SelectAll)
        self.delete_action = self._action('Delete', self.delete_selection)
        # On a Mac keyboard the key labelled "delete" sends Backspace.  Keep
        # forward Delete as an alternative for full-size and non-Mac keyboards.
        self.delete_action.setShortcuts((QKeySequence(Qt.Key_Backspace),
                                         QKeySequence(Qt.Key_Delete)))
        self._set_action_tooltip(self.delete_action)
        self.rename_action = self._action('Rename…', self.rename_selection)
        self.deselect_action = self._action('Deselect', self.deselect, 'Escape')

        self.add_curve_action = self._action('Curve point', self.add_curve_point, 'A')
        self.color_action = self._action('Next color', self.next_color, 'C')
        self.cut_action = self._action('Cut selection', self.cut_edges, 'T')
        self.fit_action = self._action('Fit graph', self.fit_graph, 'Ctrl+0')

        self.labels_action = self._action('Labels', self.set_labels, 'L', checkable=True)
        self.labels_action.setChecked(labels_visible(self.graph))
        self.directed_action = self._action('Directed', self.set_directed, checkable=True)
        self.directed_action.setChecked(self.is_directed)
        self.grid_off_action = self._action('No grid', lambda: self.set_grid(None), checkable=True)
        self.grid_square_action = self._action('Square grid', lambda: self.set_grid(None if self.grid_mode == 'square' else 'square'), checkable=True)
        self.grid_triangular_action = self._action('Triangular grid', lambda: self.set_grid(None if self.grid_mode == 'triangular' else 'triangular'), checkable=True)
        self.grid_radial_action = self._action('Radial grid', lambda: self.set_grid(None if self.grid_mode == 'radial' else 'radial'), checkable=True)
        self.grid_group = QActionGroup(self)
        self.grid_group.setExclusive(True)
        for action in (self.grid_off_action, self.grid_square_action,
                       self.grid_radial_action, self.grid_triangular_action):
            self.grid_group.addAction(action)
        self.grid_off_action.setChecked(True)
        self.grid_down_action = self._action('Decrease grid precision (larger cells)',
                                           lambda: self.change_grid_unit(2))
        self.grid_up_action = self._action('Increase grid precision (smaller cells)',
                                         lambda: self.change_grid_unit(1/2))
        self.radial_down_action = self._action('Fewer radials', lambda: self.change_radials(-1))
        self.radial_up_action = self._action('More radials', lambda: self.change_radials(1))
        self.vertex_colors_down_action = self._action('Fewer vertex colors', lambda: self.change_vertex_colors(self.graph.graph['num_vertex_colors'] - 1))
        self.vertex_colors_up_action = self._action('More vertex colors', lambda: self.change_vertex_colors(self.graph.graph['num_vertex_colors'] + 1))
        self.edge_colors_down_action = self._action('Fewer edge colors', lambda: self.change_edge_colors(self.graph.graph['num_edge_colors'] - 1))
        self.edge_colors_up_action = self._action('More edge colors', lambda: self.change_edge_colors(self.graph.graph['num_edge_colors'] + 1))

        self.extension_actions = []
        for definition in self.custom_actions:
            qt_action = self._action(definition.display_name(self.context()),
                                     lambda checked=False, action=definition: self.run_extension(action),
                                     definition.shortcut)
            self.extension_actions.append((definition, qt_action))

    def _build_controls(self):
        """A compact menu row with one context-sensitive button row beneath it."""
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        tabs = CollapsibleTabWidget(container)
        tabs.setDocumentMode(True)
        tabs.setUsesScrollButtons(True)
        tabs.setStyleSheet('''
            QTabWidget::pane { background: #f5f6f7; border: 0; }
            QTabBar::tab { color: #111111; background: #e6e7e9; padding: 5px 10px; }
            QTabBar::tab:selected { color: #111111; background: #f5f6f7; }
            QTabBar[menuOpen="false"]::tab:selected { background: #e6e7e9; }
            QTabBar::tab:disabled { color: #8a8f96; }
        ''')
        self.menu_tabs = tabs

        def row(name, actions=()):
            toolbar = QToolBar(name, tabs)
            toolbar.setMovable(False)
            toolbar.setFloatable(False)
            toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)
            toolbar.setStyleSheet('''
                QToolBar { border: 0; padding: 2px; background: #f5f6f7; }
                QToolBar QLabel { color: #111111; }
                QToolBar QLabel:disabled { color: #777d84; }
                QToolBar > QToolButton { border: 1px solid #d0d4d9; border-radius: 4px;
                                       color: #111111; background: #f5f6f7;
                                       padding: 4px 7px; margin-right: 3px; }
                QToolBar > QToolButton:hover:enabled { background: #e6ecee; }
                QToolBar > QToolButton:checked { color: #111111; background: #d4e7e8;
                                                 border-color: #96b9bc; }
                QToolBar > QToolButton:disabled { color: #777d84; background: #f1f2f3;
                                                  border-color: #777d84; }
            ''')
            toolbar.addActions(actions)
            tabs.addTab(toolbar, name)
            return toolbar

        file_row = row('File', (self.new_action, self.open_action, self.save_action,
                                self.save_as_action, self.export_action))
        file_row.addSeparator()
        file_row.addActions((self.undo_action, self.redo_action,
                             self.select_all_action, self.fit_action))

        basic_row = row('Basic', (self.rename_action, self.delete_action,
                                  self.copy_action, self.paste_action, self.color_action,
                                  self.add_curve_action, self.cut_action))
        self.paired_extension_controls = []
        for definition, action in self.extension_actions:
            if definition.group == 'basic' and not definition.pair_id:
                basic_row.addAction(action)
        pairs = {}
        for definition, action in self.extension_actions:
            if definition.group == 'basic' and definition.pair_id:
                pairs.setdefault(definition.pair_id, []).append((definition, action))
        for pair in pairs.values():
            if len(pair) != 2:
                raise ValueError('Paired actions must have exactly two members')
            label = pair[0][0].pair_label or pair[0][0].pair_id
            label_widget = QLabel(f'  {label}:', basic_row)
            label_action = basic_row.addWidget(label_widget)
            control = StepControl(pair[0][1], pair[1][1], basic_row,
                                  show_disabled_labels=pair[0][0].pair_id == 'rotate')
            control_action = basic_row.addWidget(control)
            self.paired_extension_controls.append((label_action, control_action,
                                                    control, pair[0][1], pair[1][1]))

        grid_row = row('Grid', (self.grid_off_action, self.grid_square_action,
                                self.grid_radial_action, self.grid_triangular_action))
        self.grid_unit_label = QLabel(grid_row)
        self.grid_unit_label_action = grid_row.addWidget(self.grid_unit_label)
        self.grid_unit_control = StepControl(self.grid_down_action, self.grid_up_action, grid_row)
        self.grid_unit_control_action = grid_row.addWidget(self.grid_unit_control)
        self.radial_label = QLabel(grid_row)
        self.radial_label_action = grid_row.addWidget(self.radial_label)
        self.radial_control = StepControl(self.radial_down_action, self.radial_up_action, grid_row)
        self.radial_control_action = grid_row.addWidget(self.radial_control)

        properties_row = row('Graph properties', (self.labels_action, self.directed_action))
        self.vertex_colors_label = QLabel(properties_row)
        properties_row.addWidget(self.vertex_colors_label)
        self.vertex_colors_control = StepControl(self.vertex_colors_down_action,
                                                  self.vertex_colors_up_action, properties_row)
        properties_row.addWidget(self.vertex_colors_control)
        self.edge_colors_label = QLabel(properties_row)
        properties_row.addWidget(self.edge_colors_label)
        self.edge_colors_control = StepControl(self.edge_colors_down_action,
                                                self.edge_colors_up_action, properties_row)
        properties_row.addWidget(self.edge_colors_control)

        custom = [action for definition, action in self.extension_actions if definition.group != 'basic']
        row('Custom', custom)
        tabs.open_tab(0)
        layout.addWidget(tabs)
        layout.addWidget(self.view, 1)
        self.setCentralWidget(container)
        # Actions in inactive tabs still need their keyboard shortcuts active.
        for action in (self.new_action, self.open_action, self.save_action, self.save_as_action,
                       self.close_action, self.undo_action, self.redo_action, self.copy_action,
                       self.paste_action, self.delete_action, self.rename_action,
                       self.deselect_action, self.select_all_action,
                       self.add_curve_action, self.color_action, self.cut_action, self.fit_action,
                       self.labels_action,
                       *(item for _, item in self.extension_actions)):
            if not action.shortcut().isEmpty():
                self.addAction(action)
        self._sync_controls()

    def _sync_controls(self):
        self.labels_action.setChecked(labels_visible(self.graph))
        self.directed_action.setChecked(self.is_directed)
        self.vertex_colors_label.setText(f'  Vertex colors: {self.graph.graph.get("num_vertex_colors", 4)} ')
        self.edge_colors_label.setText(f'  Edge colors: {self.graph.graph.get("num_edge_colors", 2)} ')
        self.grid_unit_label.setText('  Grid precision: ')
        self.radial_label.setText(f'  Radials: {self.radial_divisions} ')
        self.grid_unit_label_action.setVisible(self.grid_mode is not None)
        self.radial_label_action.setVisible(self.grid_mode == 'radial')
        self.grid_unit_control_action.setVisible(self.grid_mode is not None)
        self.radial_control_action.setVisible(self.grid_mode == 'radial')

    def selection_changed(self):
        if self._rebuilding or self._updating_handles:
            return
        try:
            selected_items = self.scene.selectedItems()
        except RuntimeError:
            # Qt can emit this while tearing down the scene at application exit.
            return
        self.selection.clear()
        for item in selected_items:
            if isinstance(item, NodeItem):
                self.selection.nodes.add(item.node)
            elif isinstance(item, EdgeItem):
                self.selection.edges.add(EdgeRef(item.source, item.target, self.is_directed))
            elif isinstance(item, CurveHandle):
                self.selection.edges.add(EdgeRef(item.source, item.target, self.is_directed))
        self._update_curve_handles()
        self.update_actions()

    def _update_curve_handles(self):
        wanted = {(edge.source, edge.target, index)
                  for edge in self.selection.edges
                  for index, _ in enumerate(_edge_curve_points(self.graph, edge.source, edge.target))}
        present = {(handle.source, handle.target, handle.index) for handle in self.curve_handles}
        if wanted == present:
            return
        self._updating_handles = True
        for handle in self.curve_handles:
            self.scene.removeItem(handle)
        self.curve_handles.clear()
        for edge in self.selection.edges:
            for index, position in enumerate(_edge_curve_points(self.graph, edge.source, edge.target)):
                handle = CurveHandle(self, edge.source, edge.target, index, position)
                self.scene.addItem(handle)
                self.curve_handles.append(handle)
        self._updating_handles = False

    def rebuild_scene(self, selection=None):
        if selection is not None:
            self.selection = selection
        self.selection.prune(self.graph)
        self._rebuilding = True
        self.scene.clear()
        self.node_items.clear()
        self.edge_items.clear()
        self.curve_handles.clear()
        for node in self.graph:
            item = NodeItem(self, node)
            self.node_items[node] = item
            self.scene.addItem(item)
        for source, target in logical_edges(self.graph):
            item = EdgeItem(self, source, target)
            self.edge_items[self.edge_key(source, target)] = item
            self.scene.addItem(item)
        for node in self.selection.nodes:
            self.node_items[node].setSelected(True)
        for edge in self.selection.edges:
            item = self.edge_items.get(self.edge_key(edge.source, edge.target))
            if item:
                item.setSelected(True)
        self._rebuilding = False
        self._update_curve_handles()
        self.scene.update()
        self._sync_controls()
        self.update_actions()

    def edge_key(self, source, target):
        return (source, target) if self.is_directed else frozenset((source, target))

    def refresh_adjacent_edges(self, node):
        for edge in self.edge_items.values():
            if node in (edge.source, edge.target):
                edge.refresh()

    def add_node(self, position):
        node = unused_label(self.graph)
        if self.grid_mode:
            position = QPointF(*nearest_grid_point((position.x(), position.y()), self.grid_mode,
                                                   self.grid_origin.toTuple(), self.grid_unit,
                                                   self.radial_divisions))
        self.graph.add_node(node, position=(position.x(), position.y()), col=self.vertex_color)
        self.rebuild_scene()
        self.commit_change()

    def toggle_edge(self, source, target):
        flip_edge(self.graph, source, target, self.edge_color)
        self.rebuild_scene()
        self.commit_change()

    def finish_pointer_change(self):
        if self.grid_mode:
            for node in self.selection.nodes:
                item = self.node_items.get(node)
                if item:
                    snapped = nearest_grid_point(item.pos().toTuple(), self.grid_mode,
                                                 self.grid_origin.toTuple(), self.grid_unit,
                                                 self.radial_divisions)
                    item.setPos(*snapped)
        self._update_curve_handles()
        self.commit_change()

    def rename_node(self, node):
        from PySide6.QtWidgets import QInputDialog
        label, accepted = QInputDialog.getText(self, 'Rename vertex', 'Visible label:',
                                                text=vertex_label(self.graph, node))
        if accepted:
            self.node_items[node].prepareGeometryChange()
            self.graph.nodes[node]['label'] = label
            self.node_items[node].update()
            self.commit_change()

    def rename_edge(self, source, target):
        from PySide6.QtWidgets import QInputDialog
        label, accepted = QInputDialog.getText(self, 'Rename edge', 'Visible label:',
                                                text=self.graph.edges[source, target].get('label', ''))
        if accepted:
            item = self.edge_items.get(self.edge_key(source, target))
            if item:
                item.prepareGeometryChange()
            set_edge_label(self.graph, source, target, label)
            if item:
                item.update()
            self.commit_change()

    def rename_selection(self):
        if self.selection.single_node() is not None:
            self.rename_node(self.selection.single_node())
        elif len(self.selection.edges) == 1 and not self.selection.nodes:
            edge = next(iter(self.selection.edges))
            self.rename_edge(edge.source, edge.target)

    def delete_selection(self):
        handles = [item for item in self.scene.selectedItems() if isinstance(item, CurveHandle)]
        if handles:
            for handle in sorted(handles, key=lambda item: item.index, reverse=True):
                points = _edge_curve_points(self.graph, handle.source, handle.target)
                if handle.index < len(points):
                    points.pop(handle.index)
                    _set_edge_curve_points(self.graph, handle.source, handle.target, points)
        else:
            self.graph.remove_nodes_from(self.selection.nodes)
            for edge in self.selection.edges:
                self.graph.remove_edges_from(((edge.source, edge.target),))
                if not edge.directed:
                    self.graph.remove_edges_from(((edge.target, edge.source),))
            self.selection.clear()
        self.rebuild_scene()
        self.commit_change()

    def add_curve_point(self):
        first = None
        for edge in list(self.selection.edges):
            item = self.edge_items.get(self.edge_key(edge.source, edge.target))
            if item is None:
                continue
            points = _edge_curve_points(self.graph, edge.source, edge.target)
            position = item.path().pointAtPercent(.5)
            index = self._curve_insertion_index(item, points, position)
            points.insert(index, position.toTuple())
            _set_edge_curve_points(self.graph, edge.source, edge.target, points)
            first = first or (edge.source, edge.target, index)
        self.rebuild_scene()
        if len(self.selection.edges) == 1 and first is not None:
            self._select_curve_handle(*first)
        self.commit_change()

    @staticmethod
    def _curve_insertion_index(item, points, position):
        """Order controls by their position along the rendered edge, not x/y."""
        if not points:
            return 0
        _, path_position = item.closest_path_position(position)
        if len(points) == 1:
            # The single-control curve is a circular arc; its via point need
            # not occur at the middle of the arc.
            _, via_position = item.closest_path_position(QPointF(*points[0]))
            return int(path_position > via_position)
        # Multi-control curves sample each Catmull–Rom span equally. Their
        # control points are at span boundaries even when the curve doubles
        # back or crosses itself.
        steps_per_span = (item.path().elementCount() - 1) / (len(points) + 1)
        return min(len(points), int(path_position / steps_per_span))

    def add_curve_point_at(self, source, target, position, commit=True, snap_to_path=False):
        points = _edge_curve_points(self.graph, source, target)
        item = self.edge_items[self.edge_key(source, target)]
        projected, _ = item.closest_path_position(position)
        index = self._curve_insertion_index(item, points, position)
        points.insert(index, (projected if snap_to_path else position).toTuple())
        _set_edge_curve_points(self.graph, source, target, points)
        self.rebuild_scene()
        handle = self._select_curve_handle(source, target, index)
        if commit:
            self.commit_change()
        return handle

    def delete_curve_point(self, source, target, index):
        points = _edge_curve_points(self.graph, source, target)
        if not 0 <= index < len(points):
            return
        points.pop(index)
        _set_edge_curve_points(self.graph, source, target, points)
        self.rebuild_scene()
        self.commit_change()

    def _select_curve_handle(self, source, target, index):
        for handle in self.curve_handles:
            if handle.source == source and handle.target == target and handle.index == index:
                handle.setSelected(True)
                return handle
        return None

    def next_color(self):
        if self.scene.edge_sources:
            self.edge_color = (self.edge_color + 1) % self.graph.graph['num_edge_colors']
            self.report(f'New edge color: {self.edge_color}', 2)
            return
        if not (self.selection.nodes or self.selection.edges):
            pointer = self.context().pointer_position
            hovered = self.scene.itemAt(QPointF(*pointer), QTransform())
            if isinstance(hovered, NodeItem):
                data = self.graph.nodes[hovered.node]
                data['col'] = (data.get('col', 0) + 1) % self.graph.graph['num_vertex_colors']
                hovered.update()
                self.commit_change()
                return
            self.vertex_color = (self.vertex_color + 1) % self.graph.graph['num_vertex_colors']
            self.report(f'New vertex color: {self.vertex_color}', 2)
            return
        for node in self.selection.nodes:
            self.graph.nodes[node]['col'] = (self.graph.nodes[node].get('col', 0) + 1) % self.graph.graph['num_vertex_colors']
        for edge in self.selection.edges:
            source, target = edge.source, edge.target
            color = (self.graph.edges[source, target].get('col', 0) + 1) % self.graph.graph['num_edge_colors']
            self.graph.edges[source, target]['col'] = color
            if not edge.directed and self.graph.has_edge(target, source):
                self.graph.edges[target, source]['col'] = color
        self.rebuild_scene()
        self.commit_change()

    def cut_edges(self):
        cut_edges_to_rest(self.graph, self.selection.nodes)
        self.rebuild_scene()
        self.commit_change()

    def copy_selection(self):
        nodes = set(self.selection.nodes)
        for edge in self.selection.edges:
            nodes.update((edge.source, edge.target))
        self.clipboard = copy_graph_selection(self.graph, nodes or None)
        self.update_actions()

    def paste_selection(self):
        if self.clipboard is None:
            return
        origin = self.view.mapToScene(QPoint(0, 0))
        shifted = self.view.mapToScene(QPoint(18, -18))
        self.graph, nodes = paste_graph_selection(
            self.graph, self.clipboard, (shifted.x() - origin.x(), shifted.y() - origin.y()),
        )
        self.selection = SelectionState(nodes, set())
        self.rebuild_scene()
        self.commit_change()

    def deselect(self):
        self.scene.cancel_edge_creation()
        self.scene.clearSelection()
        self.selection.clear()
        self._update_curve_handles()
        self.update_actions()

    def select_all_vertices(self):
        self.scene.clearSelection()
        for item in self.node_items.values():
            item.setSelected(True)

    def set_labels(self, checked=None):
        if checked is None:
            checked = self.labels_action.isChecked()
        for item in (*self.node_items.values(), *self.edge_items.values()):
            item.prepareGeometryChange()
        self.graph.graph['show_labels'] = bool(checked)
        self.labels_action.setChecked(bool(checked))
        self.scene.update()
        self.commit_change()

    def set_directed(self, checked=None):
        if checked is None:
            checked = self.directed_action.isChecked()
        set_directed(self.graph, bool(checked))
        self.directed_action.setChecked(bool(checked))
        self.selection.clear()
        self.rebuild_scene()
        self.commit_change()

    def change_vertex_colors(self, count):
        self.graph.graph['num_vertex_colors'] = count
        self.vertex_color %= count
        for _, data in self.graph.nodes(data=True):
            data['col'] = data.get('col', 0) % count
        self.scene.update()
        self._sync_controls()
        self.commit_change()

    def change_edge_colors(self, count):
        self.graph.graph['num_edge_colors'] = count
        self.edge_color %= count
        for _, _, data in self.graph.edges(data=True):
            data['col'] = data.get('col', 0) % count
        self.rebuild_scene()
        self.commit_change()

    def set_grid(self, mode):
        self.grid_mode = mode
        for action, active in ((self.grid_off_action, mode is None),
                               (self.grid_square_action, mode == 'square'),
                               (self.grid_radial_action, mode == 'radial'),
                               (self.grid_triangular_action, mode == 'triangular')):
            action.setChecked(active)
        self._sync_controls()
        self.scene.update()
        self.update_actions()

    def change_grid_unit(self, factor):
        minimum = COORDINATE_UNIT / 64
        maximum = COORDINATE_UNIT * 16
        self.set_grid_unit(max(minimum, min(maximum, self.grid_unit * factor)))

    def set_grid_unit(self, value):
        self.grid_unit = float(value)
        self._sync_controls()
        self.scene.update()
        self.update_actions()
        self.commit_change()

    def change_radials(self, delta):
        self.set_radials(max(2, min(99, self.radial_divisions + delta)))

    def set_radials(self, value):
        self.radial_divisions = int(value)
        self._sync_controls()
        self.scene.update()
        self.update_actions()
        self.commit_change()

    def fit_graph(self):
        if self.node_items:
            bounds = self.scene.itemsBoundingRect().adjusted(-55, -55, 55, 55)
            self.view.fitInView(bounds, Qt.KeepAspectRatio)

    def run_extension(self, definition):
        context = self.context()
        if not execute_action(definition, context):
            return
        self.graph = context.graph
        self.selection = context.selection
        self.rebuild_scene()
        self.commit_change()

    def update_actions(self):
        if not hasattr(self, 'extension_actions'):
            return
        selected_count = len(self.selection.nodes) + len(self.selection.edges)
        self.rename_action.setEnabled(selected_count == 1)
        self.delete_action.setEnabled(bool(selected_count or any(handle.isSelected() for handle in self.curve_handles)))
        self.deselect_action.setEnabled(bool(selected_count))
        self.add_curve_action.setEnabled(bool(self.selection.edges))
        self.cut_action.setEnabled(any((source in self.selection.nodes) != (target in self.selection.nodes)
                                       for source, target in self.graph.edges))
        self.copy_action.setEnabled(bool(self.graph.number_of_nodes()))
        self.paste_action.setEnabled(self.clipboard is not None and bool(self.clipboard.nodes))
        self.undo_action.setEnabled(self._history_index > 0)
        self.redo_action.setEnabled(self._history_index < len(self._history) - 1)
        self.select_all_action.setEnabled(bool(self.graph.number_of_nodes()))
        self.radial_down_action.setEnabled(self.grid_mode == 'radial' and self.radial_divisions > 2)
        self.radial_up_action.setEnabled(self.grid_mode == 'radial' and self.radial_divisions < 99)
        self.grid_down_action.setEnabled(self.grid_mode is not None and self.grid_unit < COORDINATE_UNIT * 16)
        self.grid_up_action.setEnabled(self.grid_mode is not None and self.grid_unit > COORDINATE_UNIT / 64)
        vertex_colors = self.graph.graph['num_vertex_colors']
        edge_colors = self.graph.graph['num_edge_colors']
        self.vertex_colors_down_action.setEnabled(vertex_colors > 1)
        self.vertex_colors_up_action.setEnabled(vertex_colors < 12)
        self.edge_colors_down_action.setEnabled(edge_colors > 1)
        self.edge_colors_up_action.setEnabled(edge_colors < 12)
        self.vertex_colors_control.set_limits(vertex_colors > 1, vertex_colors < 12)
        self.edge_colors_control.set_limits(edge_colors > 1, edge_colors < 12)
        self.grid_unit_control.set_limits(self.grid_down_action.isEnabled(), self.grid_up_action.isEnabled())
        self.radial_control.set_limits(self.radial_down_action.isEnabled(), self.radial_up_action.isEnabled())
        context = self.context()
        for definition, qt_action in self.extension_actions:
            qt_action.setEnabled(definition.is_available(context))
            qt_action.setText(definition.display_name(context))
            self._set_action_tooltip(qt_action)
        for label_action, control_action, control, decrease, increase in self.paired_extension_controls:
            available = decrease.isEnabled() or increase.isEnabled()
            label_action.setVisible(True)
            control_action.setVisible(True)
            label_action.defaultWidget().setEnabled(available)
            control.setEnabled(available)
            control.set_limits(decrease.isEnabled(), increase.isEnabled())

    def commit_change(self):
        state = _serialize_graph(self.graph)
        if state != self._history[self._history_index]:
            self._history = self._history[:self._history_index + 1]
            self._history.append(copy.deepcopy(state))
            if len(self._history) > 200:
                self._history.pop(0)
            self._history_index = len(self._history) - 1
        self._update_title()
        self.update_actions()

    def _update_title(self):
        dirty = _serialize_graph(self.graph) != self._saved_state
        title = self.path.name if self.path else 'Untitled graph'
        self.setWindowTitle(f'{title}{" •" if dirty else ""} — Graph Builder')

    def _restore(self, index):
        self._history_index = index
        self.graph = _deserialize_graph(copy.deepcopy(self._history[index]))
        self.selection.clear()
        self.rebuild_scene()
        self._update_title()
        self.update_actions()

    def undo(self):
        if self._history_index > 0:
            self._restore(self._history_index - 1)

    def redo(self):
        if self._history_index < len(self._history) - 1:
            self._restore(self._history_index + 1)

    def _reset_history(self):
        state = copy.deepcopy(_serialize_graph(self.graph))
        self._history = [state]
        self._history_index = 0
        self._saved_state = copy.deepcopy(state)
        self._update_title()
        self.update_actions()

    def _may_replace_document(self):
        if _serialize_graph(self.graph) == self._saved_state:
            return True
        answer = QMessageBox.question(self, 'Unsaved changes', 'Save changes to this graph?',
                                      QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                                      QMessageBox.Save)
        if answer == QMessageBox.Cancel:
            return False
        if answer == QMessageBox.Save:
            return self.save_file()
        return True

    def new_file(self):
        if not self._may_replace_document():
            return
        self.graph = empty_graph()
        self.path = None
        self.selection.clear()
        self.rebuild_scene()
        self._reset_history()

    def open_file(self):
        if not self._may_replace_document():
            return
        filename, _ = QFileDialog.getOpenFileName(self, 'Open graph', str(self.path.parent if self.path else Path.cwd()),
                                                   'GraphML files (*.graphml);;All files (*)')
        if filename:
            try:
                graph = convert_from_file(filename)
            except Exception as error:
                QMessageBox.critical(self, 'Could not open graph', str(error))
                return
            self.graph = graph
            self.path = Path(filename)
            self.selection.clear()
            self.rebuild_scene()
            self._reset_history()
            self.fit_graph()

    def save_file(self):
        if self.path is None:
            return self.save_as()
        try:
            write_graph_file(self.graph, self.path)
        except Exception as error:
            QMessageBox.critical(self, 'Could not save graph', str(error))
            return False
        self._saved_state = copy.deepcopy(_serialize_graph(self.graph))
        self._update_title()
        self.report(f'Saved {self.path.name}', 3)
        return True

    def save_as(self):
        proposed = str(self.path if self.path else Path.cwd() / 'graph.graphml')
        filename, _ = QFileDialog.getSaveFileName(self, 'Save graph', proposed,
                                                   'GraphML files (*.graphml);;All files (*)')
        if not filename:
            return False
        old_path = self.path
        self.path = Path(filename)
        if not self.path.suffix:
            self.path = self.path.with_suffix('.graphml')
        if self.save_file():
            return True
        self.path = old_path
        return False

    def export_tikz(self):
        proposed = str((self.path or Path.cwd() / 'graph.graphml').with_suffix('.tex'))
        filename, _ = QFileDialog.getSaveFileName(self, 'Export to TikZ', proposed,
                                                   'TikZ files (*.tex);;All files (*)')
        if filename:
            path = Path(filename)
            if not path.suffix:
                path = path.with_suffix('.tex')
            try:
                write_tikz(self.graph, path)
            except Exception as error:
                QMessageBox.critical(self, 'Could not export TikZ', str(error))
                return
            self.report(f'Exported {path.name}', 3)

    def closeEvent(self, event):
        if self.path is not None and _serialize_graph(self.graph) != self._saved_state:
            if self.save_file():
                event.accept()
            else:
                event.ignore()
            return
        if self._may_replace_document():
            event.accept()
        else:
            event.ignore()


def launch(actions=(), graph_file=None, **options):
    app = QApplication.instance() or QApplication(sys.argv)
    path = Path(graph_file) if graph_file is not None else Path.cwd() / 'graph.graphml'
    try:
        graph = convert_from_file(path, options)
    except Exception as error:
        QMessageBox.critical(None, 'Could not open graph', str(error))
        return 1
    window = GraphBuilderQt(graph, path, actions)
    window.show()
    if graph.number_of_nodes():
        window.fit_graph()
    return app.exec()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Graph Builder Qt editor')
    parser.add_argument('--graph', type=Path, help='GraphML file to edit')
    args = parser.parse_args()
    raise SystemExit(launch(graph_file=args.graph))
