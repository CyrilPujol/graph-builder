"""Qt application shell for Graph Builder.

The graph model and built-in actions live in ``lib``. Custom button
registration lives in ``custom``. Canvas rendering and pointer gestures live
in ``qt_canvas``. This module owns menus, controls, history and files.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import tempfile
import time
from bisect import bisect_right
from math import hypot, sqrt
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QPointF, QProcess, QRectF, QSize, QSettings, QStandardPaths, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QColor, QCursor, QDesktopServices, QIcon, QKeySequence, QPainter, QPainterPath, QPalette, QPen, QPixmap, QShortcut, QTransform
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QComboBox, QDockWidget, QDoubleSpinBox, QFileDialog, QFrame,
    QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox, QScrollArea, QSpinBox, QStackedWidget,
    QTabBar,
    QTabWidget, QTextBrowser, QTextEdit, QLineEdit, QToolBar, QToolButton, QVBoxLayout, QWidget,
)

from .lib import (
    Action, EdgeRef, EditorContext, SelectionState, _deserialize_graph,
    _edge_curve_points, _serialize_graph, _set_edge_curve_points,
    axis_alignment_plan, builtin_editor_actions, convert_from_file, copy_graph_selection,
    cut_edges_to_rest, empty_graph, execute_action, flip_edge, full_join, labels_visible,
    nearest_grid_point, selected_vertices,
    paste_graph_selection, set_directed, set_edge_label, unused_label,
    vertex_label, write_graph_file,
)
from .qt_canvas import (
    COORDINATE_UNIT, DEFAULT_GRID_PRECISION, CurveHandle, EdgeItem, GraphScene,
    GraphView, NodeItem, RegionBoundaryItem, RegionCurveHandle, RegionItem,
)
from .custom import public_graph
from .layout import (PIN_ATTRIBUTE, arrange_positions, movable_vertices,
                          pinned_vertices, relaxed_neighborhood_positions)
from .info import (ANALYSIS_TIMEOUT_MS, OPTIMIZATION_TIMEOUT_MS, BOUND_PROBLEMS,
                   BOUND_SYMBOLS, SHOWABLE_BOUNDS, DIRECT_BOUNDS, topology_payload)
from .tikz_export import write_tikz
from .picture_export import convert_picture_pdf, render_picture_pdf
from .picture_preview import PicturePreview
from .edges import edge_data, visible_edges, has_edge, remove_edge, set_multiedges
from .standard_graphs import STANDARD_GRAPHS, generate_standard_graph, validate_standard_graph
from .products import PRODUCTS, generate_product
from .styles import (copy_style, effective_style, has_custom_look, paste_style, set_overrides,
                     set_edge_style, set_palette_style, use_basic_style)
from .style_ui import PropertiesDialog, RegionPropertiesDialog, StylesDialog
from .regions import (DEFAULT_REGION_STYLE, add_region, cycle_from_edges, hull_region_nodes, path_segment,
                      line_controls, region_by_id, region_points, regions, remove_regions,
                      set_line_controls, set_region_properties, set_regions, update_region,
                      valid_boundary, prune_regions)
from .tutorial import TutorialPanel, tutorial_graph


def _documents_folder():
    location = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
    return Path(location) if location else Path.home()


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
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(0)
        layout.addWidget(self.decrease)
        layout.addWidget(self.increase)
        self.setFixedSize(60, 30)
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
        self._last_open_index = -1
        self._previous_index = None
        self._cycling = False
        self.tabBarClicked.connect(self._tab_clicked)

    def open_tab(self, index, *, cycling=False):
        self._open_index = index
        if not cycling:
            previous = self._last_open_index
            if previous >= 0 and previous != index:
                self._previous_index = previous
            self._cycling = False
        self._last_open_index = index
        self.tabBar().setProperty('menuOpen', True)
        self.setMaximumHeight(16777215)
        self.setCurrentIndex(index)
        if self.currentWidget() is not None:
            self.currentWidget().show()
        self._refresh_tab_style()

    def close_tab(self):
        self._open_index = -1
        self._cycling = False
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

    def cycle_tab(self, direction=1):
        if not self.count():
            return
        current = self.currentIndex()
        if not self._cycling and self._previous_index is not None:
            target = self._previous_index
        else:
            target = (current + direction) % self.count()
        self._cycling = True
        self.open_tab(target, cycling=True)


class GraphBuilderQt(QMainWindow):
    def __init__(self, graph=None, path=None, actions=(), return_graph_on_close=False):
        super().__init__()
        self.graph = graph if graph is not None else empty_graph()
        self.path = Path(path) if path is not None else None
        self.return_graph_on_close = return_graph_on_close
        self.custom_actions = tuple(actions)
        if any(not isinstance(action, Action) for action in self.custom_actions):
            raise TypeError('Custom actions must be Graph Builder Action values')
        self.builtin_actions = builtin_editor_actions()
        self.node_items = {}
        self.edge_items = {}
        self.region_items = {}
        self.region_boundary_items = []
        self._regions_without_selection_cue = set()
        self.curve_handles = []
        self.region_curve_handles = []
        self.selection = SelectionState()
        self._full_join_first = frozenset()
        self._morphism_first = frozenset()
        self._morphism_process = None
        self._minor_first = frozenset()
        self._minor_process = None
        self._product_first = frozenset()
        self._product_kind = None
        self.region_path = None
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
        self._info_kind = None
        self._info_topology = topology_payload(public_graph(self.graph))
        self._pending_bound_problem = None
        self._pending_show_problem = None
        self._bound_results = {}
        self._bound_quick_lines = {}
        self._last_live_layout = 0.0
        self._live_drag_changed = False
        self._active_style_dialog = None
        self._picture_temp = None

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
        self._register_unavailable_shortcuts()
        self.rebuild_scene()
        self.view.centerOn(self.grid_origin)
        self._basic_moves_completed = set()
        self.onboarding_hint = QLabel(
            'Click to create/select/move · Secondary-drag for edges and lasso selection · Alt-drag to pan.', self)
        self.statusBar().addWidget(self.onboarding_hint, 1)
        self.statusBar().messageChanged.connect(self._sync_status_bar_visibility)
        self.update_actions()
        self._keyboard_filter_active = False

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, '_keyboard_filter_active', False):
            QApplication.instance().installEventFilter(self)
            self._keyboard_filter_active = True

    def hideEvent(self, event):
        if getattr(self, '_keyboard_filter_active', False):
            QApplication.instance().removeEventFilter(self)
            self._keyboard_filter_active = False
        super().hideEvent(event)

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.KeyPress and self.isActiveWindow()
                and QApplication.activeModalWidget() is None
                and QApplication.activePopupWidget() is None):
            focus = QApplication.focusWidget()
            typing = isinstance(focus, (QLineEdit, QAbstractSpinBox, QComboBox, QTextEdit))
            key = event.key()
            modifiers = event.modifiers()
            if not typing and key in (Qt.Key_Tab, Qt.Key_Backtab) and not (
                    modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)):
                self.menu_tabs.cycle_tab(-1 if key == Qt.Key_Backtab or
                                         modifiers & Qt.ShiftModifier else 1)
                return True
            if not typing and key in (Qt.Key_Return, Qt.Key_Enter) and not modifiers:
                action = self._active_staged_action()
                if action is not None:
                    action.trigger()
                    return True
        return super().eventFilter(watched, event)

    def _active_staged_action(self):
        if self._product_first:
            return self.product_confirm_action
        if self._full_join_first:
            return self.full_join_action
        if self._morphism_first or self._morphism_process is not None:
            return self.morphism_action
        if self._minor_first or self._minor_process is not None:
            return self.minor_action
        return None

    def _sync_status_bar_visibility(self, message=''):
        self.statusBar().setVisible(self.onboarding_hint.isVisible() or bool(message))

    def mark_basic_move(self, move):
        self._basic_moves_completed.add(move)
        self._observe_tutorial(move)
        if {'create_vertex', 'create_edge', 'move_vertex'} <= self._basic_moves_completed:
            self.onboarding_hint.hide()
            self._sync_status_bar_visibility(self.statusBar().currentMessage())

    def _observe_tutorial(self, move):
        if self.tutorial_active:
            self.tutorial_panel.observe(move)

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
        if kind == 'Bounds' and len(lines) >= len(BOUND_PROBLEMS):
            self._bound_results = {}
            self.bound_heading.setText(f'Bounds · {scope}')
            for index, problem in enumerate(BOUND_PROBLEMS):
                quick_line = lines[index]
                self._bound_quick_lines[problem] = quick_line
                self.bound_labels[problem].setText(quick_line)
                self.bound_solve_buttons[problem].setEnabled(True)
                self.bound_solve_buttons[problem].setText('Compute')
                exact_value = re.search(
                    rf'{re.escape(BOUND_SYMBOLS[problem])}: (\d+)$', quick_line)
                quick_proved = bool(exact_value)
                self.bound_solve_buttons[problem].setVisible(
                    problem not in DIRECT_BOUNDS and not quick_proved)
                self.bound_color_buttons[problem].setVisible(
                    bool(exact_value) and int(exact_value.group(1)) > 0)
            self.bound_note.setText('\n'.join(lines[len(BOUND_PROBLEMS):]))
            self.info_stack.setCurrentWidget(self.bounds_scroll)
        else:
            self.info_stack.setCurrentWidget(self.info_text)
        self.help_dock.hide()
        self.picture_dock.hide()
        self.info_dock.show()
        self._info_has_result = True
        self._info_outdated = False
        self.info_outdated_bar.hide()
        self.info_copy_action.setEnabled(True)
        if kind == 'Bounds' and len(lines) >= len(BOUND_PROBLEMS) and self._pending_bound_problem:
            problem = self._pending_bound_problem
            self._pending_bound_problem = None
            QTimer.singleShot(0, lambda: self.solve_bound(problem))

    def _invalidate_info(self):
        self._info_request_id += 1
        self._pending_bound_problem = None
        self._pending_show_problem = None
        self._bound_results = {}
        if hasattr(self, 'bound_color_buttons'):
            for button in self.bound_color_buttons.values():
                button.hide()
            if self.info_stack.currentWidget() is self.bounds_scroll:
                for problem, button in self.bound_solve_buttons.items():
                    button.setText('Compute')
                    button.setEnabled(True)
                    button.setVisible(problem not in DIRECT_BOUNDS)
        if self._info_process is not None:
            process = self._info_process
            self._info_process = None
            process.kill()
            process.waitForFinished(100)
            self._release_info_process(process)
            process.deleteLater()
            self.info_text.setPlainText('Graph metrics\n\nOutdated — graph or selection changed. Run again.')
            self._info_has_result = True
            self._info_outdated = True
            self.info_copy_action.setEnabled(True)
        if self._info_has_result and not self._info_outdated:
            self.info_text.append('\nOutdated — graph or selection changed. Run again.')
            self._info_outdated = True
        if self._info_outdated:
            self.info_outdated_bar.show()

    def refresh_graph_info(self):
        if self._info_kind is None:
            return
        if self.info_scope.currentIndex() and not selected_vertices(self.selection):
            pending = self._pending_bound_problem
            self.info_scope.setCurrentIndex(0)
            self._pending_bound_problem = pending
        self.show_graph_info(self._info_kind)

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
        self._info_kind = kind
        self._info_selection_nodes = set(scope_nodes) if scope_nodes is not None else None
        self._info_request_id += 1
        request_id = self._info_request_id
        if self._info_process is not None:
            previous = self._info_process
            previous.kill()
            previous.waitForFinished(100)
            self._release_info_process(previous)
            previous.deleteLater()
            self._info_process = None
        self._info_has_result = False
        self._bound_results = {}
        self.info_outdated_bar.hide()
        self.info_copy_action.setEnabled(False)
        self.info_text.setPlainText(f'{kind} · {scope}\n\nCalculating…')
        self.info_stack.setCurrentWidget(self.info_text)
        self.help_dock.hide()
        self.picture_dock.hide()
        self.info_dock.show()
        process = QProcess(self)
        worker_dir = tempfile.TemporaryDirectory(prefix='graph-builder-info-')
        process._worker_dir = worker_dir
        input_path = Path(worker_dir.name) / 'input.json'
        process._result_path = Path(worker_dir.name) / 'result.json'
        process._bound_problem = None
        input_path.write_text(json.dumps(topology_payload(graph)), encoding='utf-8')
        self._info_process = process
        process.finished.connect(lambda exit_code, exit_status: self._finish_graph_info(
            request_id, process, kind, scope, exit_code))
        process.errorOccurred.connect(lambda error: self._graph_info_process_error(
            request_id, process, kind, scope, error))
        if getattr(sys, 'frozen', False):
            arguments = ['--graph-info-worker', kind, str(input_path), str(process._result_path)]
        else:
            arguments = ['-m', 'graph_builder_core.info', '--worker', kind,
                         str(input_path), str(process._result_path)]
        process.start(sys.executable, arguments)
        timeout_ms = ANALYSIS_TIMEOUT_MS
        QTimer.singleShot(timeout_ms,
                          lambda: self._timeout_graph_info(request_id, process, kind, scope))

    def bound_button_clicked(self, problem):
        if self._info_process is not None and self._info_process._bound_problem == problem:
            self.stop_bound(problem)
        else:
            self.solve_bound(problem)

    def stop_bound(self, problem):
        process = self._info_process
        if process is None or process._bound_problem != problem:
            return
        self._info_request_id += 1
        self._info_process = None
        if self._pending_show_problem == problem:
            self._pending_show_problem = None
        process.kill()
        process.waitForFinished(100)
        self._release_info_process(process)
        process.deleteLater()
        self.bound_labels[problem].setText(self._bound_quick_lines.get(problem, '') + '\nStopped.')
        button = self.bound_solve_buttons[problem]
        button.setText('Compute')
        button.setVisible(problem not in DIRECT_BOUNDS)
        self.bound_color_buttons[problem].setVisible(problem in DIRECT_BOUNDS)
        self.info_text.setPlainText(self.bound_heading.text() + '\n\n' + '\n'.join(
            self.bound_labels[key].text() for key in BOUND_PROBLEMS))

    def solve_bound(self, problem):
        """Run only the requested invariant in the existing bounded worker."""
        if problem not in self.bound_labels:
            return
        if self._info_outdated:
            self._pending_bound_problem = problem
            self.refresh_graph_info()
            return
        graph = public_graph(self.graph)
        if self._info_selection_nodes is not None:
            graph = graph.subgraph(self._info_selection_nodes).copy()
        self._info_request_id += 1
        request_id = self._info_request_id
        if self._info_process is not None:
            previous = self._info_process
            self._info_process = None
            if self._pending_show_problem == previous._bound_problem:
                self._pending_show_problem = None
            previous.kill()
            previous.waitForFinished(100)
            self._release_info_process(previous)
            if previous._bound_problem:
                prior = previous._bound_problem
                self.bound_labels[prior].setText(self._bound_quick_lines.get(prior, '') + ' · Canceled')
                self.bound_solve_buttons[prior].setText('Compute')
                self.bound_solve_buttons[prior].show()
            previous.deleteLater()
        self.bound_solve_buttons[problem].setText('Stop')
        self.bound_solve_buttons[problem].setEnabled(True)
        self.bound_solve_buttons[problem].show()
        self.bound_color_buttons[problem].hide()
        self._bound_results.pop(problem, None)
        self.bound_labels[problem].setText(self.bound_labels[problem].text().split(' · ')[0]
                                           + ' · Computing…')
        process = QProcess(self)
        worker_dir = tempfile.TemporaryDirectory(prefix='graph-builder-bound-')
        process._worker_dir = worker_dir
        input_path = Path(worker_dir.name) / 'input.json'
        process._result_path = Path(worker_dir.name) / 'result.json'
        process._bound_problem = problem
        input_path.write_text(json.dumps(topology_payload(graph)), encoding='utf-8')
        self._info_process = process
        scope = (f'{len(self._info_selection_nodes)} selected vertices'
                 if self._info_selection_nodes is not None else 'whole graph')
        kind = f'Solve:{problem}'
        process.finished.connect(lambda exit_code, exit_status: self._finish_graph_info(
            request_id, process, kind, scope, exit_code))
        process.errorOccurred.connect(lambda error: self._graph_info_process_error(
            request_id, process, kind, scope, error))
        arguments = (['--graph-info-worker', kind, str(input_path), str(process._result_path)]
                     if getattr(sys, 'frozen', False) else
                     ['-m', 'graph_builder_core.info', '--worker', kind,
                      str(input_path), str(process._result_path)])
        process.start(sys.executable, arguments)
        QTimer.singleShot(OPTIMIZATION_TIMEOUT_MS,
                          lambda: self._timeout_graph_info(request_id, process, kind, scope))

    def _display_bound_solution(self, problem, payload):
        solve_button = self.bound_solve_buttons[problem]
        solve_button.setText('Compute')
        solve_button.setEnabled(True)
        solve_button.show()
        if 'error' in payload:
            if self._pending_show_problem == problem:
                self._pending_show_problem = None
            self._bound_results.pop(problem, None)
            self.bound_labels[problem].setText(
                self._bound_quick_lines.get(problem, '') + '\n' + payload['error'])
        else:
            payload['optimal'] = bool(payload.get('optimal') or payload['lower'] == payload['upper'])
            self._bound_results[problem] = payload
            symbol = BOUND_SYMBOLS[problem]
            value = (str(payload['lower']) if payload['lower'] == payload['upper'] else
                     f'{payload["lower"]} ≤ {symbol} ≤ {payload["upper"]}')
            note = f' ({payload["note"]})' if payload.get('note') and not payload['optimal'] else ''
            self.bound_labels[problem].setText(f'{payload["name"]}: {value}{note}')
            self.bound_color_buttons[problem].setVisible(
                problem in SHOWABLE_BOUNDS and bool(payload['witness']))
            if payload['optimal']:
                solve_button.hide()
            if self._pending_show_problem == problem:
                self._pending_show_problem = None
                if payload['witness']:
                    QTimer.singleShot(0, lambda: self.show_bound_solution(problem))
        self.info_text.setPlainText(self.bound_heading.text() + '\n\n' + '\n'.join(
            self.bound_labels[key].text() for key in BOUND_PROBLEMS)
            + ('\n' + self.bound_note.text() if self.bound_note.text() else ''))
        self._info_has_result = True
        self.info_copy_action.setEnabled(True)

    def show_bound_solution(self, problem):
        """Show a solution witness with vertex or edge styles in one undoable change."""
        result = self._bound_results.get(problem)
        if self._info_outdated:
            return
        if result is None:
            self._pending_show_problem = problem
            self.solve_bound(problem)
            return
        if not result['witness']:
            return
        scope = (set(self._info_selection_nodes) if self._info_selection_nodes is not None
                 else set(self.graph))
        witness = result['witness']
        if problem == 'treewidth':
            from .lib import colormap_1
            remove_regions(self.graph, {region['id'] for region in regions(self.graph)
                                        if region.get('tag') == 'treewidth'})
            for index, bag in enumerate(witness['bags']):
                bag_vertices = set(bag['vertices'])
                nodes = [node for node in self.graph if node in bag_vertices]
                if not nodes:
                    continue
                rgb = colormap_1(index + 1)
                pastel = tuple(round(0.5 * channel + 0.5 * 255) for channel in rgb)
                fill = '#%02x%02x%02x' % pastel
                add_region(self.graph, mode='bag', nodes=nodes,
                           label=bag['name'], margin=25,
                           style={'fill': fill, 'opacity': .3,
                                  'outline': '#687581', 'width': 1.5},
                           tag='treewidth')
            self.rebuild_scene()
            self.commit_change()
            self.report('Tree-decomposition bags shown as regions. Undo removes them.')
            return
        if problem in ('chromatic', 'domatic'):
            colors = {node: int(color) + 1 for node, color in witness}
            count = max(colors.values(), default=0) + 1
        elif problem in ('clique', 'independent', 'vertex_cover', 'domination'):
            chosen = set(witness)
            colors = {node: int(node in chosen) for node in scope}
            count = 2
        else:
            colors = None
        if colors is not None:
            self.graph.graph['num_vertex_colors'] = max(self.graph.graph['num_vertex_colors'], count)
            for node, color in colors.items():
                if node not in scope or node not in self.graph:
                    continue
                attributes = self.graph.nodes[node]
                attributes['col'] = color
                use_basic_style(attributes, color)
        else:
            directed = self.graph.graph.get('graph_type') != 'graph'
            def identity(source, target, key):
                return (source, target, key) if directed else (frozenset((source, target)), key)
            if problem == 'edge_chromatic':
                edge_colors = {identity(*edge): int(color) + 1 for edge, color in witness}
            else:
                selected = {identity(*edge) for edge in witness}
                edge_colors = {edge: 1 for edge in selected}
            self.graph.graph['num_edge_colors'] = max(
                self.graph.graph['num_edge_colors'], max(edge_colors.values(), default=0) + 1, 2)
            for source, target, key, _ in visible_edges(self.graph):
                if source not in scope or target not in scope:
                    continue
                color = edge_colors.get(identity(source, target, key), 0)
                use_basic_style(edge_data(self.graph, source, target, key), color)
                if not directed and source != target:
                    use_basic_style(edge_data(self.graph, target, source, key), color)
        self.rebuild_scene()
        self.commit_change()
        self.report('Showing the solution. Undo restores the previous styles.')

    def color_bound_solution(self, problem):
        """Compatibility alias for scripts that called the former UI action."""
        self.show_bound_solution(problem)

    def open_house_of_graphs(self):
        """Search this graph on House of Graphs in the default browser."""
        from .house_of_graphs import search_url
        graph = public_graph(self.graph)
        try:
            url = search_url(graph)
        except ValueError as error:
            self.report(str(error), 7)
            return
        if not QDesktopServices.openUrl(QUrl(url)):
            QApplication.clipboard().setText(url)
            self.report('Could not open the browser. Search link copied to the clipboard.', 7)

    @staticmethod
    def _release_info_process(process):
        worker_dir = getattr(process, '_worker_dir', None)
        if worker_dir is not None:
            worker_dir.cleanup()
            process._worker_dir = None

    def _finish_graph_info(self, request_id, process, kind, scope, exit_code):
        if request_id == self._info_request_id and self._info_process is process:
            self._info_process = None
            if exit_code == 0:
                try:
                    lines = json.loads(process._result_path.read_text(encoding='utf-8'))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    lines = (['Analysis returned an unreadable result.'] if not process._bound_problem
                             else {'error': 'Analysis returned an unreadable result.'})
            else:
                detail = bytes(process.readAllStandardError()).decode('utf-8', errors='replace').strip()
                message = f'Analysis failed: {detail or "worker stopped unexpectedly"}'
                lines = {'error': message} if process._bound_problem else [message]
            if process._bound_problem:
                self._display_bound_solution(process._bound_problem, lines)
            else:
                self._display_info(kind, scope, lines)
        self._release_info_process(process)
        process.deleteLater()

    def _graph_info_process_error(self, request_id, process, kind, scope, error):
        if (request_id == self._info_request_id and self._info_process is process
                and error == QProcess.FailedToStart):
            self._info_process = None
            if process._bound_problem:
                self._display_bound_solution(process._bound_problem,
                                             {'error': 'Could not start the analysis process.'})
            else:
                self._display_info(kind, scope, ['Could not start the analysis process.'])
            self._release_info_process(process)
            process.deleteLater()

    def _timeout_graph_info(self, request_id, process, kind, scope):
        if request_id != self._info_request_id or self._info_process is not process:
            return
        self._info_request_id += 1
        self._info_process = None
        process.kill()
        process.waitForFinished(100)
        self._release_info_process(process)
        process.deleteLater()
        if process._bound_problem:
            self._display_bound_solution(process._bound_problem,
                                         {'error': 'Not computed within one minute.'})
            return
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

    def _register_unavailable_shortcuts(self):
        """Give disabled canvas shortcuts a small explanation instead of silence."""
        self._unavailable_shortcuts = []
        actions = (
            self.undo_action, self.redo_action, self.copy_action, self.paste_action,
            self.select_all_action, self.delete_action, self.copy_style_action,
            self.paste_style_action, self.deselect_action, self.previous_type_action,
            self.next_type_action, self.cut_action, self.full_join_action, self.fit_action,
            self.labels_action,
            *(action for _, action in self.extension_actions),
        )
        for action in actions:
            for sequence in action.shortcuts():
                if sequence.isEmpty():
                    continue
                shortcut = QShortcut(sequence, self.view)
                shortcut.setContext(Qt.WidgetWithChildrenShortcut)
                shortcut.activated.connect(
                    lambda target=action: self.report(self._unavailable_shortcut_message(target), 3))
                self._unavailable_shortcuts.append((action, shortcut))

    def _unavailable_shortcut_message(self, action):
        if action in (self.previous_type_action, self.next_type_action):
            return 'No other style is available for this selection.'
        if action is self.cut_action:
            return 'Cut needs selected vertices connected to the rest of the graph.'
        if action is self.full_join_action:
            return 'Select at least one vertex to start Full join.'
        if action is self.delete_action:
            return 'Select a vertex or edge to delete.'
        if action is self.undo_action:
            return 'Nothing to undo.'
        if action is self.redo_action:
            return 'Nothing to redo.'
        if action is self.paste_action:
            return 'Nothing to paste yet.'
        if action is self.deselect_action:
            return 'Nothing is selected.'
        return f'{action.text().replace("&", "")} is unavailable for the current graph or selection.'

    def _build_actions(self):
        self.new_action = self._action('New', self.new_file, QKeySequence.New)
        self.open_action = self._action('Open…', self.open_file, QKeySequence.Open)
        self.save_action = self._action('Save', self.save_file, QKeySequence.Save)
        self.save_as_action = self._action('Save As…', self.save_as, QKeySequence.SaveAs)
        self.export_action = self._action('Export to TikZ…', self.export_tikz, 'Ctrl+E')
        self.export_picture_action = self._action('Export picture…', self.export_picture)
        self.close_action = self._action('Quit', self.close, QKeySequence.Quit)

        self.undo_action = self._action('Undo', self.undo, QKeySequence.Undo)
        self.redo_action = self._action('Redo', self.redo, QKeySequence.Redo)
        self.copy_action = self._action('Copy', self.copy_selection, QKeySequence.Copy)
        self.paste_action = self._action('Paste', self.paste_selection, QKeySequence.Paste)
        self.select_all_action = self._action('Select all', self.select_all_vertices,
                                              QKeySequence.SelectAll)
        self.select_colors_action = self._action('Select colors', self.select_colors)
        self.select_colors_action.setToolTip('Select every vertex with a selected style index.')
        self.delete_action = self._action('Delete', self.delete_selection)
        # On a Mac keyboard the key labelled "delete" sends Backspace.  Keep
        # forward Delete as an alternative for full-size and non-Mac keyboards.
        self.delete_action.setShortcuts((QKeySequence(Qt.Key_Backspace),
                                         QKeySequence(Qt.Key_Delete)))
        self._set_action_tooltip(self.delete_action)
        self.rename_action = self._action('Rename…', self.rename_selection)
        self.remove_coloring_action = self._action('Remove coloring', self.remove_coloring)
        self.remove_coloring_action.setToolTip(
            'Reset vertex and edge styles to 0 and restore the default region look.')
        self.properties_action = self._action('Properties…', self.edit_selection_properties)
        self.styles_action = self._action('Basic styles…', self.edit_shared_styles)
        self.copy_style_action = self._action('Copy style', self.copy_selected_style, 'Ctrl+Shift+C')
        self.paste_style_action = self._action('Paste style', self.paste_selected_style, 'Ctrl+Shift+V')
        self.addAction(self.copy_style_action)
        self.addAction(self.paste_style_action)
        self.deselect_action = self._action('Deselect', self.deselect, 'Escape')

        self.add_curve_action = self._action('Curve point', self.add_curve_point)
        self.previous_type_action = self._action('Previous style', lambda: self.change_type(-1), 'Shift+S')
        self.next_type_action = self._action('Next style', lambda: self.change_type(1), 'S')
        self.cut_action = self._action('Cut', self.cut_edges, 'C')
        self.full_join_action = self._action('Full join', self.full_join_selection,
                                            'J', checkable=True)
        self.full_join_action.setToolTip(
            'Full join — J\nConnect every vertex in a first set to every vertex in a second set.')
        self.product_confirm_action = self._action('Product', self.product_selection)
        self.product_actions = {
            kind: self._action(title, lambda checked=False, kind=kind: self.start_product(kind))
            for kind, (title, _) in PRODUCTS.items()
        }
        self.morphism_action = self._action('Morphism', self.morphism_selection,
                                            checkable=True)
        self.morphism_action.setToolTip(
            'Find a homomorphism from a first selected set to a second selected set.')
        self.minor_action = self._action('Minor', self.minor_selection, checkable=True)
        self.minor_action.setToolTip('Test whether a first selected graph contains a second as an undirected minor.')
        self.make_region_action = self._action('Make region', self.make_region, checkable=True)
        self.make_region_action.setToolTip(
            'Fill a selected edge cycle or vertex hull. With no selection, click a boundary path. '
            'Alt-click inside a region to add a vertex there.')
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
        self.multiedges_action = self._action('Multiedges', self.set_multiedges, checkable=True)
        self.loops_action = self._action('Loops', self.set_loops, checkable=True)
        self.grid_off_action = self._action('Manual', lambda: self.set_grid(None), checkable=True)
        self.grid_automatic_action = self._action('Automatic', lambda: self.set_grid(None if self.grid_mode == 'automatic' else 'automatic'), checkable=True)
        self.grid_square_action = self._action('Square grid', lambda: self.set_grid(None if self.grid_mode == 'square' else 'square'), checkable=True)
        self.grid_triangular_action = self._action('Triangular grid', lambda: self.set_grid(None if self.grid_mode == 'triangular' else 'triangular'), checkable=True)
        self.grid_radial_action = self._action('Radial grid', lambda: self.set_grid(None if self.grid_mode == 'radial' else 'radial'), checkable=True)
        self.grid_axis_action = self._action('Axes', lambda: self.set_grid(None if self.grid_mode == 'axis' else 'axis'), checkable=True)
        self.axis_snap_action = self._action('Auto-snap', self.set_axis_auto_snap,
                                             checkable=True)
        self.grid_group = QActionGroup(self)
        self.grid_group.setExclusive(True)
        for action in (self.grid_off_action, self.grid_automatic_action, self.grid_square_action,
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
        self.vertex_colors_down_action = self._action('Fewer vertex styles', lambda: self.change_vertex_colors(self.graph.graph['num_vertex_colors'] - 1))
        self.vertex_colors_up_action = self._action('More vertex styles', lambda: self.change_vertex_colors(self.graph.graph['num_vertex_colors'] + 1))
        self.edge_colors_down_action = self._action('Fewer edge styles', lambda: self.change_edge_colors(self.graph.graph['num_edge_colors'] - 1))
        self.edge_colors_up_action = self._action('More edge styles', lambda: self.change_edge_colors(self.graph.graph['num_edge_colors'] + 1))
        self.info_actions = {
            kind: self._action(kind, lambda checked=False, view=kind: self.show_graph_info(view))
            for kind in ('Overview', 'Structure', 'Bounds')
        }
        self.house_of_graphs_action = self._action('House of Graphs', self.open_house_of_graphs)
        self.house_of_graphs_action.setToolTip('Search for this graph on House of Graphs.')
        self.info_copy_action = self._action('Copy results', self.copy_graph_info)

        for action, description in (
            (self.fit_action, 'Center the whole graph in view.'),
            (self.rename_action, 'Change the label of a vertex or edge.'),
            (self.previous_type_action, 'Previous vertex/edge style.'),
            (self.next_type_action, 'Next vertex/edge style.'),
            (self.add_curve_action, 'Add a control point along the edge. Drag to reshape.'),
            (self.cut_action, 'Disconnect the selection from the rest of the graph.'),
            (self.axis_snap_action, 'Align vertices while dragging.'),
            (self.grid_down_action, 'Double the spacing between grid lines or circles.'),
            (self.grid_up_action, 'Halve the spacing between grid lines or circles.'),
            (self.labels_action, 'Show or hide vertex and edge labels.'),
            (self.directed_action, 'Show edges as directed arrows.'),
            (self.multiedges_action, 'Allow several edges between the same vertices. Drag to add an edge.'),
            (self.loops_action, 'Allow loops. Drag outside a vertex and back to connect it to itself.'),
            (self.arrange_action, 'Automatically arrange vertices.'),
            (self.pin_action, 'Keep selected vertices in place when arranging.'),
            (self.unpin_action, 'Allow selected vertices to move when arranging.'),
            (self.styles_action, 'Edit the basic styles shared by vertices and edges.'),
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
                                self.save_as_action, self.export_action,
                                self.export_picture_action))

        basic_row = row('Edition', (self.undo_action, self.redo_action,
                                  self.copy_action, self.paste_action,
                                  self.select_all_action, self.select_colors_action,
                                  self.delete_action))
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

        edition_row = row('Structure', (self.directed_action, self.multiedges_action, self.loops_action))
        edition_row.addSeparator()
        edition_row.addAction(self.cut_action)
        edition_row.addAction(self.full_join_action)
        self.full_join_button = edition_row.widgetForAction(self.full_join_action)
        self.full_join_button.setFixedSize(self.full_join_button.sizeHint().width() + 8,
                                           self.full_join_button.sizeHint().height())
        self.full_join_button.setStyleSheet('''
            QToolButton { border: 1px solid #d0d4d9; border-radius: 4px;
                          color: #111111; background: #f5f6f7;
                          padding: 4px 7px; margin-right: 3px; }
            QToolButton:hover:enabled { background: #e6ecee; }
            QToolButton:checked { border: 2px solid #a76a12; font-weight: 700;
                                  color: #111111; background: #fff1d8;
                                  padding: 3px 6px; }
            QToolButton:disabled { color: #777d84; background: #f1f2f3;
                                   border-color: #777d84; }
        ''')
        edition_row.addActions(tuple(action for definition, action in self.extension_actions
                                     if definition.group == 'edition' and not definition.pair_id))
        edition_row.addAction(self.make_region_action)
        edition_row.addSeparator()
        product_menu = QMenu(edition_row)
        product_menu.addActions(tuple(self.product_actions.values()))
        self.product_button = QToolButton(edition_row)
        self.product_button.setText('Product')
        self.product_button.setCheckable(True)
        self.product_button.setToolTip('Choose a product of two selected vertex sets.')
        self.product_button.setFixedSize(140, 30)
        self.product_button.setPopupMode(QToolButton.InstantPopup)
        self.product_button.setMenu(product_menu)
        self.product_button.clicked.connect(self._product_button_clicked)
        self.product_button.setStyleSheet('''
            QToolButton { color: #111111; background: #f5f6f7;
                          border: 1px solid #b8bec4; border-radius: 4px;
                          padding: 3px 15px 3px 5px; }
            QToolButton::menu-indicator { subcontrol-origin: padding;
                                          subcontrol-position: right center; right: 5px; }
            QToolButton:checked { color: #111111; background: #fff1d8;
                                  border: 2px solid #a76a12; font-weight: 700; }
        ''')
        edition_row.addWidget(self.product_button)

        grid_row = row('Layout', (self.fit_action, self.grid_off_action,
                                self.grid_automatic_action,
                                self.grid_axis_action,
                                self.grid_square_action, self.grid_radial_action,
                                self.grid_triangular_action))
        grid_row.insertSeparator(self.grid_off_action)
        self.grid_options_separator = grid_row.addSeparator()
        self.automatic_actions = (self.arrange_action, self.pin_action, self.unpin_action,
                                  self.clear_pins_action, self.live_layout_action)
        grid_row.addActions(self.automatic_actions)
        grid_row.addAction(self.axis_snap_action)
        self.grid_unit_label = QLabel(grid_row)
        self.grid_unit_label_action = grid_row.addWidget(self.grid_unit_label)
        self.grid_unit_control = StepControl(self.grid_down_action, self.grid_up_action, grid_row)
        self.grid_unit_control_action = grid_row.addWidget(self.grid_unit_control)
        self.radial_label = QLabel(grid_row)
        self.radial_label_action = grid_row.addWidget(self.radial_label)
        self.radial_control = StepControl(self.radial_down_action, self.radial_up_action, grid_row)
        self.radial_control_action = grid_row.addWidget(self.radial_control)

        properties_row = row('Appearances', (self.labels_action, self.add_curve_action,
                                             self.rename_action, self.remove_coloring_action))
        properties_row.addWidget(QLabel('  Style:', properties_row))
        self.type_control = StepControl(self.previous_type_action, self.next_type_action,
                                        properties_row)
        properties_row.addWidget(self.type_control)
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

        info_row = row('Metrics', (self.morphism_action, self.minor_action))
        for action in (self.morphism_action, self.minor_action):
            button = info_row.widgetForAction(action)
            button.setFixedSize(button.sizeHint().width() + 8, button.sizeHint().height())
            button.setStyleSheet(self.full_join_button.styleSheet())
        info_row.addSeparator()
        info_row.addActions(tuple(self.info_actions.values()))
        self.info_scope = QComboBox(info_row)
        self.info_scope.addItems(('Whole graph', 'Selected vertices'))
        self.info_scope.setStyleSheet('QComboBox { color: #111111; background: #f5f6f7; '
                                     'border: 1px solid #b8bec4; border-radius: 4px; padding: 3px 8px; } '
                                     'QComboBox QAbstractItemView { color: #111111; background: white; }')
        self.info_scope.currentIndexChanged.connect(lambda: (self._invalidate_info(), self.update_actions()))
        info_row.addWidget(self.info_scope)
        info_row.addAction(self.info_copy_action)
        info_row.addAction(self.house_of_graphs_action)

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
            custom_row.addWidget(QLabel(
                'This app has no custom buttons. Add your own by running a short Python script.',
                custom_row))
            custom_row.addAction(self._action('How to add functions', self.show_custom_help))
        tabs.tabBar().setTabButton(tabs.count() - 1, QTabBar.RightSide, self.help_button)
        tabs.open_tab(0)
        layout.addWidget(tabs)
        layout.addWidget(self.view, 1)
        self.setCentralWidget(container)
        self.info_dock = QDockWidget('Graph metrics', self)
        self.info_dock.setAllowedAreas(Qt.RightDockWidgetArea)
        self.info_dock.setMinimumWidth(315)
        self.info_text = QTextEdit(self.info_dock)
        self.info_text.setReadOnly(True)
        self.info_text.setStyleSheet('QTextEdit { color: #111111; background: #ffffff; padding: 8px; }')
        self.bounds_panel = QWidget(self.info_dock)
        self.bounds_panel.setStyleSheet('QWidget#boundsPanel { background: #ffffff; }')
        self.bounds_panel.setObjectName('boundsPanel')
        bounds_layout = QVBoxLayout(self.bounds_panel)
        bounds_layout.setContentsMargins(10, 10, 10, 10)
        bounds_layout.setSpacing(10)
        self.bound_heading = QLabel(self.bounds_panel)
        self.bound_heading.setStyleSheet('color: #111111; font-weight: 600;')
        bounds_layout.addWidget(self.bound_heading)
        self.bound_labels = {}
        self.bound_solve_buttons = {}
        self.bound_color_buttons = {}
        for problem in BOUND_PROBLEMS:
            line = QWidget(self.bounds_panel)
            line_layout = QHBoxLayout(line)
            line_layout.setContentsMargins(0, 3, 0, 3)
            label = QLabel(line)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.setStyleSheet('color: #111111;')
            line_layout.addWidget(label, 1)
            controls = QVBoxLayout()
            controls.setSpacing(4)
            solve = QToolButton(line)
            solve.setText('Compute')
            solve.setToolTip('Search for up to one minute. You can stop earlier.')
            solve.setStyleSheet('QToolButton { color: #111111; background: #f5f6f7; '
                                'border: 1px solid #b8bec4; border-radius: 4px; padding: 4px; } '
                                'QToolButton:disabled { color: #777777; border-color: #d5d5d5; }')
            solve.clicked.connect(lambda checked=False, key=problem: self.bound_button_clicked(key))
            controls.addWidget(solve)
            color = QToolButton(line)
            color.setText('Show')
            color.setToolTip('Show the solution on the canvas. Undo restores the previous drawing.')
            color.setStyleSheet(solve.styleSheet())
            color.clicked.connect(lambda checked=False, key=problem: self.show_bound_solution(key))
            color.hide()
            controls.addWidget(color)
            line_layout.addLayout(controls)
            bounds_layout.addWidget(line)
            self.bound_labels[problem] = label
            self.bound_solve_buttons[problem] = solve
            self.bound_color_buttons[problem] = color
        self.bound_note = QLabel(self.bounds_panel)
        self.bound_note.setWordWrap(True)
        self.bound_note.setStyleSheet('color: #555c63;')
        bounds_layout.addWidget(self.bound_note)
        bounds_layout.addStretch()
        self.bounds_scroll = QScrollArea(self.info_dock)
        self.bounds_scroll.setWidgetResizable(True)
        self.bounds_scroll.setFrameShape(QFrame.NoFrame)
        self.bounds_scroll.setStyleSheet('QScrollArea { background: #ffffff; border: 0; }')
        self.bounds_scroll.setWidget(self.bounds_panel)
        self.info_stack = QStackedWidget(self.info_dock)
        self.info_stack.addWidget(self.info_text)
        self.info_stack.addWidget(self.bounds_scroll)
        info_container = QWidget(self.info_dock)
        info_container.setStyleSheet('background: #ffffff;')
        info_layout = QVBoxLayout(info_container)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(0)
        info_layout.addWidget(self.info_stack, 1)
        self.info_outdated_bar = QWidget(info_container)
        refresh_layout = QHBoxLayout(self.info_outdated_bar)
        refresh_layout.setContentsMargins(10, 5, 10, 8)
        refresh_label = QLabel('Outdated — graph or selection changed', self.info_outdated_bar)
        refresh_label.setStyleSheet('color: #555c63;')
        refresh_layout.addWidget(refresh_label, 1)
        self.info_refresh_button = QToolButton(self.info_outdated_bar)
        self.info_refresh_button.setText('⟳')
        self.info_refresh_button.setToolTip('Refresh these metrics')
        self.info_refresh_button.setStyleSheet('QToolButton { color: #111111; background: #f5f6f7; '
                                              'border: 1px solid #b8bec4; border-radius: 4px; '
                                              'font-size: 18px; min-width: 24px; min-height: 24px; }')
        self.info_refresh_button.clicked.connect(self.refresh_graph_info)
        refresh_layout.addWidget(self.info_refresh_button)
        info_layout.addWidget(self.info_outdated_bar)
        self.info_outdated_bar.hide()
        self.info_dock.setWidget(info_container)
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
            between vertices to add or remove an edge. Alt-click inside a region to add a vertex there.
            Secondary-click a vertex to delete it or press Delete.</p>
            <p><b>Select:</b> Click an object, drag a rectangle in empty space,
            or secondary-drag there for a lasso.</p>
            <p><b>Move and navigate:</b> Drag one or multiple vertices to move them.
            Press Space to fit the graph in view. Alt+drag to pan. Mouse wheel to zoom.</p>
            <p><b>Edit:</b> Double-click a vertex or edge to edit its label and style. Basic styles can be edited in Appearances. Use S to change style.
            Use Edition or Structure for graph operations.</p>
            <p><small>Secondary-click means right-click, or Ctrl-click on a
            trackpad.</small></p>
            <h3>Essential menus</h3>
            <p><b>File</b> saves, loads and exports.<br>
            <b>Edition</b> has undo, selection and transformations.<br>
            <b>Structure</b> has graph operations, graph types, and regions.<br>
            <b>Layout</b> has Fit graph, manual, automatic, and guided positioning.<br>
            <b>Appearances</b> has labels, styles and curves.<br>
            <b>Standard graphs</b> inserts familiar graph families.<br>
            <b>Metrics</b> computes graph measures and tests morphisms and minors.<br>
            <b>Custom</b> shows functions added by your Python script.</p>
            <a name="custom-buttons"></a><h3>Add your own functions</h3>
            <p>The downloaded app does not load personal Python code. To add custom
            functions, install the library and launch it from your own script.
            See <a href="https://github.com/CyrilPujol/graph-builder#custom-python-functions">the Custom Python functions guide</a> for setup and examples.</p>
            <h3>About</h3>
            <p>Created by Cyril Pujol.<br>
            <a href="https://github.com/CyrilPujol/graph-builder">GitHub</a> ·
            <a href="https://www.irif.fr/~cpujol/">Webpage</a></p>
        ''')
        help_content = QWidget(self.help_dock)
        help_layout = QVBoxLayout(help_content)
        help_layout.setContentsMargins(0, 0, 0, 0)
        help_layout.setSpacing(0)
        self.replay_tutorial_button = QToolButton(help_content)
        self.replay_tutorial_button.setText('↻  Replay tutorial…')
        self.replay_tutorial_button.setToolTip('Start the quick tour again with its example graph')
        self.replay_tutorial_button.setStyleSheet('''
            QToolButton { color: #176f6b; background: #edf6f4; border: 0;
                          text-align: left; padding: 10px 12px; font-weight: 600; }
            QToolButton:hover { background: #dcefeb; }
        ''')
        self.replay_tutorial_button.clicked.connect(self.replay_tutorial)
        help_layout.addWidget(self.replay_tutorial_button)
        help_layout.addWidget(self.help_text, 1)
        self.help_dock.setWidget(help_content)
        self.addDockWidget(Qt.RightDockWidgetArea, self.help_dock)
        self.help_dock.hide()
        self.tutorial_dock = QDockWidget('Getting started', self)
        self.tutorial_dock.setAllowedAreas(Qt.RightDockWidgetArea)
        self.tutorial_dock.setMinimumWidth(300)
        self.tutorial_panel = TutorialPanel(self.tutorial_dock)
        self.tutorial_panel.finished.connect(self.finish_tutorial)
        self.tutorial_dock.setWidget(self.tutorial_panel)
        self.addDockWidget(Qt.RightDockWidgetArea, self.tutorial_dock)
        self.tutorial_dock.hide()
        self.tutorial_active = False
        self.picture_dock = QDockWidget('Picture preview', self)
        self.picture_dock.setAllowedAreas(Qt.RightDockWidgetArea)
        self.picture_dock.setMinimumWidth(340)
        self.picture_preview = PicturePreview(self.picture_dock)
        self.picture_preview.save_requested.connect(self._save_picture_preview)
        self.picture_dock.setWidget(self.picture_preview)
        self.addDockWidget(Qt.RightDockWidgetArea, self.picture_dock)
        self.picture_dock.hide()
        self.add_curve_action.triggered.connect(
            lambda checked=False: self._observe_tutorial('curve_edge'))
        tabs.tabBarClicked.connect(self._observe_tutorial_menu)
        self.help_button.clicked.connect(self.toggle_help)
        # Actions in inactive tabs still need their keyboard shortcuts active.
        for action in (self.new_action, self.open_action, self.save_action, self.save_as_action,
                       self.close_action, self.undo_action, self.redo_action, self.copy_action,
                       self.paste_action, self.delete_action, self.rename_action,
                       self.deselect_action, self.select_all_action,
                       self.add_curve_action, self.previous_type_action,
                       self.next_type_action, self.cut_action, self.full_join_action,
                       self.fit_action,
                       self.labels_action,
                       *(item for _, item in self.extension_actions)):
            if not action.shortcut().isEmpty():
                self.addAction(action)
        self._sync_controls()

    def toggle_help(self):
        if self.help_dock.isVisible():
            self.help_dock.hide()
            if self.tutorial_active:
                self.tutorial_dock.show()
        else:
            self.info_dock.hide()
            self.tutorial_dock.hide()
            self.picture_dock.hide()
            self.help_dock.show()

    def show_custom_help(self):
        self.info_dock.hide()
        self.tutorial_dock.hide()
        self.picture_dock.hide()
        self.help_dock.show()
        self.help_text.scrollToAnchor('custom-buttons')

    def offer_first_run_tutorial(self, settings):
        """Offer the tour once for the desktop app, never for library calls."""
        if settings.value('tutorial/offered', False, type=bool):
            return False
        settings.setValue('tutorial/offered', True)
        self.start_tutorial()
        return True

    def start_tutorial(self):
        self.vertex_color = 0
        self.edge_color = 0
        self.graph = tutorial_graph()
        self.path = None
        self.selection.clear()
        self.rebuild_scene()
        self._reset_history()
        self.tutorial_panel.restart()
        self.tutorial_active = True
        self.info_dock.hide()
        self.help_dock.hide()
        self.picture_dock.hide()
        self.tutorial_dock.show()
        QTimer.singleShot(0, self.fit_graph)

    def finish_tutorial(self):
        self.tutorial_active = False
        self.tutorial_panel.stop()
        self.tutorial_dock.hide()

    def _observe_tutorial_menu(self, index):
        self._observe_tutorial('menu_any')

    def replay_tutorial(self):
        if self.graph.number_of_nodes() == 0:
            self.start_tutorial()
            return
        answer = QMessageBox.question(
            self, 'Replay tutorial',
            'Replay the tutorial with its example graph? This replaces the current graph.',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes or not self._may_replace_document():
            return
        self.start_tutorial()

    def _sync_controls(self):
        self.multiedges_action.setChecked(self.graph.is_multigraph())
        self.loops_action.setChecked(bool(self.graph.graph.get('loops', False)))
        self.labels_action.setChecked(labels_visible(self.graph))
        self.directed_action.setChecked(self.is_directed)
        self.vertex_colors_label.setText(f'  Vertex styles: {self.graph.graph.get("num_vertex_colors", 4)} ')
        self.edge_colors_label.setText(f'  Edge styles: {self.graph.graph.get("num_edge_colors", 2)} ')
        self.grid_unit_label.setText('  Grid density: ')
        self.radial_label.setText(f'  Radials: {self.radial_divisions} ')
        self.grid_unit_label_action.setVisible(self.grid_mode in ('square', 'triangular', 'radial'))
        self.radial_label_action.setVisible(self.grid_mode == 'radial')
        self.grid_unit_control_action.setVisible(self.grid_mode in ('square', 'triangular', 'radial'))
        self.radial_control_action.setVisible(self.grid_mode == 'radial')
        self.axis_snap_action.setVisible(self.grid_mode == 'axis')
        for action in self.automatic_actions:
            action.setVisible(self.grid_mode == 'automatic')
        self.grid_options_separator.setVisible(self.grid_mode in
                                               ('automatic', 'axis', 'square', 'triangular', 'radial'))

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
        return self._insert_generated_graph(generated)

    def _insert_generated_graph(self, generated, *, arrange_parallel=False):
        """Add a positioned component without replacing the current document."""
        positions = generated.positions
        xs = [point[0] for point in positions.values()]
        ys = [point[1] for point in positions.values()]
        midpoint = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
        width, height = max(xs) - min(xs), max(ys) - min(ys)
        viewport = self.view.viewport()
        pixels_per_unit = min(85.0, .75 * viewport.width() / max(width, 1),
                              .75 * viewport.height() / max(height, 1))
        if arrange_parallel:
            # A small product need not fill most of the viewport. Keep its
            # nearest distinct vertices at a comfortable screen distance,
            # while the viewport limit above still handles large products.
            points = tuple(positions.values())
            nearest = min((hypot(x1 - x2, y1 - y2)
                           for index, (x1, y1) in enumerate(points)
                           for x2, y2 in points[index + 1:]
                           if (x1, y1) != (x2, y2)), default=None)
            if nearest is not None:
                pixels_per_unit = min(pixels_per_unit, 58.0 / nearest)
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
            if arrange_parallel and self.graph.is_multigraph():
                flip_edge(self.graph, first, second, self.edge_color)
                continue
            self.graph.add_edge(first, second, col=self.edge_color, label='')
            if not generated.graph.is_directed() and first != second:
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
                self.selection.edges.add(EdgeRef(item.source, item.target, self.is_directed, item.key))
            elif isinstance(item, CurveHandle):
                if isinstance(item, RegionCurveHandle):
                    self.selection.regions.add(item.region_id)
                else:
                    self.selection.edges.add(EdgeRef(item.source, item.target, self.is_directed, item.key))
            elif isinstance(item, RegionItem):
                self.selection.regions.add(item.region_id)
        self._update_curve_handles()
        self._update_region_curve_handles()
        self._update_region_boundaries()
        if self._info_selection_nodes is not None and selected_vertices(self.selection) != self._info_selection_nodes:
            self._invalidate_info()
        self.update_actions()

    def _update_curve_handles(self):
        wanted = {(edge.source, edge.target, index, edge.key)
                  for edge in self.selection.edges
                  for index, _ in enumerate(_edge_curve_points(self.graph, edge.source, edge.target, edge.key))}
        present = {(handle.source, handle.target, handle.index, handle.key) for handle in self.curve_handles}
        if wanted == present:
            return
        self._updating_handles = True
        for handle in self.curve_handles:
            self.scene.removeItem(handle)
        self.curve_handles.clear()
        for edge in self.selection.edges:
            for index, position in enumerate(_edge_curve_points(self.graph, edge.source, edge.target, edge.key)):
                handle = CurveHandle(self, edge.source, edge.target, index, position, edge.key)
                self.scene.addItem(handle)
                self.curve_handles.append(handle)
        self._updating_handles = False

    def _update_region_boundaries(self):
        selected = self.selection.regions
        for item in self.region_boundary_items:
            item.setVisible(item.region_id in selected)

    def _update_region_curve_handles(self):
        wanted = set()
        for identifier in self.selection.regions:
            region = region_by_id(self.graph, identifier)
            if region is None:
                continue
            for segment_index, segment in enumerate(region.get('segments', [])):
                if segment['kind'] == 'edge':
                    source = segment.get('edge_source', segment['source'])
                    target = segment.get('edge_target', segment['target'])
                    count = len(_edge_curve_points(self.graph, source, target, segment.get('key')))
                else:
                    count = len(segment.get('controls', []))
                wanted.update((identifier, segment_index, index) for index in range(count))
        present = {(handle.region_id, handle.segment_index, handle.index)
                   for handle in self.region_curve_handles}
        if wanted == present:
            for handle in self.region_curve_handles:
                handle.sync_position()
            return
        self._updating_handles = True
        for handle in self.region_curve_handles:
            self.scene.removeItem(handle)
        self.region_curve_handles.clear()
        for identifier, segment_index, index in sorted(wanted):
            handle = RegionCurveHandle(self, identifier, segment_index, index, (0, 0))
            handle.sync_position()
            self.scene.addItem(handle)
            self.region_curve_handles.append(handle)
        self._updating_handles = False

    def rebuild_scene(self, selection=None):
        if selection is not None:
            self.selection = selection
        prune_regions(self.graph)
        self.selection.prune(self.graph)
        if not self._full_join_first.issubset(self.graph):
            self._clear_full_join()
        if not self._morphism_first.issubset(self.graph):
            self._clear_morphism(cancel_process=True)
        if not self._minor_first.issubset(self.graph):
            self._clear_minor(cancel_process=True)
        if not self._product_first.issubset(self.graph):
            self._clear_product()
        self._rebuilding = True
        self.scene.set_edge_hover_target(None)
        self.scene.clear_fusion_animation()
        self.scene.set_axis_snap_guides(())
        self.scene.clear()
        self.scene.region_preview_item = None
        self.node_items.clear()
        self.edge_items.clear()
        self.region_items.clear()
        self.region_boundary_items.clear()
        self.curve_handles.clear()
        self.region_curve_handles.clear()
        for region in regions(self.graph):
            item = RegionItem(self, region)
            self.region_items[region['id']] = item
            self.scene.addItem(item)
        for node in self.graph:
            item = NodeItem(self, node)
            self.node_items[node] = item
            self.scene.addItem(item)
        for source, target, key, _ in visible_edges(self.graph):
            item = EdgeItem(self, source, target, key)
            self.edge_items[self.edge_key(source, target, key)] = item
            self.scene.addItem(item)
        for region in regions(self.graph):
            for index, _ in enumerate(region.get('segments', [])):
                boundary = RegionBoundaryItem(self, region['id'], index)
                self.region_boundary_items.append(boundary)
                self.scene.addItem(boundary)
        for node in self.selection.nodes:
            self.node_items[node].setSelected(True)
        for edge in self.selection.edges:
            item = self.edge_items.get(self.edge_key(edge.source, edge.target, edge.key))
            if item:
                item.setSelected(True)
        for identifier in self.selection.regions:
            item = self.region_items.get(identifier)
            if item:
                item.setSelected(True)
        self._rebuilding = False
        self._update_region_boundaries()
        self._update_curve_handles()
        self._update_region_curve_handles()
        self.scene.update()
        self._sync_controls()
        self.update_actions()

    def edge_key(self, source, target, key=None):
        pair = (source, target) if self.is_directed else frozenset((source, target))
        return (pair, key) if self.graph.is_multigraph() else pair

    def refresh_adjacent_edges(self, node):
        for edge in self.edge_items.values():
            if node in (edge.source, edge.target):
                edge.refresh()

    def refresh_regions(self):
        for item in self.region_items.values():
            item.refresh()
        for item in self.region_boundary_items:
            item.refresh()
        for handle in self.region_curve_handles:
            handle.sync_position()
        for handle in self.curve_handles:
            handle.sync_position()

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
            attributes['col'] = color
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
        before_types = {node: source_graph.nodes[node].get('col', 0) for node in nodes}
        self.graph = source_graph
        if result == PropertiesDialog.Accepted:
            self._write_node_properties(self.graph, dialog, nodes)
        self.rebuild_scene()
        if result == PropertiesDialog.Accepted:
            self.commit_change()
            if any(self.graph.nodes[node].get('col', 0) != before_types[node] or
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
            edge_data(graph, first, second, edge_id)['col'] = color
            if graph.graph.get('graph_type') == 'graph' and has_edge(graph, second, first, edge_id):
                edge_data(graph, second, first, edge_id)['col'] = color
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

    def delete_selection(self):
        handles = [item for item in self.scene.selectedItems() if isinstance(item, CurveHandle)]
        if handles:
            for handle in sorted(handles, key=lambda item: item.index, reverse=True):
                if isinstance(handle, RegionCurveHandle):
                    region = region_by_id(self.graph, handle.region_id)
                    if region is None:
                        continue
                    segment = region['segments'][handle.segment_index]
                    if segment['kind'] == 'line':
                        points = line_controls(self.graph, segment)
                        if handle.index < len(points):
                            points.pop(handle.index)
                            set_line_controls(self.graph, segment, points)
                            update_region(self.graph, handle.region_id,
                                          {'segments': region['segments']})
                        continue
                    source = segment.get('edge_source', segment['source'])
                    target = segment.get('edge_target', segment['target'])
                    key = segment.get('key')
                else:
                    source, target, key = handle.source, handle.target, handle.key
                points = _edge_curve_points(self.graph, source, target, key)
                if handle.index < len(points):
                    points.pop(handle.index)
                    _set_edge_curve_points(self.graph, source, target, points, key)
        else:
            if self.selection.regions:
                remove_regions(self.graph, self.selection.regions)
            self.graph.remove_nodes_from(self.selection.nodes)
            for edge in self.selection.edges:
                remove_edge(self.graph, edge.source, edge.target, edge.key)
                if not edge.directed:
                    remove_edge(self.graph, edge.target, edge.source, edge.key)
            self.selection.clear()
        self.rebuild_scene()
        self.commit_change()

    def add_curve_point(self):
        first = None
        for edge in list(self.selection.edges):
            item = self.edge_items.get(self.edge_key(edge.source, edge.target, edge.key))
            if item is None:
                continue
            points = _edge_curve_points(self.graph, edge.source, edge.target, edge.key)
            position, index = self._next_curve_point(item, points)
            points.insert(index, position.toTuple())
            _set_edge_curve_points(self.graph, edge.source, edge.target, points, edge.key)
            first = first or (edge.source, edge.target, index, edge.key)
        self.rebuild_scene()
        if len(self.selection.edges) == 1 and first is not None:
            self._select_curve_handle(*first)
        self.commit_change()
        if first is not None:
            self._observe_tutorial('curve_edge')

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

    def add_curve_point_at(self, source, target, position, commit=True, snap_to_path=False, key=None):
        points = _edge_curve_points(self.graph, source, target, key)
        item = self.edge_items[self.edge_key(source, target, key)]
        projected, _ = item.closest_path_position(position)
        index = self._curve_insertion_index(item, points, position)
        points.insert(index, (projected if snap_to_path else position).toTuple())
        _set_edge_curve_points(self.graph, source, target, points, key)
        self.rebuild_scene()
        handle = self._select_curve_handle(source, target, index, key)
        if commit:
            self.commit_change()
        return handle

    def delete_curve_point(self, source, target, index, key=None):
        points = _edge_curve_points(self.graph, source, target, key)
        if not 0 <= index < len(points):
            return
        points.pop(index)
        _set_edge_curve_points(self.graph, source, target, points, key)
        self.rebuild_scene()
        self.commit_change()

    def delete_region_curve_point(self, identifier, segment_index, index):
        region = region_by_id(self.graph, identifier)
        if region is None or segment_index >= len(region.get('segments', [])):
            return
        segment = region['segments'][segment_index]
        if segment['kind'] == 'edge':
            source = segment.get('edge_source', segment['source'])
            target = segment.get('edge_target', segment['target'])
            key = segment.get('key')
            points = _edge_curve_points(self.graph, source, target, key)
            if index >= len(points):
                return
            points.pop(index)
            _set_edge_curve_points(self.graph, source, target, points, key)
        else:
            points = line_controls(self.graph, segment)
            if index >= len(points):
                return
            points.pop(index)
            set_line_controls(self.graph, segment, points)
            update_region(self.graph, identifier, {'segments': region['segments']})
        self.rebuild_scene()
        self.commit_change()

    def _select_curve_handle(self, source, target, index, key=None):
        for handle in self.curve_handles:
            if handle.source == source and handle.target == target and handle.index == index and handle.key == key:
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
                custom_look = has_custom_look(data)
                data['col'] = (data.get('col', 0) + delta) % self.graph.graph['num_vertex_colors']
                self.rebuild_scene()
                self.commit_change()
                if self.graph.graph['num_vertex_colors'] > 1:
                    self._observe_tutorial('change_appearance')
                if custom_look:
                    self.report('Style changed, but this vertex has a custom look.', 4)
                return
            self.vertex_color = (self.vertex_color + delta) % self.graph.graph['num_vertex_colors']
            self.report(f'New vertex style: {self.vertex_color}', 2)
            return
        custom_look = (self.graph.graph['num_vertex_colors'] > 1 and any(
            has_custom_look(self.graph.nodes[node]) for node in self.selection.nodes)) or (
            self.graph.graph['num_edge_colors'] > 1 and any(
                has_custom_look(edge_data(self.graph, edge.source, edge.target, edge.key))
                for edge in self.selection.edges))
        changed_vertex_style = bool(self.selection.nodes and self.graph.graph['num_vertex_colors'] > 1)
        for node in self.selection.nodes:
            self.graph.nodes[node]['col'] = (self.graph.nodes[node].get('col', 0) + delta) % self.graph.graph['num_vertex_colors']
        for edge in self.selection.edges:
            source, target, key = edge.source, edge.target, edge.key
            color = (edge_data(self.graph, source, target, key).get('col', 0) + delta) % self.graph.graph['num_edge_colors']
            edge_data(self.graph, source, target, key)['col'] = color
            if not edge.directed and has_edge(self.graph, target, source, key):
                edge_data(self.graph, target, source, key)['col'] = color
        self.rebuild_scene()
        self.commit_change()
        if changed_vertex_style:
            self._observe_tutorial('change_appearance')
        if custom_look:
            self.report('Style changed, but some selected objects have custom looks.', 4)

    def cut_edges(self):
        cut_edges_to_rest(self.graph, self.selection.nodes)
        self.rebuild_scene()
        self.commit_change()

    def _cancel_region_path(self):
        self.region_path = None
        self.make_region_action.setChecked(False)
        self.scene.set_region_preview(())
        self.scene.update()

    def make_region(self, checked=False):
        """Fill an edge cycle, a vertex hull, or start an interactive boundary."""
        if self.region_path is not None:
            self._cancel_region_path()
            self.report('Region path cancelled.', 3)
            return
        if self.selection.edges:
            segments = cycle_from_edges(self.graph, self.selection.edges)
            if segments is not None:
                identifier = add_region(self.graph, mode='path', segments=segments)
                self.make_region_action.setChecked(False)
                self.selection = SelectionState(set(), set(), {identifier})
                self.rebuild_scene()
                self.commit_change()
                self.report('Region created from the selected edges.', 4)
                return
        elif self.selection.nodes:
            hull = hull_region_nodes(self.graph, self.selection.nodes)
            if hull is not None:
                nodes, margin = hull
                identifier = add_region(self.graph, mode='hull', nodes=nodes, margin=margin)
                self.make_region_action.setChecked(False)
                self.selection = SelectionState(set(), set(), {identifier})
                self.rebuild_scene()
                self.commit_change()
                self.report('Region created around the selected vertices.', 4)
                return
        self.scene.clearSelection()
        self.region_path = {'start': None, 'end': None, 'segments': []}
        self.make_region_action.setChecked(True)
        self.report('Click vertices or adjacent edges to trace a boundary. Click the starting vertex to close it. Esc cancels.', 8)

    def region_path_click(self, item):
        """Advance an interactive region path by a vertex or adjacent edge."""
        if self.region_path is None:
            return
        path = self.region_path
        if isinstance(item, NodeItem):
            node = item.node
            if path['start'] is None:
                path['start'] = path['end'] = node
                self.scene.set_region_preview((self.graph.nodes[node]['position'],))
                self.report('Boundary started. Click another vertex or an adjacent edge.', 5)
                return
            if node == path['end']:
                return
            candidate = path['segments'] + [path_segment(path['end'], node)]
            if node == path['start']:
                self._close_region_path(candidate)
                return
            path['segments'] = candidate
            path['end'] = node
        elif isinstance(item, EdgeItem):
            first, second = item.source, item.target
            if path['start'] is None:
                path['start'], path['end'] = first, second
                path['segments'].append(path_segment(first, second,
                    EdgeRef(first, second, self.is_directed, item.key)))
                if first == second:
                    self._close_region_path(path['segments'])
                    return
            else:
                current = path['end']
                if current not in (first, second):
                    self.report('Choose an edge touching the end of the boundary.', 4)
                    return
                following = second if current == first else first
                candidate = path['segments'] + [path_segment(current, following,
                    EdgeRef(first, second, self.is_directed, item.key))]
                if following == path['start']:
                    self._close_region_path(candidate)
                    return
                path['segments'] = candidate
                path['end'] = following
        else:
            self.report('Click a vertex or an edge adjacent to the current path.', 4)
            return
        self.scene.set_region_preview(region_points(
            self.graph, {'mode': 'path', 'segments': path['segments']}))
        self.scene.update()

    def _close_region_path(self, segments):
        if not valid_boundary(self.graph, segments):
            self.report('The boundary needs to enclose a visible area.', 4)
            return
        identifier = add_region(self.graph, mode='path', segments=segments)
        self._cancel_region_path()
        self.selection = SelectionState(set(), set(), {identifier})
        self.rebuild_scene()
        self.commit_change()
        self.report('Region created. Double-click it to edit its look.', 5)

    def _clear_full_join(self):
        previous = self._full_join_first
        self._full_join_first = frozenset()
        if previous:
            self.statusBar().clearMessage()
        self.full_join_action.setChecked(False)
        self.full_join_action.setToolTip(
            'Full join — J\nConnect every vertex in a first set to every vertex in a second set.')
        for node in previous:
            item = self.node_items.get(node)
            if item is not None and item.scene() is self.scene:
                item.update()

    def _clear_product(self):
        previous = self._product_first
        self._product_first = frozenset()
        self._product_kind = None
        self.product_button.setChecked(False)
        self.product_button.setText('Product')
        self.product_button.setPopupMode(QToolButton.InstantPopup)
        self.product_button.setToolTip('Choose a product of two selected vertex sets.')
        if previous:
            self.statusBar().clearMessage()
        for node in previous:
            item = self.node_items.get(node)
            if item is not None and item.scene() is self.scene:
                item.update()

    def _product_button_clicked(self):
        if self._product_first:
            self.product_button.setChecked(True)
            self.product_selection()
        else:
            self.product_button.setChecked(False)
            self.product_button.showMenu()

    def start_product(self, kind):
        if self._product_first and self._product_kind == kind:
            self.product_selection()
            return
        if self._product_first:
            self._product_kind = kind
            self.product_button.setText(f'{PRODUCTS[kind][0]} ✓')
            self.product_button.setPopupMode(QToolButton.DelayedPopup)
            self.product_button.setToolTip(
                f'Select the second factor, then click here or press Enter to make the {kind} product.')
            self.report(f'Switched to {PRODUCTS[kind][0]} product. Select the second factor.', 5)
            return
        selected = set(self.selection.nodes)
        if not selected:
            self.report('Select the vertices of the first factor.', 4)
            return
        if self._full_join_first:
            self._clear_full_join()
        if self._morphism_first or self._morphism_process is not None:
            self._clear_morphism(cancel_process=True)
        if self._minor_first or self._minor_process is not None:
            self._clear_minor(cancel_process=True)
        self._product_first = frozenset(selected)
        self._product_kind = kind
        self.product_button.setChecked(True)
        self.product_button.setText(f'{PRODUCTS[kind][0]} ✓')
        self.product_button.setPopupMode(QToolButton.DelayedPopup)
        self.product_button.setToolTip(
            f'Select the second factor, then click here or press Enter to make the {kind} product.')
        self.scene.clearSelection()
        for node in self._product_first:
            self.node_items[node].update()
        message = 'First factor marked. Select the second factor, then click the highlighted button or press Enter.'
        self.report(message, 8)
        self.statusBar().showMessage(message, 0)
        self.update_actions()

    def product_selection(self, checked=False):
        if not self._product_first:
            self._product_button_clicked()
            return
        second = set(self.selection.nodes)
        if not second:
            self.report('Select at least one vertex for the second factor. Esc cancels.', 5)
            return
        try:
            generated = generate_product(self.graph, self._product_first, second,
                                         self._product_kind)
        except ValueError as error:
            self.report(str(error), 5)
            return
        kind = self._product_kind
        self._clear_product()
        new_nodes = self._insert_generated_graph(generated, arrange_parallel=True)
        self.report(f'Added the {kind} product with {len(new_nodes)} vertices.', 5)

    def full_join_selection(self, checked=False):
        """Capture one vertex set, then join it to the next selected set."""
        second = set(self.selection.nodes)
        if not self._full_join_first:
            if self._product_first:
                self._clear_product()
            if self._morphism_first or self._morphism_process is not None:
                self._clear_morphism(cancel_process=True)
            if self._minor_first or self._minor_process is not None:
                self._clear_minor(cancel_process=True)
            if not second:
                self.full_join_action.setChecked(False)
                self.report('Select at least one vertex for the first set.', 4)
                return
            self._full_join_first = frozenset(second)
            self.full_join_action.setChecked(True)
            self.full_join_action.setToolTip(
                'Full join — J\nSelect the second vertex set, then click again. Esc cancels.')
            self.scene.clearSelection()
            for node in self._full_join_first:
                self.node_items[node].update()
            message = 'First set marked. Select a second set, then click Full join again. Esc cancels.'
            self.report(message, 8)
            self.statusBar().showMessage(message, 0)
            self.update_actions()
            return
        if not second:
            self.full_join_action.setChecked(True)
            self.report('Select at least one vertex for the second set. Esc cancels.', 5)
            return
        first = self._full_join_first
        self._clear_full_join()
        added = full_join(self.graph, first, second, self.edge_color)
        self.rebuild_scene()
        self.commit_change()
        self.report(f'Full join added {added} edge{"" if added == 1 else "s"}.', 5)
        self.view.viewport().repaint()
        QTimer.singleShot(0, self.view.viewport().update)

    def _clear_morphism(self, cancel_process=False):
        if cancel_process and self._morphism_process is not None:
            process = self._morphism_process
            self._morphism_process = None
            process.kill()
            process.waitForFinished(100)
            process._worker_dir.cleanup()
            process.deleteLater()
        previous = self._morphism_first
        self._morphism_first = frozenset()
        if previous:
            self.statusBar().clearMessage()
        self.morphism_action.setChecked(False)
        self.morphism_action.setToolTip(
            'Find a homomorphism from a first selected set to a second selected set.')
        for node in previous:
            item = self.node_items.get(node)
            if item is not None and item.scene() is self.scene:
                item.update()

    def _clear_minor(self, cancel_process=False):
        if cancel_process and self._minor_process is not None:
            process = self._minor_process
            self._minor_process = None
            process.kill()
            process.waitForFinished(100)
            process._worker_dir.cleanup()
            process.deleteLater()
        previous = self._minor_first
        self._minor_first = frozenset()
        if previous:
            self.statusBar().clearMessage()
        self.minor_action.setChecked(False)
        self.minor_action.setToolTip(
            'Test whether a first selected graph contains a second as an undirected minor.')
        for node in previous:
            item = self.node_items.get(node)
            if item is not None and item.scene() is self.scene:
                item.update()

    def morphism_selection(self, checked=False):
        """Capture induced G and H, then solve without blocking the canvas."""
        if self._morphism_process is not None:
            self._clear_morphism(cancel_process=True)
            self.report('Morphism search stopped.', 4)
            self.update_actions()
            return
        selected = set(self.selection.nodes)
        if not self._morphism_first:
            if self._product_first:
                self._clear_product()
            if self._full_join_first:
                self._clear_full_join()
            if self._minor_first or self._minor_process is not None:
                self._clear_minor(cancel_process=True)
            if not selected:
                self.morphism_action.setChecked(False)
                self.report('Select at least one vertex for G.', 4)
                return
            self._morphism_first = frozenset(selected)
            self.morphism_action.setChecked(True)
            self.morphism_action.setToolTip(
                'Select the vertices of H, then click Morphism again. Esc cancels.')
            self.scene.clearSelection()
            for node in self._morphism_first:
                self.node_items[node].update()
            message = 'G marked. Select vertices for H, then click Morphism again. Esc cancels.'
            self.report(message, 8)
            self.statusBar().showMessage(message, 0)
            self.update_actions()
            return
        if not selected:
            self.morphism_action.setChecked(True)
            self.report('Select at least one vertex for H. Esc cancels.', 5)
            return
        self.morphism_action.setChecked(True)
        self.morphism_action.setToolTip('Computing a morphism. Click again or press Esc to stop.')
        self._start_morphism_search(set(self._morphism_first), selected)

    def _start_morphism_search(self, sources, targets):
        graph = public_graph(self.graph)
        topology = topology_payload(graph)
        payload = topology | {'source_nodes': sorted(sources, key=str),
                              'target_nodes': sorted(targets, key=str)}
        process = QProcess(self)
        worker_dir = tempfile.TemporaryDirectory(prefix='graph-builder-morphism-')
        process._worker_dir = worker_dir
        input_path = Path(worker_dir.name) / 'input.json'
        process._result_path = Path(worker_dir.name) / 'result.json'
        input_path.write_text(json.dumps(payload), encoding='utf-8')
        self._morphism_process = process
        process.finished.connect(lambda code, status: self._finish_morphism(
            process, code, sources, targets, topology))
        process.errorOccurred.connect(lambda error: self._morphism_worker_error(process, error))
        kind = 'Morphism'
        arguments = (['--graph-info-worker', kind, str(input_path), str(process._result_path)]
                     if getattr(sys, 'frozen', False) else
                     ['-m', 'graph_builder_core.info', '--worker', kind,
                      str(input_path), str(process._result_path)])
        process.start(sys.executable, arguments)
        QTimer.singleShot(OPTIMIZATION_TIMEOUT_MS, lambda: self._timeout_morphism(process))
        self.report('Computing a morphism. Click Morphism again to stop.', 6)
        self.update_actions()

    def minor_selection(self, checked=False):
        """Capture host G and pattern H, then test their undirected minor relation."""
        if self._minor_process is not None:
            self._clear_minor(cancel_process=True)
            self.report('Minor search stopped.', 4)
            self.update_actions()
            return
        selected = set(self.selection.nodes)
        if not self._minor_first:
            if self._product_first:
                self._clear_product()
            if self._full_join_first:
                self._clear_full_join()
            if self._morphism_first or self._morphism_process is not None:
                self._clear_morphism(cancel_process=True)
            if not selected:
                self.minor_action.setChecked(False)
                self.report('Select the host graph first.', 4)
                return
            self._minor_first = frozenset(selected)
            self.minor_action.setChecked(True)
            self.scene.clearSelection()
            for node in self._minor_first:
                self.node_items[node].update()
            message = 'Host marked. Select a pattern graph, then click Minor again. Esc cancels.'
            self.report(message, 8)
            self.statusBar().showMessage(message, 0)
            self.update_actions()
            return
        if not selected:
            self.minor_action.setChecked(True)
            self.report('Select at least one vertex for the pattern.', 5)
            return
        self.minor_action.setChecked(True)
        sources, targets = set(self._minor_first), selected
        topology = topology_payload(public_graph(self.graph))
        payload = topology | {'source_nodes': sorted(sources, key=str),
                              'target_nodes': sorted(targets, key=str)}
        process = QProcess(self)
        worker_dir = tempfile.TemporaryDirectory(prefix='graph-builder-minor-')
        process._worker_dir = worker_dir
        input_path = Path(worker_dir.name) / 'input.json'
        process._result_path = Path(worker_dir.name) / 'result.json'
        input_path.write_text(json.dumps(payload), encoding='utf-8')
        self._minor_process = process
        process.finished.connect(lambda code, status: self._finish_minor(
            process, code, sources, targets, topology))
        process.errorOccurred.connect(lambda error: self._minor_worker_error(process, error))
        arguments = (['--graph-info-worker', 'Minor', str(input_path), str(process._result_path)]
                     if getattr(sys, 'frozen', False) else
                     ['-m', 'graph_builder_core.info', '--worker', 'Minor',
                      str(input_path), str(process._result_path)])
        process.start(sys.executable, arguments)
        QTimer.singleShot(OPTIMIZATION_TIMEOUT_MS, lambda: self._timeout_minor(process))
        self.report('Computing a minor. Click Minor again or press Esc to stop.', 6)
        self.update_actions()

    def _minor_worker_error(self, process, error):
        if process is self._minor_process and error == QProcess.FailedToStart:
            self._clear_minor(cancel_process=True)
            self.report('Could not start the minor solver.', 6)
            self.update_actions()

    def _timeout_minor(self, process):
        if process is self._minor_process:
            self._clear_minor(cancel_process=True)
            self.report('Minor search stopped after one minute.', 6)
            self.update_actions()

    def _finish_minor(self, process, exit_code, sources, targets, topology):
        if process is not self._minor_process:
            return
        self._minor_process = None
        try:
            result = json.loads(process._result_path.read_text(encoding='utf-8')) if exit_code == 0 else {
                'error': bytes(process.readAllStandardError()).decode('utf-8', errors='replace').strip()
                         or 'The solver stopped unexpectedly.'}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            result = {'error': 'The minor solver returned an unreadable result.'}
        process._worker_dir.cleanup()
        process.deleteLater()
        self._clear_minor()
        self.update_actions()
        if topology_payload(public_graph(self.graph)) != topology:
            self.report('The graph changed during the search. Please try Minor again.', 7)
            return
        if 'error' in result:
            self.report(result['error'], 8)
            return
        if result['status'] == 'none':
            self.report('The first graph does not contain the second as a minor.', 6)
            return
        if result['status'] == 'timeout':
            self.report('No answer within one minute. This does not disprove the minor.', 8)
            return
        from .minor import lift_minor_styles
        auto_colored = lift_minor_styles(self.graph, sources, targets, result['branch_sets'])
        self.rebuild_scene()
        self.commit_change()
        message = ('Minor found. Distinct styles show its branch sets.' if auto_colored else
                   'Minor found. Styles from the pattern show its branch sets.')
        self.report(message, 6)
        self.view.viewport().repaint()
        QTimer.singleShot(0, self.view.viewport().update)

    def _morphism_worker_error(self, process, error):
        if process is self._morphism_process and error == QProcess.FailedToStart:
            self._clear_morphism(cancel_process=True)
            self.report('Could not start the morphism solver.', 6)
            self.update_actions()

    def _timeout_morphism(self, process):
        if process is self._morphism_process:
            self._clear_morphism(cancel_process=True)
            self.report('Morphism search stopped after one minute.', 6)
            self.update_actions()

    def _finish_morphism(self, process, exit_code, sources, targets, topology):
        if process is not self._morphism_process:
            return
        self._morphism_process = None
        try:
            result = json.loads(process._result_path.read_text(encoding='utf-8')) if exit_code == 0 else {
                'error': bytes(process.readAllStandardError()).decode('utf-8', errors='replace').strip()
                         or 'The solver stopped unexpectedly.'}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            result = {'error': 'The morphism solver returned an unreadable result.'}
        process._worker_dir.cleanup()
        process.deleteLater()
        self._clear_morphism()
        self.update_actions()
        if topology_payload(public_graph(self.graph)) != topology:
            self.report('The graph changed during the search. Please try Morphism again.', 7)
            return
        if 'error' in result:
            self.report(result['error'], 8)
            return
        if result['status'] == 'none':
            self.report('No morphism from G to H exists.', 6)
            return
        if result['status'] == 'timeout':
            self.report('No answer within one minute. This does not prove that no morphism exists.', 8)
            return
        from .morphism import lift_morphism_styles
        auto_colored = lift_morphism_styles(self.graph, sources, targets, result['mapping'])
        self.rebuild_scene()
        self.commit_change()
        message = ('Morphism shown. H received distinct vertex styles.' if auto_colored else
                   'Morphism shown with styles lifted from H.')
        self.report(message, 6)
        self.view.viewport().repaint()
        QTimer.singleShot(0, self.view.viewport().update)

    def copy_selection(self):
        nodes = set(self.selection.nodes)
        for edge in self.selection.edges:
            nodes.update((edge.source, edge.target))
        for identifier in self.selection.regions:
            region = region_by_id(self.graph, identifier)
            if region is None:
                continue
            nodes.update(region.get('nodes', []))
            for segment in region.get('segments', []):
                nodes.update((segment['source'], segment['target']))
        self.clipboard = copy_graph_selection(self.graph, nodes or None)
        self.update_actions()

    def paste_selection(self):
        if self.clipboard is None:
            return
        origin = self.view.mapToScene(QPoint(0, 0))
        shifted = self.view.mapToScene(QPoint(18, -18))
        self.graph, nodes, region_ids = paste_graph_selection(
            self.graph, self.clipboard, (shifted.x() - origin.x(), shifted.y() - origin.y()),
            return_regions=True,
        )
        self.selection = SelectionState(nodes, set(), region_ids)
        self.rebuild_scene()
        self.commit_change()

    def deselect(self):
        if self.region_path is not None:
            self._cancel_region_path()
        if self._full_join_first:
            self._clear_full_join()
            self.statusBar().clearMessage()
        if self._morphism_first or self._morphism_process is not None:
            self._clear_morphism(cancel_process=True)
            self.statusBar().clearMessage()
        if self._minor_first or self._minor_process is not None:
            self._clear_minor(cancel_process=True)
            self.statusBar().clearMessage()
        if self._product_first:
            self._clear_product()
            self.statusBar().clearMessage()
        self.scene.cancel_edge_creation()
        self.scene.clearSelection()
        self.selection.clear()
        self._update_curve_handles()
        self.update_actions()

    def select_all_vertices(self):
        self.scene.clearSelection()
        for item in self.node_items.values():
            item.setSelected(True)

    def select_colors(self):
        if not self.selection.nodes:
            self.report('Select a vertex first.', 4)
            return
        indices = {int(self.graph.nodes[node].get('col', 0)) for node in self.selection.nodes}
        had_custom = any(has_custom_look(attributes)
                         for _, attributes in self.graph.nodes(data=True)
                         if int(attributes.get('col', 0)) in indices)
        self.scene.clearSelection()
        for node, item in self.node_items.items():
            if int(self.graph.nodes[node].get('col', 0)) in indices:
                item.setSelected(True)
        names = ', '.join(map(str, sorted(indices)))
        note = ' Custom looks were ignored and style indices used.' if had_custom else ''
        term = 'styles' if len(indices) > 1 else 'style'
        self.report(f'Selected vertices with {term} {names}.{note}', 5)

    def remove_coloring(self):
        changed = False
        for _, attributes in self.graph.nodes(data=True):
            changed |= int(attributes.get('col', 0)) != 0 or has_custom_look(attributes)
            use_basic_style(attributes, 0)
        for _, _, attributes in self.graph.edges(data=True):
            changed |= int(attributes.get('col', 0)) != 0 or has_custom_look(attributes)
            use_basic_style(attributes, 0)
        saved_regions = regions(self.graph)
        for region in saved_regions:
            changed |= region.get('style') != DEFAULT_REGION_STYLE
            region['style'] = dict(DEFAULT_REGION_STYLE)
        if changed:
            set_regions(self.graph, saved_regions)
            self.rebuild_scene()
            self.commit_change()
            self.report('Vertex, edge, and region coloring reset.', 4)

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

    def set_multiedges(self, checked):
        self.graph = set_multiedges(self.graph, checked)
        self.selection.clear()
        self.rebuild_scene()
        self.commit_change()

    def set_loops(self, checked):
        self.graph.graph['loops'] = bool(checked)
        if not checked:
            for u, v, key, _ in list(visible_edges(self.graph)):
                if u == v:
                    remove_edge(self.graph, u, v, key)
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
        if mode != 'automatic':
            self.live_layout_action.setChecked(False)
        self.scene.set_axis_snap_guides(())
        for action, active in ((self.grid_off_action, mode is None),
                               (self.grid_automatic_action, mode == 'automatic'),
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
        selected_count = len(self.selection.nodes) + len(self.selection.edges) + len(self.selection.regions)
        self.rename_action.setEnabled(selected_count == 1)
        self.properties_action.setEnabled(bool(selected_count))
        self.copy_style_action.setEnabled(
            (len(self.selection.nodes) == 1 and not self.selection.edges and not self.selection.regions)
            or (len(self.selection.edges) == 1 and not self.selection.nodes and not self.selection.regions)
            or (len(self.selection.regions) == 1 and not self.selection.nodes and not self.selection.edges))
        self.paste_style_action.setEnabled(bool(self.style_clipboard) and bool(
            self.selection.nodes if self.style_clipboard and self.style_clipboard[0] == 'vertex'
            else self.selection.edges if self.style_clipboard and self.style_clipboard[0] == 'edge'
            else self.selection.regions))
        self.delete_action.setEnabled(bool(selected_count or any(
            handle.isSelected() for handle in (*self.curve_handles, *self.region_curve_handles))))
        self.deselect_action.setEnabled(bool(selected_count or self._full_join_first or
                                              self._morphism_first or self._morphism_process or
                                              self._minor_first or self._minor_process or
                                              self._product_first or
                                              self.region_path is not None))
        self.add_curve_action.setEnabled(bool(self.selection.edges))
        self.cut_action.setEnabled(any((source in self.selection.nodes) != (target in self.selection.nodes)
                                       for source, target in self.graph.edges()))
        self.full_join_action.setEnabled(bool(self.selection.nodes or self._full_join_first))
        self.morphism_action.setEnabled(bool(self.selection.nodes or self._morphism_first or
                                             self._morphism_process))
        self.minor_action.setEnabled(bool(self.selection.nodes or self._minor_first or
                                          self._minor_process))
        self.select_colors_action.setEnabled(bool(self.selection.nodes))
        self.remove_coloring_action.setEnabled(bool(self.graph.number_of_nodes() or
                                                    self.graph.number_of_edges() or
                                                    regions(self.graph)))
        self.copy_action.setEnabled(bool(self.graph.number_of_nodes()))
        self.paste_action.setEnabled(self.clipboard is not None and bool(self.clipboard.nodes))
        self.undo_action.setEnabled(self._history_index > 0)
        self.redo_action.setEnabled(self._history_index < len(self._history) - 1)
        self.select_all_action.setEnabled(bool(self.graph.number_of_nodes()))
        movable = movable_vertices(self.graph, self.selection.nodes)
        pins = pinned_vertices(self.graph)
        size = self.graph.number_of_nodes()
        self.arrange_action.setEnabled(self.grid_mode == 'automatic' and bool(movable)
                                       and size <= 350)
        self.arrange_action.setText('Arrange selection' if self.selection.nodes else 'Arrange graph')
        self.arrange_action.setToolTip('Available for graphs with at most 350 vertices'
                                       if size > 350 else self.arrange_action.text())
        self.pin_action.setEnabled(bool(self.selection.nodes - pins))
        self.unpin_action.setEnabled(bool(self.selection.nodes & pins))
        self.clear_pins_action.setEnabled(bool(pins))
        self.live_layout_action.setEnabled(self.grid_mode == 'automatic' and size <= 200)
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
        self.vertex_colors_up_action.setEnabled(True)
        self.edge_colors_down_action.setEnabled(edge_colors > 1)
        self.edge_colors_up_action.setEnabled(True)
        self.vertex_colors_control.set_limits(vertex_colors > 1, True)
        self.edge_colors_control.set_limits(edge_colors > 1, True)
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
        for action, shortcut in self._unavailable_shortcuts:
            shortcut.setEnabled(not action.isEnabled())

    def commit_change(self):
        state = _serialize_graph(self.graph)
        if state != self._history[self._history_index]:
            topology = topology_payload(public_graph(self.graph))
            if topology != self._info_topology:
                self._invalidate_info()
            self._info_topology = topology
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
        if self.region_path is not None:
            self._cancel_region_path()
        self._clear_full_join()
        self._clear_morphism(cancel_process=True)
        self._clear_minor(cancel_process=True)
        self._clear_product()
        self._history_index = index
        self.graph = _deserialize_graph(copy.deepcopy(self._history[index]))
        topology = topology_payload(public_graph(self.graph))
        if topology != self._info_topology:
            self._invalidate_info()
        self._info_topology = topology
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
        if self.region_path is not None:
            self._cancel_region_path()
        self._clear_full_join()
        self._clear_morphism(cancel_process=True)
        self._clear_minor(cancel_process=True)
        self._clear_product()
        self._invalidate_info()
        self._info_topology = topology_payload(public_graph(self.graph))
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
        self.finish_tutorial()
        self.graph = empty_graph()
        self.path = None
        self.selection.clear()
        self.rebuild_scene()
        self._reset_history()

    def open_file(self):
        if not self._may_replace_document():
            return
        filename, _ = QFileDialog.getOpenFileName(self, 'Open graph', str(self.path.parent if self.path else _documents_folder()),
                                                   'GraphML files (*.graphml);;All files (*)')
        if filename:
            try:
                graph = convert_from_file(filename)
            except Exception as error:
                QMessageBox.critical(self, 'Could not open graph', str(error))
                return
            self.finish_tutorial()
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
        proposed = str(self.path if self.path else _documents_folder() / 'graph.graphml')
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
        proposed = str((self.path or _documents_folder() / 'graph.graphml').with_suffix('.tex'))
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

    def export_picture(self):
        temporary = tempfile.TemporaryDirectory(prefix='graph-builder-preview-')
        try:
            pdf = render_picture_pdf(self.graph, Path(temporary.name) / 'picture.pdf')
            self.picture_preview.show_pdf(pdf)
        except Exception as error:
            temporary.cleanup()
            QMessageBox.critical(self, 'Could not export picture', str(error))
            return
        previous = self._picture_temp
        self._picture_temp = temporary
        if previous is not None:
            previous.cleanup()
        self.info_dock.hide()
        self.help_dock.hide()
        self.tutorial_dock.hide()
        self.picture_dock.show()
        self.picture_dock.raise_()
        self.report('Picture ready to preview and save', 3)

    def _save_picture_preview(self):
        if self._picture_temp is None:
            return
        proposed = str((self.path or _documents_folder() / 'graph.graphml').with_suffix('.png'))
        filters = ('PNG image (*.png);;SVG vector image (*.svg);;PDF document (*.pdf)')
        filename, selected_filter = QFileDialog.getSaveFileName(
            self, 'Save picture', proposed, filters)
        if not filename:
            return
        path = Path(filename)
        suffix_by_filter = {'PNG image (*.png)': '.png',
                            'SVG vector image (*.svg)': '.svg',
                            'PDF document (*.pdf)': '.pdf'}
        selected_suffix = suffix_by_filter.get(selected_filter, '.png')
        if path.suffix.lower() != selected_suffix:
            path = path.with_suffix(selected_suffix)
        try:
            convert_picture_pdf(Path(self._picture_temp.name) / 'picture.pdf', path)
        except Exception as error:
            QMessageBox.critical(self, 'Could not save picture', str(error))
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
        if event.isAccepted() and self._picture_temp is not None:
            self.picture_preview.close_pdf()
            self._picture_temp.cleanup()
            self._picture_temp = None
        if event.isAccepted() and self._info_process is not None:
            self._info_request_id += 1
            process = self._info_process
            process.kill()
            process.waitForFinished(100)
            self._release_info_process(process)
            self._info_process = None
        if event.isAccepted() and self._morphism_process is not None:
            self._clear_morphism(cancel_process=True)


def launch(actions=(), graph_file=None, *, untitled=False,
           tutorial_on_first_run=False, **options):
    app = QApplication.instance() or QApplication(sys.argv)
    if untitled and graph_file is not None:
        raise ValueError('Choose either graph_file or untitled=True.')
    if untitled:
        path = None
        graph = empty_graph(**options)
    else:
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
    if tutorial_on_first_run and untitled:
        settings = QSettings('Cyril Pujol', 'Graph Builder')
        QTimer.singleShot(0, lambda: window.offer_first_run_tutorial(settings))
    return app.exec()


def edit_graph_window(graph=None, *, actions=()):
    """Run a file-optional editor session for the public edit_graph API."""
    import networkx as nx
    from .custom import (integer_key_input, integer_key_output,
                                      normalize_graph, public_graph)

    source = nx.Graph() if graph is None else graph
    if not isinstance(source, nx.Graph):
        raise TypeError('edit_graph expects a NetworkX Graph or DiGraph.')
    source = integer_key_input(source)
    initial = empty_graph(graph_type='digraph' if source.is_directed() else 'graph',
                          multiedges=source.is_multigraph(), loops=bool(nx.number_of_selfloops(source)))
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
    return integer_key_output(public_graph(window.graph))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Graph Builder Qt editor')
    parser.add_argument('--graph', type=Path, help='GraphML file to edit')
    args = parser.parse_args()
    raise SystemExit(launch(graph_file=args.graph))
