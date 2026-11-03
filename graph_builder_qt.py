"""Qt application shell for Graph Builder.

The graph model and custom actions live in ``graph_builder_lib`` and
``graph_builder.py``. Canvas rendering and pointer gestures live in
``graph_builder_qt_canvas``. This module owns menus, controls, history and files.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from bisect import bisect_right
from math import sqrt
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QProcess, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QCursor, QIcon, QKeySequence, QPainter, QPainterPath, QPalette, QPen, QPixmap, QTransform
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDockWidget, QDoubleSpinBox, QFileDialog, QFrame,
    QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox, QSpinBox, QStackedWidget,
    QTabBar,
    QTabWidget, QTextBrowser, QTextEdit, QToolBar, QToolButton, QVBoxLayout, QWidget,
)

from graph_builder_lib import (
    Action, EdgeRef, EditorContext, SelectionState, _deserialize_graph,
    _edge_curve_points, _serialize_graph, _set_edge_curve_points,
    axis_alignment_plan, builtin_editor_actions, convert_from_file, copy_graph_selection,
    cut_edges_to_rest, empty_graph, execute_action, flip_edge, labels_visible,
    logical_edges, nearest_grid_point, selected_vertices,
    paste_graph_selection, set_directed, set_edge_label, unused_label,
    vertex_label, write_graph_file,
)
from graph_builder_qt_canvas import (
    COORDINATE_UNIT, DEFAULT_GRID_PRECISION, CurveHandle, EdgeItem, GraphScene,
    GraphView, NodeItem,
)
from graph_builder_custom import public_graph
from graph_layout import (PIN_ATTRIBUTE, arrange_positions, movable_vertices,
                          pinned_vertices, relaxed_neighborhood_positions)
from graph_info import ANALYSIS_TIMEOUT_MS, analyze, topology_payload
from tikz_export import write_tikz
from standard_graphs import STANDARD_GRAPHS, generate_standard_graph, validate_standard_graph
from graph_styles import copy_style, paste_style, set_overrides, set_edge_style, set_palette_style
from graph_style_ui import PropertiesDialog, StylesDialog


class MessageSurface:
    """Small compatibility surface for custom actions that report on canvas."""
    def __init__(self, window):
        self.window = window

    def write(self, message, duration=5, screen_relative_position=(.8, .2)):
        self.window.report(message, duration)


def _transformation_icon(kind):
    """Compact, consistently weighted vector transformation icons."""
    image = QPixmap(52, 52)
    image.setDevicePixelRatio(2)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    color = QColor('#111111')
    painter.setPen(QPen(color, 1.8, Qt.SolidLine, Qt.FlatCap, Qt.RoundJoin))

    def reference_frame(x, y, width, height, extent=22):
        # Preserve the reference's proportions instead of stretching its curves.
        scale = extent / max(width, height)
        painter.translate(13 - (x + width / 2) * scale,
                          13 - (y + height / 2) * scale)
        painter.scale(scale, scale)
        painter.setPen(QPen(color, 1.8 / scale, Qt.SolidLine,
                            Qt.FlatCap, Qt.RoundJoin))

    def head(points):
        shape = QPainterPath(QPointF(*points[0]))
        for point in points[1:]:
            shape.lineTo(QPointF(*point))
        shape.closeSubpath()
        painter.fillPath(shape, color)

    if kind in ('rotate_left', 'rotate_right'):
        if kind == 'rotate_right':
            painter.translate(26, 0)
            painter.scale(-1, 1)
        reference_frame(70, 128, 176, 130)
        painter.drawArc(QRectF(70, 156, 162, 162), -8 * 16, 141 * 16)
        head(((77, 218), (86, 134), (100, 178), (150, 196)))
    elif kind == 'flip_horizontal':
        painter.drawLine(QPointF(7, 13), QPointF(19, 13))
        head(((2, 13), (9, 9), (7, 13), (9, 17)))
        head(((24, 13), (17, 9), (19, 13), (17, 17)))
    elif kind == 'flip_vertical':
        painter.drawLine(QPointF(13, 7), QPointF(13, 19))
        head(((13, 2), (9, 9), (13, 7), (17, 9)))
        head(((13, 24), (9, 17), (13, 19), (17, 17)))
    elif kind == 'half_turn':
        reference_frame(1088, 56, 250, 284, extent=24)
        ring = QRectF(1098, 89, 228, 212)
        painter.drawArc(ring, 109 * 16, 144 * 16)
        painter.drawArc(ring, -75 * 16, 147 * 16)
        head(((1233, 102), (1160, 58), (1174, 91), (1154, 134)))
        head(((1191, 294), (1270, 261), (1250, 292), (1266, 338)))
    elif kind in ('grow', 'shrink'):
        # Four identical diagonal arrows. Keep a gap at the center so the
        # inward arrowheads remain distinct even at the toolbar's small size.
        for horizontal in (-1, 1):
            for vertical in (-1, 1):
                ux, uy = horizontal / sqrt(2), vertical / sqrt(2)
                if kind == 'grow':
                    tip_radius, base_radius, start_radius = 14.3, 9.6, 2.0
                else:
                    tip_radius, base_radius, start_radius = 3.0, 7.8, 14.3
                tip = (13 + ux * tip_radius, 13 + uy * tip_radius)
                base = (13 + ux * base_radius, 13 + uy * base_radius)
                start = (13 + ux * start_radius, 13 + uy * start_radius)
                painter.drawLine(QPointF(*start), QPointF(*base))
                perpendicular = (-uy * 3.0, ux * 3.0)
                head((tip,
                      (base[0] + perpendicular[0], base[1] + perpendicular[1]),
                      (base[0] - perpendicular[0], base[1] - perpendicular[1])))
    else:
        raise ValueError(f'Unknown transformation icon: {kind}')
    painter.end()
    return QIcon(image)


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
    def __init__(self, graph=None, path=None, actions=(), return_graph_on_close=False):
        super().__init__()
        self.graph = graph if graph is not None else empty_graph()
        self.path = Path(path) if path is not None else None
        self.return_graph_on_close = return_graph_on_close
        self.custom_actions = tuple(actions)
        if any(not isinstance(action, Action) for action in self.custom_actions):
            raise TypeError('Custom actions must be graph_builder_lib.Action values')
        self.builtin_actions = builtin_editor_actions()
        self.node_items = {}
        self.edge_items = {}
        self.curve_handles = []
        self.selection = SelectionState()
        self.clipboard = None
        self.style_clipboard = None
        self.grid_mode = 'axis'
        self.axis_auto_snap = True
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
        self._info_request_id = 0
        self._info_process = None
        self._info_has_result = False
        self._info_selection_nodes = None
        self._info_outdated = False
        self._last_live_layout = 0.0
        self._live_drag_changed = False
        self._active_style_dialog = None

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
        self._basic_moves_completed = set()
        self.onboarding_hint = QLabel(
            'Click to create/select/move · Secondary-drag for edges and lasso selection · Alt-drag to pan.', self)
        self.statusBar().addWidget(self.onboarding_hint, 1)
        self.statusBar().messageChanged.connect(self._sync_status_bar_visibility)
        self.update_actions()

    def _sync_status_bar_visibility(self, message=''):
        self.statusBar().setVisible(self.onboarding_hint.isVisible() or bool(message))

    def mark_basic_move(self, move):
        self._basic_moves_completed.add(move)
        if {'create_vertex', 'create_edge', 'move_vertex'} <= self._basic_moves_completed:
            self.onboarding_hint.hide()
            self._sync_status_bar_visibility(self.statusBar().currentMessage())

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

    def _display_info(self, kind, scope, lines):
        self.info_text.setPlainText(f'{kind} · {scope}\n\n' + '\n'.join(lines))
        self.help_dock.hide()
        self.info_dock.show()
        self._info_has_result = True
        self._info_outdated = False
        self.info_copy_action.setEnabled(True)

    def _invalidate_info(self):
        self._info_request_id += 1
        if self._info_process is not None:
            process = self._info_process
            self._info_process = None
            process.kill()
            process.waitForFinished(100)
            self.info_text.setPlainText('Graph info\n\nOutdated — graph or selection changed. Run again.')
            self._info_has_result = True
            self._info_outdated = True
            self.info_copy_action.setEnabled(True)
        if self._info_has_result and not self._info_outdated:
            self.info_text.append('\nOutdated — graph or selection changed. Run again.')
            self._info_outdated = True

    def copy_graph_info(self):
        if self._info_has_result:
            QApplication.clipboard().setText(self.info_text.toPlainText())

    def show_graph_info(self, kind):
        scope_nodes = selected_vertices(self.selection) if self.info_scope.currentIndex() else None
        if scope_nodes is not None and not scope_nodes:
            return
        graph = public_graph(self.graph)
        if scope_nodes is not None:
            graph = graph.subgraph(scope_nodes).copy()
        scope = f'{len(scope_nodes)} selected vertices' if scope_nodes is not None else 'whole graph'
        self._info_selection_nodes = set(scope_nodes) if scope_nodes is not None else None
        self._info_request_id += 1
        request_id = self._info_request_id
        if self._info_process is not None:
            self._info_process.kill()
            self._info_process.waitForFinished(100)
            self._info_process = None
        self._info_has_result = False
        self.info_copy_action.setEnabled(False)
        if kind == 'Overview':
            self._display_info(kind, scope, analyze(graph, kind))
            return
        self.info_text.setPlainText(f'{kind} · {scope}\n\nCalculating…')
        self.help_dock.hide()
        self.info_dock.show()
        process = QProcess(self)
        process.setWorkingDirectory(str(Path(__file__).resolve().parent))
        self._info_process = process
        payload = json.dumps(topology_payload(graph)).encode('utf-8')
        process.started.connect(lambda: (process.write(payload), process.closeWriteChannel()))
        process.finished.connect(lambda exit_code, exit_status: self._finish_graph_info(
            request_id, process, kind, scope, exit_code))
        process.errorOccurred.connect(lambda error: self._graph_info_process_error(
            request_id, process, kind, scope, error))
        process.start(sys.executable, ['-m', 'graph_info', '--worker', kind])
        QTimer.singleShot(ANALYSIS_TIMEOUT_MS,
                          lambda: self._timeout_graph_info(request_id, process, kind, scope))

    def _finish_graph_info(self, request_id, process, kind, scope, exit_code):
        if request_id == self._info_request_id and self._info_process is process:
            self._info_process = None
            if exit_code == 0:
                try:
                    lines = json.loads(bytes(process.readAllStandardOutput()).decode('utf-8'))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    lines = ['Analysis returned an unreadable result.']
            else:
                detail = bytes(process.readAllStandardError()).decode('utf-8', errors='replace').strip()
                lines = [f'Analysis failed: {detail or "worker stopped unexpectedly"}']
            self._display_info(kind, scope, lines)
        process.deleteLater()

    def _graph_info_process_error(self, request_id, process, kind, scope, error):
        if (request_id == self._info_request_id and self._info_process is process
                and error == QProcess.FailedToStart):
            self._info_process = None
            self._display_info(kind, scope, ['Could not start the analysis process.'])
            process.deleteLater()

    def _timeout_graph_info(self, request_id, process, kind, scope):
        if request_id != self._info_request_id or self._info_process is not process:
            return
        self._info_request_id += 1
        self._info_process = None
        process.kill()
        process.waitForFinished(100)
        self._display_info(kind, scope,
                           [f'Not computed within {ANALYSIS_TIMEOUT_MS / 1000:g} seconds.'])

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
        description = action.property('description')
        detail = f'\n{description}' if description else ''
        action.setToolTip(f'{action.text().replace("&", "")}{suffix}{detail}')

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
        self.properties_action = self._action('Properties…', self.edit_selection_properties)
        self.styles_action = self._action('Type styles…', self.edit_shared_styles)
        self.copy_style_action = self._action('Copy style', self.copy_selected_style, 'Ctrl+Shift+C')
        self.paste_style_action = self._action('Paste style', self.paste_selected_style, 'Ctrl+Shift+V')
        self.addAction(self.copy_style_action)
        self.addAction(self.paste_style_action)
        self.deselect_action = self._action('Deselect', self.deselect, 'Escape')

        self.add_curve_action = self._action('Curve point', self.add_curve_point)
        self.previous_type_action = self._action('Previous type', lambda: self.change_type(-1), 'Shift+T')
        self.next_type_action = self._action('Next type', lambda: self.change_type(1), 'T')
        self.cut_action = self._action('Cut', self.cut_edges, 'C')
        self.fit_action = self._action('Fit graph', self.fit_graph, 'Space')

        self.arrange_action = self._action('Arrange', self.arrange_graph)
        self.pin_action = self._action('Pin selection', self.pin_selection)
        self.unpin_action = self._action('Unpin selection', self.unpin_selection)
        self.clear_pins_action = self._action('Clear pins', self.clear_layout_pins)
        self.live_layout_action = self._action('Relax while dragging',
                                               self.set_live_layout, checkable=True)

        self.labels_action = self._action('Labels', self.set_labels, 'L', checkable=True)
        self.labels_action.setChecked(labels_visible(self.graph))
        self.directed_action = self._action('Directed', self.set_directed, checkable=True)
        self.directed_action.setChecked(self.is_directed)
        self.grid_off_action = self._action('No guides', lambda: self.set_grid(None), checkable=True)
        self.grid_square_action = self._action('Square grid', lambda: self.set_grid(None if self.grid_mode == 'square' else 'square'), checkable=True)
        self.grid_triangular_action = self._action('Triangular grid', lambda: self.set_grid(None if self.grid_mode == 'triangular' else 'triangular'), checkable=True)
        self.grid_radial_action = self._action('Radial grid', lambda: self.set_grid(None if self.grid_mode == 'radial' else 'radial'), checkable=True)
        self.grid_axis_action = self._action('Axes', lambda: self.set_grid(None if self.grid_mode == 'axis' else 'axis'), checkable=True)
        self.axis_snap_action = self._action('Auto-snap', self.set_axis_auto_snap,
                                             checkable=True)
        self.grid_group = QActionGroup(self)
        self.grid_group.setExclusive(True)
        for action in (self.grid_off_action, self.grid_square_action,
                       self.grid_radial_action, self.grid_triangular_action,
                       self.grid_axis_action):
            self.grid_group.addAction(action)
        self.grid_axis_action.setChecked(True)
        self.axis_snap_action.setChecked(self.axis_auto_snap)
        self.grid_down_action = self._action('Decrease grid density (larger cells)',
                                           lambda: self.change_grid_unit(2))
        self.grid_up_action = self._action('Increase grid density (smaller cells)',
                                         lambda: self.change_grid_unit(1/2))
        self.radial_down_action = self._action('Fewer radials', lambda: self.change_radials(-1))
        self.radial_up_action = self._action('More radials', lambda: self.change_radials(1))
        self.vertex_colors_down_action = self._action('Fewer vertex types', lambda: self.change_vertex_colors(self.graph.graph['num_vertex_colors'] - 1))
        self.vertex_colors_up_action = self._action('More vertex types', lambda: self.change_vertex_colors(self.graph.graph['num_vertex_colors'] + 1))
        self.edge_colors_down_action = self._action('Fewer edge types', lambda: self.change_edge_colors(self.graph.graph['num_edge_colors'] - 1))
        self.edge_colors_up_action = self._action('More edge types', lambda: self.change_edge_colors(self.graph.graph['num_edge_colors'] + 1))
        self.info_actions = {
            kind: self._action(kind, lambda checked=False, view=kind: self.show_graph_info(view))
            for kind in ('Overview', 'Structure', 'Distances', 'Bounds')
        }
        self.info_copy_action = self._action('Copy results', self.copy_graph_info)

        for action, description in (
            (self.fit_action, 'Center the whole graph in view.'),
            (self.rename_action, 'Change the label of a vertex or edge.'),
            (self.previous_type_action, 'Previous vertex/edge type.'),
            (self.next_type_action, 'Next vertex/edge type.'),
            (self.add_curve_action, 'Add a control point along the edge. Drag to reshape.'),
            (self.cut_action, 'Disconnect the selection from the rest of the graph.'),
            (self.axis_snap_action, 'Align vertices while dragging.'),
            (self.grid_down_action, 'Double the spacing between grid lines or circles.'),
            (self.grid_up_action, 'Halve the spacing between grid lines or circles.'),
            (self.labels_action, 'Show or hide vertex and edge labels.'),
            (self.directed_action, 'Show edges as directed arrows.'),
            (self.arrange_action, 'Automatically arrange vertices.'),
            (self.pin_action, 'Keep selected vertices in place when arranging.'),
            (self.unpin_action, 'Allow selected vertices to move when arranging.'),
            (self.styles_action, 'Edit the shared appearance of each vertex or edge type.'),
        ):
            action.setProperty('description', description)
            self._set_action_tooltip(action)

        self.extension_actions = []
        for definition in (*self.builtin_actions, *self.custom_actions):
            qt_action = self._action(definition.display_name(self.context()),
                                     lambda checked=False, action=definition: self.run_extension(action),
                                     definition.shortcut)
            qt_action.setProperty('description', definition.description or '')
            self._set_action_tooltip(qt_action)
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
        self.help_button = QToolButton(tabs.tabBar())
        self.help_button.setText('?')
        self.help_button.setToolTip('Show the controls guide')
        self.help_button.setAccessibleName('Controls guide')
        self.help_button.setFixedSize(25, 25)
        self.help_button.setStyleSheet('''
            QToolButton { color: #111111; background: #e6e7e9;
                          border: 1px solid #c4c9ce; border-radius: 12px;
                          font-weight: bold; font-size: 14px; }
            QToolButton:hover { background: #d4e7e8; }
        ''')

        def row(name, actions=()):
            toolbar = QToolBar(name, tabs)
            toolbar.setMovable(False)
            toolbar.setFloatable(False)
            toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)
            toolbar.setStyleSheet('''
                QToolBar { border: 0; padding: 2px 2px 2px 8px; background: #f5f6f7; }
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
                QToolBar::separator { background: #c4c9ce; width: 1px;
                                      margin: 5px 7px; }
            ''')
            toolbar.addActions(actions)
            tabs.addTab(toolbar, name)
            return toolbar

        file_row = row('File', (self.new_action, self.open_action, self.save_action,
                                self.save_as_action, self.export_action))

        basic_row = row('Basic', (self.undo_action, self.redo_action,
                                  self.copy_action, self.paste_action,
                                  self.select_all_action, self.delete_action,
                                  self.fit_action, self.rename_action))
        self.paired_extension_controls = []
        self.transformation_controls = []
        for definition, action in self.extension_actions:
            if definition.group == 'basic' and not definition.pair_id:
                basic_row.addAction(action)
        pairs = {}
        for definition, action in self.extension_actions:
            if definition.group == 'basic' and definition.pair_id:
                pairs.setdefault(definition.pair_id, []).append((definition, action))
        for pair_id, pair in pairs.items():
            if pair_id == 'transformation':
                if len(pair) != 7:
                    raise ValueError('Transformation needs seven actions')
                label_action = basic_row.addWidget(QLabel('  Transformation:', basic_row))
                control = QWidget(basic_row)
                buttons = QHBoxLayout(control)
                buttons.setContentsMargins(0, 0, 0, 0)
                buttons.setSpacing(2)
                for (_, action), kind in zip(pair, ('rotate_left', 'rotate_right',
                                                     'flip_horizontal', 'flip_vertical',
                                                     'half_turn', 'grow', 'shrink')):
                    button = QToolButton(control)
                    button.setToolTip(action.toolTip())
                    button.setEnabled(action.isEnabled())
                    button.clicked.connect(action.trigger)
                    action.changed.connect(lambda button=button, action=action:
                                           button.setEnabled(action.isEnabled()))
                    button.setFixedSize(30, 30)
                    button.setStyleSheet('''
                        QToolButton { border: 1px solid #9ba2a9; border-radius: 4px;
                                      color: #111111; background: #f5f6f7; padding: 0; }
                        QToolButton:hover:enabled { background: #e6ecee; }
                        QToolButton:disabled { color: #777d84; background: #f1f2f3;
                                               border-color: #d0d4d9; }
                    ''')
                    button.setIcon(_transformation_icon(kind))
                    button.setIconSize(QSize(24, 24))
                    button.setToolButtonStyle(Qt.ToolButtonIconOnly)
                    buttons.addWidget(button)
                control_action = basic_row.addWidget(control)
                self.transformation_controls.append((label_action, control_action,
                                                     control, tuple(action for _, action in pair)))
                continue
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

        edition_row = row('Edition', ())
        edition_row.addWidget(QLabel('  Type:', edition_row))
        self.type_control = StepControl(self.previous_type_action, self.next_type_action,
                                        edition_row)
        edition_row.addWidget(self.type_control)
        edition_row.addActions((self.add_curve_action, self.cut_action))
        edition_row.addActions(tuple(action for definition, action in self.extension_actions
                                     if definition.group == 'edition' and not definition.pair_id))

        grid_row = row('Guides', (self.grid_off_action, self.grid_axis_action,
                                self.grid_square_action, self.grid_radial_action,
                                self.grid_triangular_action))
        self.grid_options_separator = grid_row.addSeparator()
        grid_row.addAction(self.axis_snap_action)
        self.grid_unit_label = QLabel(grid_row)
        self.grid_unit_label_action = grid_row.addWidget(self.grid_unit_label)
        self.grid_unit_control = StepControl(self.grid_down_action, self.grid_up_action, grid_row)
        self.grid_unit_control_action = grid_row.addWidget(self.grid_unit_control)
        self.radial_label = QLabel(grid_row)
        self.radial_label_action = grid_row.addWidget(self.radial_label)
        self.radial_control = StepControl(self.radial_down_action, self.radial_up_action, grid_row)
        self.radial_control_action = grid_row.addWidget(self.radial_control)

        properties_row = row('Graph properties', (self.labels_action, self.directed_action))
        style_menu = QMenu(properties_row)
        style_menu.addActions((self.properties_action, self.styles_action,
                               self.copy_style_action, self.paste_style_action))
        style_button = QToolButton(properties_row)
        style_button.setText('Styles')
        style_button.setMinimumWidth(92)
        style_button.setFixedHeight(30)
        style_button.setStyleSheet('QToolButton { color: #111111; background: #f5f6f7; '
                                   'border: 1px solid #b8bec4; border-radius: 4px; '
                                   'padding: 3px 22px 3px 9px; } '
                                   'QToolButton::menu-indicator { subcontrol-origin: padding; '
                                   'subcontrol-position: right center; right: 7px; }')
        style_button.setMenu(style_menu)
        style_button.setPopupMode(QToolButton.InstantPopup)
        properties_row.addWidget(style_button)
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

        row('Layout', (self.arrange_action, self.pin_action, self.unpin_action,
                       self.clear_pins_action, self.live_layout_action))

        info_row = row('Info', tuple(self.info_actions.values()))
        self.info_scope = QComboBox(info_row)
        self.info_scope.addItems(('Whole graph', 'Selected vertices'))
        self.info_scope.setStyleSheet('QComboBox { color: #111111; background: #f5f6f7; '
                                     'border: 1px solid #b8bec4; border-radius: 4px; padding: 3px 8px; } '
                                     'QComboBox QAbstractItemView { color: #111111; background: white; }')
        self.info_scope.currentIndexChanged.connect(self.update_actions)
        info_row.addWidget(self.info_scope)
        info_row.addAction(self.info_copy_action)

        standard_row = row('Standard graphs')
        self.standard_graph_choice = QComboBox(standard_row)
        self.standard_graph_choice.setMinimumWidth(190)
        self.standard_graph_choice.setStyleSheet('''
            QComboBox { color: #111111; background: #f5f6f7;
                        border: 1px solid #b8bec4; border-radius: 4px;
                        padding: 3px 8px; }
            QComboBox QAbstractItemView { color: #111111; background: #ffffff;
                                         selection-color: #111111;
                                         selection-background-color: #d4e7e8; }
        ''')
        choice_palette = self.standard_graph_choice.palette()
        for role in (QPalette.Text, QPalette.ButtonText, QPalette.WindowText):
            choice_palette.setColor(role, QColor('#111111'))
        choice_palette.setColor(QPalette.Button, QColor('#f5f6f7'))
        choice_palette.setColor(QPalette.Base, QColor('#ffffff'))
        self.standard_graph_choice.setPalette(choice_palette)
        self.standard_parameter_stack = QStackedWidget(standard_row)
        self.standard_parameter_inputs = {}
        for definition in STANDARD_GRAPHS:
            self.standard_graph_choice.addItem(definition.title, definition.key)
            page = QWidget(self.standard_parameter_stack)
            fields = QHBoxLayout(page)
            fields.setContentsMargins(0, 0, 0, 0)
            fields.setSpacing(5)
            inputs = {}
            for parameter in definition.parameters:
                fields.addWidget(QLabel(parameter.label + ':', page))
                if parameter.kind == 'probability':
                    control = QDoubleSpinBox(page)
                    control.setDecimals(3)
                    control.setSingleStep(.05)
                else:
                    control = QSpinBox(page)
                    if parameter.kind == 'optional_seed':
                        control.setSpecialValueText('Random')
                control.setRange(parameter.minimum, parameter.maximum)
                control.setValue(parameter.default)
                control.setFixedWidth(82 if parameter.kind == 'optional_seed' else 66)
                control.valueChanged.connect(self._update_standard_graph_form)
                fields.addWidget(control)
                inputs[parameter.key] = control
            self.standard_parameter_inputs[definition.key] = inputs
            self.standard_parameter_stack.addWidget(page)
        standard_row.addWidget(self.standard_graph_choice)
        standard_row.addWidget(self.standard_parameter_stack)
        self.standard_add_action = self._action('Add graph', lambda: self.add_standard_graph())
        standard_row.addAction(self.standard_add_action)
        self.standard_info_label = QLabel(standard_row)
        self.standard_info_label.setStyleSheet('color: #555c63; padding-left: 8px;')
        standard_row.addWidget(self.standard_info_label)
        self.standard_graph_choice.currentIndexChanged.connect(self._change_standard_graph)
        self._change_standard_graph()

        custom = [action for definition, action in self.extension_actions
                  if definition.group not in ('basic', 'edition')]
        custom_row = row('Custom', custom)
        if not custom:
            custom_row.addWidget(QLabel('Add functions to your launch script with the @button decorator.', custom_row))
        tabs.tabBar().setTabButton(tabs.count() - 1, QTabBar.RightSide, self.help_button)
        tabs.open_tab(0)
        layout.addWidget(tabs)
        layout.addWidget(self.view, 1)
        self.setCentralWidget(container)
        self.info_dock = QDockWidget('Graph info', self)
        self.info_dock.setAllowedAreas(Qt.RightDockWidgetArea)
        self.info_dock.setMinimumWidth(315)
        self.info_text = QTextEdit(self.info_dock)
        self.info_text.setReadOnly(True)
        self.info_text.setStyleSheet('QTextEdit { color: #111111; background: #ffffff; padding: 8px; }')
        self.info_dock.setWidget(self.info_text)
        self.addDockWidget(Qt.RightDockWidgetArea, self.info_dock)
        self.info_dock.hide()
        self.help_dock = QDockWidget('Controls', self)
        self.help_dock.setAllowedAreas(Qt.RightDockWidgetArea)
        self.help_dock.setMinimumWidth(290)
        self.help_text = QTextBrowser(self.help_dock)
        self.help_text.setStyleSheet('QTextBrowser { color: #111111; background: #ffffff; padding: 8px; }')
        self.help_text.setOpenExternalLinks(True)
        self.help_text.setHtml('''
            <h3>Quick controls</h3>
            <p><b>Create:</b> Click empty space for a vertex. Secondary-drag
            between vertices to add or remove an edge. Secondary-click a vertex to delete it or press Delete.</p>
            <p><b>Select:</b> Click an object, drag a rectangle in empty space,
            or secondary-drag there for a lasso.</p>
            <p><b>Move and navigate:</b> Drag one or multiple vertices to move them.
            Press Space to fit the graph in view. Alt+drag to pan. Mouse wheel to zoom.</p>
            <p><b>Edit:</b> Double-click a vertex or edge to edit its label and style. Global styles can be edited in the Graph properties menu. Use T to change vertex style.
            Use the Basic or Edition menu for graph operations.</p>
            <p><small>Secondary-click means right-click, or Ctrl-click on a
            trackpad.</small></p>
            <h3>Essential menus</h3>
            <p><b>File</b> saves, loads and exports.<br>
            <b>Basic</b> has undo, selection and transformations.<br>
            <b>Edition</b> has graph operations.<br>
            <b>Guides</b> has various guides and grids for consistent layout positioning.<br>
            <b>Graph properties</b> has labels and styles.<br>
            <b>Standard graphs</b> inserts familiar graph families.<br>
            <b>Layout</b> arranges vertices.<br>
            <b>Info</b> Computes metrics of the graph.<br>
            <b>Custom</b> Buttons added by your script.</p>
            <h3>About</h3>
            <p>Created by Cyril Pujol.<br>
            <a href="https://github.com/CyrilPujol/graph-builder">GitHub</a> ·
            <a href="https://www.irif.fr/~cpujol/">Webpage</a></p>
        ''')
        self.help_dock.setWidget(self.help_text)
        self.addDockWidget(Qt.RightDockWidgetArea, self.help_dock)
        self.help_dock.hide()
        self.help_button.clicked.connect(self.toggle_help)
        # Actions in inactive tabs still need their keyboard shortcuts active.
        for action in (self.new_action, self.open_action, self.save_action, self.save_as_action,
                       self.close_action, self.undo_action, self.redo_action, self.copy_action,
                       self.paste_action, self.delete_action, self.rename_action,
                       self.deselect_action, self.select_all_action,
                       self.add_curve_action, self.previous_type_action,
                       self.next_type_action, self.cut_action, self.fit_action,
                       self.labels_action,
                       *(item for _, item in self.extension_actions)):
            if not action.shortcut().isEmpty():
                self.addAction(action)
        self._sync_controls()

    def toggle_help(self):
        if self.help_dock.isVisible():
            self.help_dock.hide()
        else:
            self.info_dock.hide()
            self.help_dock.show()

    def _sync_controls(self):
        self.labels_action.setChecked(labels_visible(self.graph))
        self.directed_action.setChecked(self.is_directed)
        self.vertex_colors_label.setText(f'  Vertex types: {self.graph.graph.get("num_vertex_colors", 4)} ')
        self.edge_colors_label.setText(f'  Edge types: {self.graph.graph.get("num_edge_colors", 2)} ')
        self.grid_unit_label.setText('  Grid density: ')
        self.radial_label.setText(f'  Radials: {self.radial_divisions} ')
        self.grid_unit_label_action.setVisible(self.grid_mode in ('square', 'triangular', 'radial'))
        self.radial_label_action.setVisible(self.grid_mode == 'radial')
        self.grid_unit_control_action.setVisible(self.grid_mode in ('square', 'triangular', 'radial'))
        self.radial_control_action.setVisible(self.grid_mode == 'radial')
        self.axis_snap_action.setVisible(self.grid_mode == 'axis')
        self.grid_options_separator.setVisible(self.grid_mode is not None)

    def _change_standard_graph(self):
        self.standard_parameter_stack.setCurrentIndex(self.standard_graph_choice.currentIndex())
        page = self.standard_parameter_stack.currentWidget()
        self.standard_parameter_stack.setFixedWidth(page.sizeHint().width())
        self._update_standard_graph_form()

    def _standard_parameters(self):
        key = self.standard_graph_choice.currentData()
        return {name: control.value()
                for name, control in self.standard_parameter_inputs[key].items()}

    def _update_standard_graph_form(self):
        if not hasattr(self, 'standard_info_label'):
            return
        try:
            _, vertices, edges = validate_standard_graph(
                self.standard_graph_choice.currentData(), self._standard_parameters())
        except ValueError as error:
            message = str(error)
            self.standard_info_label.setStyleSheet('color: #a12b2b; padding-left: 8px;')
            self.standard_info_label.setText(message)
            self.standard_info_label.setToolTip(message)
            self.standard_add_action.setEnabled(False)
        else:
            edges_text = f'≈{edges:.0f}' if isinstance(edges, float) else str(edges)
            self.standard_info_label.setStyleSheet('color: #555c63; padding-left: 8px;')
            self.standard_info_label.setText(f'{vertices} vertices · {edges_text} edges')
            self.standard_info_label.setToolTip('Expected size (random edge count is approximate)')
            self.standard_add_action.setEnabled(True)

    def add_standard_graph(self, key=None, parameters=None):
        """Insert a named graph at the visible viewport center in one undo step."""
        key = self.standard_graph_choice.currentData() if key is None else key
        parameters = self._standard_parameters() if parameters is None else parameters
        try:
            generated = generate_standard_graph(key, parameters)
        except ValueError as error:
            self.report(str(error))
            return set()
        positions = generated.positions
        xs = [point[0] for point in positions.values()]
        ys = [point[1] for point in positions.values()]
        midpoint = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
        width, height = max(xs) - min(xs), max(ys) - min(ys)
        viewport = self.view.viewport()
        pixels_per_unit = min(85.0, .75 * viewport.width() / max(width, 1),
                              .75 * viewport.height() / max(height, 1))
        scene_per_unit = pixels_per_unit / self.view.transform().m11()
        center = self.view.mapToScene(viewport.rect().center())
        index = 0
        new_ids = {}
        for original in generated.graph:
            while str(index) in self.graph:
                index += 1
            new_id = str(index)
            new_ids[original] = new_id
            index += 1
            x, y = positions[original]
            position = (center.x() + (x - midpoint[0]) * scene_per_unit,
                        center.y() + (y - midpoint[1]) * scene_per_unit)
            self.graph.add_node(new_id, position=position, col=self.vertex_color,
                                label=generated.labels[original])
        for source, target in generated.graph.edges:
            first, second = new_ids[source], new_ids[target]
            self.graph.add_edge(first, second, col=self.edge_color, label='')
            self.graph.add_edge(second, first, col=self.edge_color, label='')
        self.selection = SelectionState(set(new_ids.values()), set())
        self.rebuild_scene()
        self.commit_change()
        self.statusBar().showMessage(
            f'Added {len(new_ids)} vertices and {generated.graph.number_of_edges()} edges', 4000)
        return set(new_ids.values())

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
        if self._info_selection_nodes is not None and selected_vertices(self.selection) != self._info_selection_nodes:
            self._invalidate_info()
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
        self.scene.set_edge_hover_target(None)
        self.scene.clear_fusion_animation()
        self.scene.set_axis_snap_guides(())
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

    def _set_layout_positions(self, positions, rebuild=False):
        for node, position in positions.items():
            item = self.node_items.get(node)
            if item is not None:
                item.setPos(*position)
        if rebuild:
            self.rebuild_scene()
        else:
            self.scene.update()

    def arrange_graph(self):
        movable = movable_vertices(self.graph, self.selection.nodes)
        if not movable:
            self.report('No movable vertices. Unpin a vertex or change the selection.')
            return False
        if self.graph.number_of_nodes() > 350:
            self.report('Arrange is limited to 350 vertices to keep the editor responsive.')
            return False
        visible = self.view.mapToScene(self.view.viewport().rect()).boundingRect()
        positions = arrange_positions(
            self.graph, movable,
            center=(visible.center().x(), visible.center().y()),
            fit_size=(visible.width() * .75, visible.height() * .75))
        self._set_layout_positions(positions, rebuild=True)
        self.commit_change()
        return True

    def pin_selection(self):
        for node in self.selection.nodes:
            self.graph.nodes[node][PIN_ATTRIBUTE] = True
            self.node_items[node].update()
        self.commit_change()

    def unpin_selection(self):
        for node in self.selection.nodes:
            self.graph.nodes[node].pop(PIN_ATTRIBUTE, None)
            self.node_items[node].update()
        self.commit_change()

    def clear_layout_pins(self):
        for node in pinned_vertices(self.graph):
            self.graph.nodes[node].pop(PIN_ATTRIBUTE, None)
            self.node_items[node].update()
        self.commit_change()

    def set_live_layout(self, checked):
        self.live_layout_action.setChecked(bool(checked))
        if checked:
            self.report('Live layout is on. Nearby vertices relax while you hold or drag a vertex.')

    def relax_dragged_neighbors(self, dragged):
        if not self.live_layout_action.isChecked() or self.graph.number_of_nodes() > 200:
            return
        now = time.monotonic()
        if now - self._last_live_layout < .05:
            return
        self._last_live_layout = now
        positions = relaxed_neighborhood_positions(self.graph, dragged)
        if positions:
            self._set_layout_positions(positions)
            self._live_drag_changed = True

    def add_node(self, position):
        node = unused_label(self.graph)
        if self.grid_mode in ('square', 'triangular', 'radial'):
            position = QPointF(*nearest_grid_point((position.x(), position.y()), self.grid_mode,
                                                   self.grid_origin.toTuple(), self.grid_unit,
                                                   self.radial_divisions))
        self.graph.add_node(node, position=(position.x(), position.y()), col=self.vertex_color)
        self.rebuild_scene()
        self.commit_change()
        self.mark_basic_move('create_vertex')

    def toggle_edge(self, source, target):
        flip_edge(self.graph, source, target, self.edge_color)
        self.rebuild_scene()
        self.commit_change()

    def finish_pointer_change(self):
        if self.grid_mode == 'axis' and self.axis_auto_snap:
            moving = {node: self.node_items[node] for node in self.selection.nodes
                      if node in self.node_items}
            offsets, _ = self.axis_snap_plan(moving)
            if offsets != (0.0, 0.0):
                for item in moving.values():
                    item.setPos(item.pos() + QPointF(*offsets))
        elif self.grid_mode in ('square', 'triangular', 'radial'):
            for node in self.selection.nodes:
                item = self.node_items.get(node)
                if item:
                    snapped = nearest_grid_point(item.pos().toTuple(), self.grid_mode,
                                                 self.grid_origin.toTuple(), self.grid_unit,
                                                 self.radial_divisions)
                    item.setPos(*snapped)
        self.scene.set_axis_snap_guides(())
        self._update_curve_handles()
        self.commit_change()

    def axis_snap_plan(self, moving_nodes, include_endpoints=False):
        if self.grid_mode != 'axis' or not self.axis_auto_snap or not moving_nodes:
            result = ((0.0, 0.0), ())
            return (*result, ()) if include_endpoints else result
        moving = [(node, self.node_items[node]) for node in moving_nodes
                  if node in self.node_items]
        viewport = self.view.viewport().rect()
        moving_ids = {node for node, _ in moving}
        references = [(node, item) for node, item in self.node_items.items()
                      if node not in moving_ids and
                      viewport.contains(self.view.mapFromScene(item.pos()))]
        visible = self.view.mapToScene(viewport).boundingRect()
        vertical_visible = visible.left() <= 0 <= visible.right()
        horizontal_visible = visible.top() <= 0 <= visible.bottom()
        plan = axis_alignment_plan(
            [item.pos().toTuple() for _, item in moving],
            [item.pos().toTuple() for _, item in references],
            self.view.transform().m11(),
            axis_visible=(vertical_visible, horizontal_visible),
            origin_visible=vertical_visible and horizontal_visible,
            include_matches=include_endpoints)
        if not include_endpoints:
            return plan
        offsets, guides, matches = plan
        endpoints = []
        for guide, (moved_index, reference_index) in zip(guides, matches):
            nodes = {moving[moved_index][0]}
            if reference_index is not None and reference_index < len(references):
                nodes.add(references[reference_index][0])
            else:
                nodes.update(node for node, item in references
                             if item.pos().toTuple() == guide[0])
            endpoints.append(frozenset(nodes))
        return offsets, guides, tuple(endpoints)

    def preview_axis_snap(self, moving_nodes):
        _, guides, endpoints = self.axis_snap_plan(moving_nodes, include_endpoints=True)
        self.scene.set_axis_snap_guides(guides, endpoints)

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

    def edit_node_properties(self, node):
        nodes = ([n for n in self.graph if n in self.selection.nodes]
                 if node in self.selection.nodes and len(self.selection.nodes) > 1 else [node])
        source_graph = self.graph
        editor = PropertiesDialog(self.graph, 'vertex',
                                  [dict(self.graph.nodes[n], label=vertex_label(self.graph, n))
                                   for n in nodes],
                                  bulk=len(nodes) > 1, parent=self)
        editor.accepted.connect(lambda: self._apply_node_properties(editor, nodes, source_graph))
        self._show_style_editor(editor)
        return editor

    def _apply_node_properties(self, dialog, nodes, source_graph):
        if self.graph is not source_graph or any(node not in self.graph for node in nodes):
            self.report('Graph changed. Reopen vertex properties.', 4)
            return
        node = nodes[0]
        changes = dialog.changes()
        if dialog.shared_style_update is not None:
            index, style = dialog.shared_style_update
            set_palette_style(self.graph, 'vertex', index, style)
        for current, color in zip(nodes, dialog.type_values()):
            attributes = self.graph.nodes[current]
            attributes['col'] = color
            set_overrides(attributes, changes)
            if dialog.clear_preset():
                attributes.pop('style_preset', None)
        if dialog.label_edit is not None and dialog.label_edit.text() != vertex_label(self.graph, node):
            self.graph.nodes[node]['label'] = dialog.label_edit.text()
        self.rebuild_scene()
        self.commit_change()

    def edit_edge_properties(self, source, target):
        selected = self.edge_key(source, target)
        edges = ([(edge.source, edge.target) for edge in self.selection.edges]
                 if any(self.edge_key(edge.source, edge.target) == selected
                        for edge in self.selection.edges) and len(self.selection.edges) > 1
                 else [(source, target)])
        source_graph = self.graph
        editor = PropertiesDialog(self.graph, 'edge',
                                  [self.graph.edges[pair] for pair in edges],
                                  bulk=len(edges) > 1, parent=self)
        editor.accepted.connect(lambda: self._apply_edge_properties(editor, edges, source_graph))
        self._show_style_editor(editor)
        return editor

    def _apply_edge_properties(self, dialog, edges, source_graph):
        if self.graph is not source_graph or any(not self.graph.has_edge(*pair) for pair in edges):
            self.report('Graph changed. Reopen edge properties.', 4)
            return
        source, target = edges[0]
        if dialog.shared_style_update is not None:
            index, style = dialog.shared_style_update
            set_palette_style(self.graph, 'edge', index, style)
        for (first, second), color in zip(edges, dialog.type_values()):
            self.graph.edges[first, second]['col'] = color
            if not self.graph.is_directed() and self.graph.has_edge(second, first):
                self.graph.edges[second, first]['col'] = color
            set_edge_style(self.graph, first, second, dialog.changes(),
                           '' if dialog.clear_preset() else None)
        if dialog.label_edit is not None:
            set_edge_label(self.graph, source, target, dialog.label_edit.text())
        self.rebuild_scene()
        self.commit_change()

    def edit_selection_properties(self):
        if self.selection.nodes:
            self.edit_node_properties(next(iter(self.selection.nodes)))
        elif self.selection.edges:
            edge = next(iter(self.selection.edges))
            self.edit_edge_properties(edge.source, edge.target)

    def edit_shared_styles(self):
        source_graph = self.graph
        editor = StylesDialog(self.graph, self)
        editor.accepted.connect(lambda: self._apply_type_styles(editor, source_graph))
        self._show_style_editor(editor)
        return editor

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
        if self.graph is not source_graph:
            self.report('Graph changed. Reopen Type styles.', 4)
            return
        for key in ('vertex_styles', 'edge_styles'):
            if key in dialog.graph.graph:
                self.graph.graph[key] = copy.deepcopy(dialog.graph.graph[key])
            else:
                self.graph.graph.pop(key, None)
        self.rebuild_scene()
        self.commit_change()

    def copy_selected_style(self):
        if len(self.selection.nodes) == 1 and not self.selection.edges:
            node = next(iter(self.selection.nodes))
            self.style_clipboard = ('vertex', copy_style(self.graph, 'vertex', self.graph.nodes[node]))
        elif len(self.selection.edges) == 1 and not self.selection.nodes:
            edge = next(iter(self.selection.edges))
            self.style_clipboard = ('edge', copy_style(self.graph, 'edge',
                                                      self.graph.edges[edge.source, edge.target]))
        self.update_actions()

    def paste_selected_style(self):
        if not self.style_clipboard:
            return
        kind, snapshot = self.style_clipboard
        if kind == 'vertex':
            for node in self.selection.nodes:
                paste_style(self.graph.nodes[node], snapshot)
        else:
            for edge in self.selection.edges:
                set_edge_style(self.graph, edge.source, edge.target, snapshot, '')
        self.rebuild_scene()
        self.commit_change()

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
            position, index = self._next_curve_point(item, points)
            points.insert(index, position.toTuple())
            _set_edge_curve_points(self.graph, edge.source, edge.target, points)
            first = first or (edge.source, edge.target, index)
        self.rebuild_scene()
        if len(self.selection.edges) == 1 and first is not None:
            self._select_curve_handle(*first)
        self.commit_change()

    @staticmethod
    def _next_curve_point(item, points):
        """Split the longest stretch of the visible path between controls."""
        path = item.path()
        elements = [path.elementAt(index) for index in range(path.elementCount())]
        distances = [0.0]
        for first, second in zip(elements, elements[1:]):
            distances.append(distances[-1] +
                             ((second.x - first.x) ** 2 + (second.y - first.y) ** 2) ** .5)

        def distance_at(path_position):
            index = min(int(path_position), len(elements) - 2)
            fraction = path_position - index
            return distances[index] + fraction * (distances[index + 1] - distances[index])

        boundaries = [0.0]
        if len(points) == 1:
            _, path_position = item.closest_path_position(QPointF(*points[0]))
            boundaries.append(distance_at(path_position))
        elif len(points) > 1:
            steps_per_span = (len(elements) - 1) / (len(points) + 1)
            boundaries.extend(distance_at((index + 1) * steps_per_span)
                              for index in range(len(points)))
        boundaries.append(distances[-1])
        insertion_index = max(range(len(boundaries) - 1),
                              key=lambda index: boundaries[index + 1] - boundaries[index])
        middle = (boundaries[insertion_index] + boundaries[insertion_index + 1]) / 2
        segment = min(max(0, bisect_right(distances, middle) - 1), len(elements) - 2)
        span = distances[segment + 1] - distances[segment]
        fraction = (middle - distances[segment]) / span if span else 0.0
        start, end = elements[segment], elements[segment + 1]
        return (QPointF(start.x + fraction * (end.x - start.x),
                        start.y + fraction * (end.y - start.y)), insertion_index)

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

    def change_type(self, delta):
        if self.scene.edge_sources:
            self.edge_color = (self.edge_color + delta) % self.graph.graph['num_edge_colors']
            self.scene.update()
            return
        if not (self.selection.nodes or self.selection.edges):
            pointer = self.context().pointer_position
            hovered = self.scene.itemAt(QPointF(*pointer), QTransform())
            if isinstance(hovered, NodeItem):
                data = self.graph.nodes[hovered.node]
                data['col'] = (data.get('col', 0) + delta) % self.graph.graph['num_vertex_colors']
                self.rebuild_scene()
                self.commit_change()
                return
            self.vertex_color = (self.vertex_color + delta) % self.graph.graph['num_vertex_colors']
            self.report(f'New vertex type: {self.vertex_color}', 2)
            return
        for node in self.selection.nodes:
            self.graph.nodes[node]['col'] = (self.graph.nodes[node].get('col', 0) + delta) % self.graph.graph['num_vertex_colors']
        for edge in self.selection.edges:
            source, target = edge.source, edge.target
            color = (self.graph.edges[source, target].get('col', 0) + delta) % self.graph.graph['num_edge_colors']
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
        self.rebuild_scene()
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
        self.scene.set_axis_snap_guides(())
        for action, active in ((self.grid_off_action, mode is None),
                               (self.grid_square_action, mode == 'square'),
                               (self.grid_radial_action, mode == 'radial'),
                               (self.grid_triangular_action, mode == 'triangular'),
                               (self.grid_axis_action, mode == 'axis')):
            action.setChecked(active)
        self._sync_controls()
        self.scene.update()
        self.update_actions()

    def set_axis_auto_snap(self, checked):
        self.axis_auto_snap = bool(checked)
        self.axis_snap_action.setChecked(self.axis_auto_snap)
        if not checked:
            self.scene.set_axis_snap_guides(())

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
            if self.view.transform().m11() > 1:
                self.view.resetTransform()
                self.view.centerOn(bounds.center())
        else:
            self.view.resetTransform()
            self.view.centerOn(0, 0)

    def run_extension(self, definition):
        context = self.context()
        # Work on isolated state: failed user code must never partially edit the
        # document, nor leave its selection pointing at deleted vertices.
        context.graph = copy.deepcopy(self.graph)
        context.selection = copy.deepcopy(self.selection)
        old_nodes = set(self.graph)
        if not execute_action(definition, context):
            return
        self.graph = context.graph
        self.selection = context.selection
        self.rebuild_scene()
        self.commit_change()
        if definition.id == 'builtin:fuse':
            self.scene.show_fusion_animation(
                self.graph.nodes[node]['position'] for node in self.graph if node not in old_nodes)

    def update_actions(self):
        if not hasattr(self, 'extension_actions'):
            return
        selected_count = len(self.selection.nodes) + len(self.selection.edges)
        self.rename_action.setEnabled(selected_count == 1)
        self.properties_action.setEnabled(bool(selected_count))
        self.copy_style_action.setEnabled(selected_count == 1)
        self.paste_style_action.setEnabled(bool(self.style_clipboard) and bool(
            self.selection.nodes if self.style_clipboard and self.style_clipboard[0] == 'vertex'
            else self.selection.edges))
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
        movable = movable_vertices(self.graph, self.selection.nodes)
        pins = pinned_vertices(self.graph)
        size = self.graph.number_of_nodes()
        self.arrange_action.setEnabled(bool(movable) and size <= 350)
        self.arrange_action.setText('Arrange selection' if self.selection.nodes else 'Arrange graph')
        self.arrange_action.setToolTip('Available for graphs with at most 350 vertices'
                                       if size > 350 else self.arrange_action.text())
        self.pin_action.setEnabled(bool(self.selection.nodes - pins))
        self.unpin_action.setEnabled(bool(self.selection.nodes & pins))
        self.clear_pins_action.setEnabled(bool(pins))
        self.live_layout_action.setEnabled(size <= 200)
        if size > 200:
            self.live_layout_action.setChecked(False)
            self.live_layout_action.setToolTip('Available for graphs with at most 200 vertices')
        self.radial_down_action.setEnabled(self.grid_mode == 'radial' and self.radial_divisions > 2)
        self.radial_up_action.setEnabled(self.grid_mode == 'radial' and self.radial_divisions < 99)
        has_precision = self.grid_mode in ('square', 'triangular', 'radial')
        self.grid_down_action.setEnabled(has_precision and self.grid_unit < COORDINATE_UNIT * 16)
        self.grid_up_action.setEnabled(has_precision and self.grid_unit > COORDINATE_UNIT / 64)
        vertex_colors = self.graph.graph['num_vertex_colors']
        edge_colors = self.graph.graph['num_edge_colors']
        if self.scene.edge_sources:
            type_available = edge_colors > 1
        elif self.selection.nodes or self.selection.edges:
            type_available = ((vertex_colors > 1 and bool(self.selection.nodes)) or
                              (edge_colors > 1 and bool(self.selection.edges)))
        else:
            type_available = vertex_colors > 1
        self.previous_type_action.setEnabled(type_available)
        self.next_type_action.setEnabled(type_available)
        self.type_control.set_limits(type_available, type_available)
        self.vertex_colors_down_action.setEnabled(vertex_colors > 1)
        self.vertex_colors_up_action.setEnabled(vertex_colors < 12)
        self.edge_colors_down_action.setEnabled(edge_colors > 1)
        self.edge_colors_up_action.setEnabled(edge_colors < 12)
        self.vertex_colors_control.set_limits(vertex_colors > 1, vertex_colors < 12)
        self.edge_colors_control.set_limits(edge_colors > 1, edge_colors < 12)
        info_available = self.info_scope.currentIndex() == 0 or bool(selected_vertices(self.selection))
        for action in self.info_actions.values():
            action.setEnabled(info_available)
        self.info_copy_action.setEnabled(self._info_has_result)
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
        for label_action, control_action, control, actions in self.transformation_controls:
            available = any(action.isEnabled() for action in actions)
            label_action.defaultWidget().setEnabled(available)
            control.setEnabled(available)

    def commit_change(self):
        state = _serialize_graph(self.graph)
        if state != self._history[self._history_index]:
            self._invalidate_info()
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
        self._invalidate_info()
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
        self._invalidate_info()
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
        if self.return_graph_on_close and self.path is None:
            event.accept()
        elif self.path is not None and _serialize_graph(self.graph) != self._saved_state:
            if self.save_file():
                event.accept()
            else:
                event.ignore()
        elif self._may_replace_document():
            event.accept()
        else:
            event.ignore()
        if event.isAccepted() and self._info_process is not None:
            self._info_request_id += 1
            self._info_process.kill()
            self._info_process.waitForFinished(100)
            self._info_process = None


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


def edit_graph_window(graph=None, *, actions=()):
    """Run a file-optional editor session for the public edit_graph API."""
    import networkx as nx
    from graph_builder_custom import normalize_graph, public_graph

    source = nx.Graph() if graph is None else graph
    if not isinstance(source, nx.Graph):
        raise TypeError('edit_graph expects a NetworkX Graph or DiGraph.')
    if source.is_multigraph():
        raise ValueError('Parallel edges are not supported by the editor.')
    initial = empty_graph(graph_type='digraph' if source.is_directed() else 'graph')
    for key in ('num_vertex_colors', 'num_edge_colors', 'show_labels'):
        if key in source.graph:
            initial.graph[key] = source.graph[key]
    normalized, _ = normalize_graph(source, initial)

    app = QApplication.instance() or QApplication([])
    window = GraphBuilderQt(normalized, actions=actions, return_graph_on_close=True)
    window.show()
    if normalized.number_of_nodes():
        window.fit_graph()
    app.exec()
    return public_graph(window.graph)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Graph Builder Qt editor')
    parser.add_argument('--graph', type=Path, help='GraphML file to edit')
    args = parser.parse_args()
    raise SystemExit(launch(graph_file=args.graph))
