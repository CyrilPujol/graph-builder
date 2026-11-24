"""Qt application shell for Graph Builder.

Owns the document, selection and shared UI state. Cohesive groups of window
behaviors live in ``ui.controllers``. Rendering, scene gestures and camera
navigation live in ``items``, ``scene`` and ``view`` respectively.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
import copy
import json
from math import hypot
from pathlib import Path
import sys
import time

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QSettings, Qt, QTimer
from PySide6.QtGui import (
    QAction, QActionGroup, QColor, QCursor, QFileOpenEvent, QKeySequence, QShortcut,
    QTransform,
)
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QComboBox, QFrame, QDialog, QGraphicsDropShadowEffect,
    QLabel, QMainWindow, QMessageBox, QTextEdit, QLineEdit, QToolButton, QToolTip, QWidget,
)

from graph_builder_core.actions import (
    Action, EditorContext, builtin_editor_actions, execute_action,
)
from graph_builder_core.algorithms.generators import (
    generate_standard_graph, validate_standard_graph,
)
from graph_builder_core.algorithms.metrics import topology_payload
from graph_builder_core.algorithms.products import PRODUCTS
from graph_builder_core.extensions import ExtensionMenu, ParameterDefinition, public_graph
from graph_builder_core.geometry.curves import _edge_curve_points, _set_edge_curve_points
from graph_builder_core.geometry.guides import axis_alignment_plan, nearest_grid_point
from graph_builder_core.geometry.layout import (
    PIN_ATTRIBUTE, arrange_positions, movable_vertices, pinned_vertices,
    relaxed_neighborhood_positions,
)
from graph_builder_core.io.graphml import convert_from_file
from graph_builder_core.model.document import (
    _serialize_graph, empty_graph, labels_visible, unused_label,
)
from graph_builder_core.model.edges import (
    edge_data, visible_edges, has_edge, remove_edge, set_multiedges,
)
from graph_builder_core.model.operations import cut_edges_to_rest, flip_edge, set_directed
from graph_builder_core.model.regions import (
    DEFAULT_REGION_STYLE, line_controls, region_by_id, region_points, regions, remove_regions,
    set_line_controls, set_regions, update_region, prune_regions,
)
from graph_builder_core.model.selection import (
    EdgeRef, SelectionState, copy_graph_selection, selected_vertices, paste_graph_selection,
)
from graph_builder_core.model.styles import has_custom_look, use_basic_style
from graph_builder_core.ui.action_search import ActionSearchDialog, SearchableControl
from graph_builder_core.ui.controllers.appearance import AppearanceController
from graph_builder_core.ui.controllers.documents import DocumentController
from graph_builder_core.ui.controllers.menus import MenusController
from graph_builder_core.ui.controllers.metrics import MetricsController
from graph_builder_core.ui.controllers.regions import RegionController
from graph_builder_core.ui.controllers.relations import RelationsController
from graph_builder_core.ui.icons import _gear_icon, _search_icon, _transformation_icon
from graph_builder_core.ui.items import (
    COORDINATE_UNIT, DEFAULT_GRID_PRECISION, CurveHandle, EdgeItem, NodeItem,
    RegionAnchorHandle, RegionBoundaryItem, RegionCurveHandle, RegionItem,
)
from graph_builder_core.ui.preferences import (
    PreferencesDialog, settings as preference_settings, theme_manager,
)
from graph_builder_core.ui.scene import GraphScene
from graph_builder_core.ui.tutorial import tutorial_graph
from graph_builder_core.ui.view import GraphView


class MessageSurface:
    """Small compatibility surface for custom actions that report on canvas."""
    def __init__(self, window):
        self.window = window

    def write(self, message, duration=5, screen_relative_position=(.8, .2)):
        self.window.report(message, duration)


class GraphBuilderApplication(QApplication):
    """Receive Finder's open-document events, including after startup."""

    def __init__(self, arguments):
        self._open_window = None
        self._pending_files = []
        super().__init__(arguments)

    def event(self, event):
        if event.type() == QEvent.FileOpen and isinstance(event, QFileOpenEvent):
            url = event.url()
            filename = url.toLocalFile() if url.isLocalFile() else event.file()
            if filename:
                self._pending_files.append(Path(filename))
                QTimer.singleShot(0, self._open_pending_files)
            event.accept()
            return True
        return super().event(event)

    def set_open_window(self, window):
        self._open_window = window
        QTimer.singleShot(0, self._open_pending_files)

    def _open_pending_files(self):
        if self._open_window is None:
            return
        while self._pending_files:
            path = self._pending_files.pop(0)
            if self._open_window.path != path.resolve():
                self._open_window.open_path(path)


class GraphBuilderQt(MetricsController, AppearanceController, RegionController, RelationsController, DocumentController, MenusController, QMainWindow):
    def __init__(self, graph=None, path=None, actions=(), return_graph_on_close=False,
                 parameters=(), extensions=()):
        super().__init__()
        self.graph = graph if graph is not None else empty_graph()
        self.path = Path(path) if path is not None and Path(path).suffix.lower() == '.graphml' else None
        self.return_graph_on_close = return_graph_on_close
        self.custom_actions = tuple(actions)
        if any(not isinstance(action, Action) for action in self.custom_actions):
            raise TypeError('Custom actions must be Graph Builder Action values')
        self.custom_parameters = tuple(parameters)
        self.extra_menus = tuple(extensions)
        if any(not isinstance(menu, ExtensionMenu) for menu in self.extra_menus):
            raise TypeError('Extensions must be ExtensionMenu values')
        self.custom_parameters = tuple({id(item): item for item in (
            *self.custom_parameters, *(p for menu in self.extra_menus for p in menu.parameters))}.values())
        from graph_builder_core.algorithms.generators import STANDARD_GRAPHS
        self.standard_graphs = (*STANDARD_GRAPHS,
                               *(g for menu in self.extra_menus for g in menu.generators))
        self.standard_graph_registry = {g.key: g for g in self.standard_graphs}
        if len(self.standard_graph_registry) != len(self.standard_graphs):
            raise ValueError('Standard graph keys must be unique.')
        self._staged_extension = None
        self._staged_sets = []
        self._completed_selections = ()
        if any(not isinstance(item, ParameterDefinition) for item in self.custom_parameters):
            raise TypeError('Custom parameters must be ParameterDefinition values')
        names = [menu.name for menu in self.extra_menus]
        reserved = {'File', 'Edition', 'Structure', 'Layout', 'Appearances',
                    'Properties', 'Standard graphs', 'Custom'}
        if (len(names) != len(set(names)) or any(not name.strip() for name in names)
                or set(names) & reserved):
            raise ValueError('Extension menu names must be unique and distinct from built-in menus.')
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
        self._subgraph_first = frozenset()
        self._subgraph_process = None
        self._subgraph_kind = None
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
        self._bound_revert_state = None
        self._bound_revert_problem = None
        self._preserve_bound_revert = False
        self._preserve_custom_result = False
        self._info_tooltip_text = None
        self._custom_parameter_values = {}
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
        self._configure_shortcuts()
        self._build_controls()
        self._register_unavailable_shortcuts()
        self._apply_theme()
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
        bound_target = (getattr(self, '_bound_tooltip_rows', {}).get(watched)
                        if isinstance(watched, QWidget) else None)
        if bound_target is not None and event.type() in (QEvent.ToolTip, QEvent.MouseMove):
            bound_row, label = bound_target
            definition = label.toolTip()
            position = (event.pos() if event.type() == QEvent.ToolTip else
                        event.position().toPoint())
            row_position = watched.mapTo(bound_row, position)
            hover_area = QRect(0, 0, label.geometry().right() + 1, bound_row.height())
            if definition and hover_area.contains(row_position) and (
                    event.type() == QEvent.ToolTip or QToolTip.isVisible()):
                global_pos = (event.globalPos() if event.type() == QEvent.ToolTip else
                              event.globalPosition().toPoint())
                QToolTip.showText(global_pos, definition, bound_row, hover_area)
            if event.type() == QEvent.ToolTip:
                event.accept()
                return True
        if watched is self.info_text.viewport():
            if event.type() == QEvent.Leave:
                QToolTip.hideText()
                self._info_tooltip_text = None
            elif event.type() in (QEvent.ToolTip, QEvent.MouseMove):
                position = (event.pos() if event.type() == QEvent.ToolTip else
                            event.position().toPoint())
                target = self._info_definition_at(position)
                definition = target[0] if target else None
                if definition and (event.type() == QEvent.ToolTip or
                                   self._info_tooltip_text not in (None, definition)):
                    global_pos = (event.globalPos() if event.type() == QEvent.ToolTip else
                                  event.globalPosition().toPoint())
                    QToolTip.showText(global_pos, definition,
                                      self.info_text.viewport(), self.info_text.viewport().rect())
                    self._info_tooltip_text = definition
                if event.type() == QEvent.ToolTip:
                    if self._info_tooltip_text:
                        event.accept()
                    else:
                        event.ignore()
                    return True
        if (event.type() == QEvent.ShortcutOverride and self.isActiveWindow()
                and event.matches(QKeySequence.Copy)):
            focus = QApplication.focusWidget()
            if focus is not None and self.info_dock.isAncestorOf(focus):
                event.accept()
                return True
        if (event.type() == QEvent.KeyPress and self.isActiveWindow()
                and QApplication.activeModalWidget() is None
                and QApplication.activePopupWidget() is None):
            focus = QApplication.focusWidget()
            typing = isinstance(focus, (QLineEdit, QAbstractSpinBox, QComboBox, QTextEdit))
            key = event.key()
            modifiers = event.modifiers()
            if not typing and key == Qt.Key_Escape and self.region_path is not None:
                self.make_region()
                return True
            if not typing and key in (Qt.Key_Tab, Qt.Key_Backtab) and not (
                    modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)):
                self.menu_tabs.cycle_tab(-1 if key == Qt.Key_Backtab or
                                         modifiers & Qt.ShiftModifier else 1)
                return True
            if not typing and key in (Qt.Key_Return, Qt.Key_Enter) and not modifiers:
                if self.region_path is not None:
                    self.finish_region_path()
                    return True
                action = self._active_staged_action()
                if action is not None:
                    action.trigger()
                    return True
        return super().eventFilter(watched, event)

    def _active_staged_action(self):
        if self._staged_extension is not None:
            return next(action for definition, action in self.extension_actions
                        if definition is self._staged_extension)
        if self._product_first:
            return self.product_confirm_action
        if self._full_join_first:
            return self.full_join_action
        if self._morphism_first or self._morphism_process is not None:
            return self.morphism_action
        if self._minor_first or self._minor_process is not None:
            return self.minor_action
        if self._subgraph_first or self._subgraph_process is not None:
            return (self.induced_subgraph_action if self._subgraph_kind == 'Induced subgraph'
                    else self.subgraph_action)
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
        for _, shortcut in getattr(self, '_unavailable_shortcuts', ()):
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self._unavailable_shortcuts = []
        actions = tuple(action for _, action in self._shortcut_registry.values())
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
        self.select_neighbours_action = self._action('Select neighbours', self.select_neighbours, 'N')
        self.delete_action = self._action('Delete', self.delete_selection)
        # On a Mac keyboard the key labelled "delete" sends Backspace.  Keep
        # forward Delete as an alternative for full-size and non-Mac keyboards.
        self.delete_action.setShortcuts((QKeySequence(Qt.Key_Backspace),
                                         QKeySequence(Qt.Key_Delete)))
        self._set_action_tooltip(self.delete_action)
        self.rename_action = self._action('Rename…', self.rename_selection)
        self.remove_coloring_action = self._action('Remove coloring', self.remove_coloring)
        self.properties_action = self._action('Selection', self.edit_selection_properties)
        self.styles_action = self._action('Global', self.edit_shared_styles)
        self.copy_style_action = self._action('Copy', self.copy_selected_style, 'Ctrl+Shift+C')
        self.paste_style_action = self._action('Paste', self.paste_selected_style, 'Ctrl+Shift+V')
        for action, description in (
            (self.properties_action, 'Edit the selected object’s appearance.'),
            (self.styles_action, 'Edit the shared basic styles for the whole graph.'),
            (self.copy_style_action, 'Copy the selected object’s appearance.'),
            (self.paste_style_action, 'Apply the copied appearance to the selection.'),
        ):
            action.setProperty('description', description)
            self._set_action_tooltip(action)
        self.addAction(self.copy_style_action)
        self.addAction(self.paste_style_action)
        self.deselect_action = self._action('Deselect', self.deselect, 'Escape')

        self.add_curve_action = self._action('Curve point', self.add_curve_point)
        self.previous_type_action = self._action('Previous style', lambda: self.change_type(-1), 'Shift+S')
        self.next_type_action = self._action('Next style', lambda: self.change_type(1), 'S')
        self.cut_action = self._action('Cut', self.cut_edges, 'C')
        self.full_join_action = self._action('Full join', self.full_join_selection,
                                            'J', checkable=True)
        self.product_confirm_action = self._action('Product', self.product_selection)
        self.product_actions = {
            kind: self._action(title, lambda checked=False, kind=kind: self.start_product(kind))
            for kind, (title, _) in PRODUCTS.items()
        }
        self.morphism_action = self._action('Morphism', self.morphism_selection,
                                            checkable=True)
        self.minor_action = self._action('Minor', self.minor_selection, checkable=True)
        self.subgraph_action = self._action('Subgraph',
            lambda: self.subgraph_selection('Subgraph'), checkable=True)
        self.induced_subgraph_action = self._action('Induced subgraph',
            lambda: self.subgraph_selection('Induced subgraph'), checkable=True)
        self.make_region_action = self._action('Make region', self.make_region, checkable=True)
        self.make_region_action.setToolTip(
            'Fill a selected boundary or trace a new region on the canvas.')
        self.fit_action = self._action('Fit graph', self.fit_graph, 'Space')
        self.zoom_in_action = self._action('Zoom in',
                                           lambda: self.zoom_canvas(1.2), 'Ctrl++')
        self.zoom_out_action = self._action('Zoom out',
                                            lambda: self.zoom_canvas(1 / 1.2), 'Ctrl+-')

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
        self.vertex_colors_down_action = self._action('Fewer vertex styles', lambda: self.change_vertex_colors(self.graph.graph['num_vertex_styles'] - 1))
        self.vertex_colors_up_action = self._action('More vertex styles', lambda: self.change_vertex_colors(self.graph.graph['num_vertex_styles'] + 1))
        self.edge_colors_down_action = self._action('Fewer edge styles', lambda: self.change_edge_colors(self.graph.graph['num_edge_styles'] - 1))
        self.edge_colors_up_action = self._action('More edge styles', lambda: self.change_edge_colors(self.graph.graph['num_edge_styles'] + 1))
        self.info_actions = {
            kind: self._action(kind, lambda checked=False, view=kind: self.show_graph_info(view))
            for kind in ('Metrics', 'Classes', 'Bounds')
        }
        if self.custom_parameters:
            self.info_actions['Custom'] = self._action(
                'Custom', lambda: self.show_graph_info('Custom'))
        self.house_of_graphs_action = self._action('House of Graphs', self.open_house_of_graphs)

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
            (self.new_action, 'Start a blank drawing.'),
            (self.open_action, 'Open a saved graph.'),
            (self.save_action, 'Save the current drawing.'),
            (self.save_as_action, 'Save the drawing under a new name.'),
            (self.export_action, 'Export editable TikZ code.'),
            (self.export_picture_action, 'Render and save a picture of the drawing.'),
            (self.select_all_action, 'Select every vertex.'),
            (self.select_colors_action, 'Select every vertex with a selected style index.'),
            (self.select_neighbours_action, 'Select the open neighbourhood of the selected vertices.'),
            (self.delete_action, 'Delete selected objects.'),
            (self.remove_coloring_action, 'Reset vertex and edge styles to 0 and restore the default region look.'),
            (self.make_region_action, 'Fill a selected boundary or trace a new region.'),
            (self.full_join_action, 'Connect every vertex in a first set to every vertex in a second set.'),
            (self.subgraph_action, 'Find a copy of the second selected graph inside the first.'),
            (self.induced_subgraph_action, 'Find a copy with exactly the same adjacencies.'),
            (self.morphism_action, 'Find a homomorphism from the first selected graph to the second.'),
            (self.minor_action, 'Test whether the first selected graph contains the second as a minor.'),
            (self.house_of_graphs_action, 'Search for this graph on House of Graphs.'),
            (self.copy_style_action, 'Copy only the selected object’s appearance.'),
            (self.paste_style_action, 'Apply a copied appearance to selected objects.'),
            (self.properties_action, 'Edit the selected object’s label and appearance.'),
            (self.zoom_in_action, 'Zoom in around the view center.'),
            (self.zoom_out_action, 'Zoom out around the view center.'),
            (self.clear_pins_action, 'Let every vertex move during automatic layout.'),
            (self.live_layout_action, 'Gently relax neighboring vertices while dragging.'),
            (self.grid_off_action, 'Position vertices freely without guides.'),
            (self.grid_automatic_action, 'Use automatic graph layout.'),
            (self.grid_axis_action, 'Show the coordinate axes and optional alignment snapping.'),
            (self.grid_square_action, 'Show and snap to a square grid.'),
            (self.grid_radial_action, 'Show and snap to a radial grid.'),
            (self.grid_triangular_action, 'Show and snap to a triangular grid.'),
        ):
            action.setProperty('description', description)
            self._set_action_tooltip(action)

        for kind, description in (
            ('Metrics', 'Show counts, degrees, girth, and distances.'),
            ('Classes', 'Check common graph classes and properties.'),
            ('Bounds', 'Show quick bounds and compute exact values when possible.'),
        ):
            self.info_actions[kind].setProperty('description', description)
            self._set_action_tooltip(self.info_actions[kind])
        if self.custom_parameters:
            self.info_actions['Custom'].setProperty('description',
                'Show measures added by your Python script.')
            self._set_action_tooltip(self.info_actions['Custom'])

        self.extension_actions = []
        extra_actions = tuple(action for menu in self.extra_menus for action in menu.actions())
        for definition in (*self.builtin_actions, *self.custom_actions, *extra_actions):
            qt_action = self._action(definition.display_name(self.context()),
                                     lambda checked=False, action=definition: self.run_extension(action),
                                     definition.shortcut)
            qt_action.setProperty('description', definition.description or '')
            self._set_action_tooltip(qt_action)
            self.extension_actions.append((definition, qt_action))
            qt_action.setCheckable(definition.selections > 1)

    def _configure_shortcuts(self):
        """Collect stable action IDs and restore user shortcuts across launches."""
        groups = {
            'File': ('new', 'open', 'save', 'save_as', 'export', 'export_picture', 'close'),
            'Edition': ('undo', 'redo', 'copy', 'paste', 'select_all', 'select_colors',
                        'select_neighbours',
                        'delete', 'deselect'),
            'Structure': ('directed', 'multiedges', 'loops', 'cut', 'full_join',
                          'product_confirm'),
            'Layout': ('fit', 'zoom_in', 'zoom_out', 'arrange', 'pin', 'unpin', 'clear_pins', 'live_layout',
                       'grid_off', 'grid_automatic', 'grid_axis', 'grid_square',
                       'grid_radial', 'grid_triangular', 'axis_snap', 'grid_down',
                       'grid_up', 'radial_down', 'radial_up'),
            'Appearances': ('make_region', 'labels', 'add_curve', 'rename', 'remove_coloring',
                            'properties', 'styles', 'copy_style', 'paste_style',
                            'previous_type', 'next_type', 'vertex_colors_down',
                            'vertex_colors_up', 'edge_colors_down', 'edge_colors_up'),
            'Properties': ('subgraph', 'induced_subgraph', 'morphism', 'minor', 'house_of_graphs'),
        }
        self._shortcut_registry = {}
        for group, names in groups.items():
            for name in names:
                action = getattr(self, name + '_action')
                self._shortcut_registry[f'{group}/{name}'] = (tuple(action.shortcuts()), action)
        for kind, action in self.info_actions.items():
            self._shortcut_registry[f'Properties/{kind.lower()}'] = (tuple(action.shortcuts()), action)
        for kind, action in self.product_actions.items():
            self._shortcut_registry[f'Structure/product_{kind}'] = (tuple(action.shortcuts()), action)
        for definition, action in self.extension_actions:
            group = {'basic': 'Edition', 'edition': 'Structure'}.get(
                definition.group, definition.group.removeprefix('menu:')
                if definition.group.startswith('menu:') else 'Custom')
            key = f'{group}/{definition.id}'
            if key in self._shortcut_registry:
                ordinal = 2
                while f'{key}#{ordinal}' in self._shortcut_registry:
                    ordinal += 1
                key = f'{key}#{ordinal}'
            self._shortcut_registry[key] = (tuple(action.shortcuts()), action)
        for key, (defaults, action) in self._shortcut_registry.items():
            raw = preference_settings().value('shortcuts/' + key, None)
            if raw is None and key.startswith('Properties/'):
                raw = preference_settings().value('shortcuts/Metrics/' + key.split('/', 1)[1], None)
            if raw is not None:
                try:
                    values = json.loads(raw)
                    if isinstance(values, list) and all(isinstance(v, str) for v in values):
                        action.setShortcuts(tuple(QKeySequence(v) for v in values))
                except (TypeError, ValueError):
                    action.setShortcuts(defaults)
            self._set_action_tooltip(action)

    def open_preferences(self):
        if getattr(self, '_active_preferences_dialog', None) is not None:
            self._active_preferences_dialog.raise_()
            self._active_preferences_dialog.activateWindow()
            return
        dialog = PreferencesDialog(self._shortcut_registry, self)
        self._active_preferences_dialog = dialog
        dialog.setWindowModality(Qt.ApplicationModal)
        dialog.finished.connect(lambda result: self._finish_preferences(dialog, result))
        dialog.show()

    def _searchable_controls(self):
        """Resolve action names to the actual visible toolbar control."""
        found = []

        def add(menu, action, widget):
            if widget is None:
                return
            name = action.text().replace('&', '').replace('…', '').strip()
            if not name:
                return
            shortcuts = ', '.join(key.toString(QKeySequence.NativeText)
                                  for key in action.shortcuts() if not key.isEmpty())
            found.append(SearchableControl(menu, name, widget, shortcuts))

        for index in range(self.menu_tabs.count()):
            menu = self.menu_tabs.tabText(index)
            toolbar = self.menu_tabs.widget(index)
            for action in toolbar.actions():
                if action.isSeparator():
                    continue
                widget = toolbar.widgetForAction(action)
                if isinstance(widget, QToolButton):
                    add(menu, action, widget)

        for _, _, control, decrease, increase in self.paired_extension_controls:
            add('Edition', decrease, control.decrease)
            add('Edition', increase, control.increase)
        for _, _, control, actions in self.transformation_controls:
            for button, action in zip(control.findChildren(QToolButton), actions):
                add('Edition', action, button)
        for menu, control, actions in (
            ('Layout', self.grid_unit_control, (self.grid_down_action, self.grid_up_action)),
            ('Layout', self.radial_control, (self.radial_down_action, self.radial_up_action)),
            ('Appearances', self.type_control, (self.previous_type_action, self.next_type_action)),
            ('Appearances', self.vertex_colors_control,
             (self.vertex_colors_down_action, self.vertex_colors_up_action)),
            ('Appearances', self.edge_colors_control,
             (self.edge_colors_down_action, self.edge_colors_up_action)),
        ):
            add(menu, actions[0], control.decrease)
            add(menu, actions[1], control.increase)
        for action in self.style_menu.actions():
            add('Appearances', action, self.style_button)
        for action in self.product_actions.values():
            add('Structure', action, self.product_button)
        found.append(SearchableControl('Appearances', 'Styles', self.style_button))
        found.append(SearchableControl('Structure', 'Product', self.product_button))
        for menu, name, widget, action in getattr(self, 'extension_search_controls', ()):
            shortcuts = (', '.join(key.toString(QKeySequence.NativeText)
                                   for key in action.shortcuts() if not key.isEmpty())
                         if action is not None else '')
            found.append(SearchableControl(menu, name, widget, shortcuts))
        return found

    def open_action_search(self):
        dialog = getattr(self, '_active_action_search', None)
        if dialog is not None:
            dialog.raise_()
            dialog.activateWindow()
            return
        dialog = ActionSearchDialog(self._searchable_controls(), self)
        self._active_action_search = dialog
        dialog.setWindowModality(Qt.ApplicationModal)
        dialog.chosen.connect(lambda index: QTimer.singleShot(
            0, lambda: self._locate_search_result(dialog.controls[index])))
        dialog.finished.connect(lambda _result: self._close_action_search(dialog))
        dialog.show()

    def _close_action_search(self, dialog):
        self._active_action_search = None
        dialog.deleteLater()

    def _locate_search_result(self, control):
        for index in range(self.menu_tabs.count()):
            if self.menu_tabs.tabText(index) == control.menu:
                self.menu_tabs.open_tab(index)
                break
        previous = getattr(self, '_search_highlight_target', None)
        if previous is not None:
            previous.setGraphicsEffect(None)
        effect = QGraphicsDropShadowEffect(control.widget)
        effect.setBlurRadius(17)
        effect.setOffset(0, 0)
        effect.setColor(QColor('#168aaf'))
        control.widget.setGraphicsEffect(effect)
        self._search_highlight_target = control.widget
        if not hasattr(self, '_search_highlight_timer'):
            self._search_highlight_timer = QTimer(self)
            self._search_highlight_timer.setSingleShot(True)
            self._search_highlight_timer.timeout.connect(self._clear_search_highlight)
        self._search_highlight_timer.start(3500)

    def _clear_search_highlight(self):
        target = getattr(self, '_search_highlight_target', None)
        if target is not None:
            target.setGraphicsEffect(None)
        self._search_highlight_target = None

    def _finish_preferences(self, dialog, result):
        self._active_preferences_dialog = None
        dialog.deleteLater()
        if result != QDialog.Accepted:
            return
        store = preference_settings()
        store.setValue('appearance/theme', dialog.theme.currentText())
        for key, (defaults, action) in self._shortcut_registry.items():
            values = dialog.values[key]
            if key.startswith('Properties/'):
                store.remove('shortcuts/Metrics/' + key.split('/', 1)[1])
            default_values = tuple(seq.toString(QKeySequence.PortableText) for seq in defaults)
            if values == default_values:
                store.remove('shortcuts/' + key)
            else:
                store.setValue('shortcuts/' + key, json.dumps(values))
            action.setShortcuts(tuple(QKeySequence(value) for value in values))
            self._set_action_tooltip(action)
            if values and action not in self.actions():
                self.addAction(action)
        self._register_unavailable_shortcuts()
        for control, actions in (
            (self.type_control, (self.previous_type_action, self.next_type_action)),
            (self.grid_unit_control, (self.grid_down_action, self.grid_up_action)),
            (self.radial_control, (self.radial_down_action, self.radial_up_action)),
            (self.vertex_colors_control, (self.vertex_colors_down_action, self.vertex_colors_up_action)),
            (self.edge_colors_control, (self.edge_colors_down_action, self.edge_colors_up_action)),
        ):
            control.decrease.setToolTip(actions[0].toolTip())
            control.increase.setToolTip(actions[1].toolTip())
        for _, _, control, actions in self.transformation_controls:
            for button, action in zip(control.findChildren(QToolButton), actions):
                button.setToolTip(action.toolTip())
        self._apply_theme()
        self.update_actions()

    def _apply_theme(self):
        manager = theme_manager(QApplication.instance())
        manager.apply(str(preference_settings().value('appearance/theme', 'System')))
        self.theme_dark = manager.is_dark
        if hasattr(self, 'preferences_button'):
            self.preferences_button.setIcon(_gear_icon(dark=self.theme_dark))
        if hasattr(self, 'search_button'):
            self.search_button.setIcon(_search_icon(dark=self.theme_dark))
        if hasattr(self, 'standard_graph_choice'):
            self.standard_graph_choice.setPalette(QApplication.instance().palette())
        for _, _, control, _ in getattr(self, 'transformation_controls', ()):
            for button in control.findChildren(QToolButton):
                kind = button.property('transformationKind')
                if kind:
                    button.setIcon(_transformation_icon(kind, dark=self.theme_dark))
        self.scene.update()
        self.view.viewport().update()

    def zoom_canvas(self, factor):
        self.view.zoom_by_factor(factor, QPointF(self.view.viewport().rect().center()))

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
        self.vertex_colors_label.setText(f'  Vertex styles: {self.graph.graph.get("num_vertex_styles", 4)} ')
        self.edge_colors_label.setText(f'  Edge styles: {self.graph.graph.get("num_edge_styles", 2)} ')
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
                self.standard_graph_choice.currentData(), self._standard_parameters(),
                registry=self.standard_graph_registry)
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
            generated = generate_standard_graph(key, parameters,
                                                registry=self.standard_graph_registry)
        except ValueError as error:
            self.report(str(error))
            return set()
        return self._insert_generated_graph(generated)

    def _insert_generated_graph(self, generated, *, arrange_parallel=False):
        """Add a positioned component without replacing the current document."""
        positions = generated.positions
        if not positions:
            self.report('The generated graph is empty.', 4)
            return set()
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
            self.graph.add_node(new_id, position=position, style=self.vertex_color,
                                label=generated.labels[original])
        for source, target in generated.graph.edges:
            first, second = new_ids[source], new_ids[target]
            if arrange_parallel and self.graph.is_multigraph():
                flip_edge(self.graph, first, second, self.edge_color)
                continue
            self.graph.add_edge(first, second, style=self.edge_color, label='')
            if not generated.graph.is_directed() and first != second:
                self.graph.add_edge(second, first, style=self.edge_color, label='')
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
                if 'source_point' in segment:
                    wanted.add((identifier, segment_index, -1))
                if segment['kind'] == 'edge':
                    source = segment.get('edge_source', segment['source'])
                    target = segment.get('edge_target', segment['target'])
                    count = len(_edge_curve_points(self.graph, source, target, segment.get('key')))
                else:
                    count = len(segment.get('controls', []))
                wanted.update((identifier, segment_index, index) for index in range(count))
            if region['mode'] in ('hull', 'bag'):
                wanted.update((identifier, index, -1)
                              for index, anchor in enumerate(region.get('anchors', []))
                              if isinstance(anchor, dict) and 'point' in anchor)
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
            handle = (RegionAnchorHandle(self, identifier, segment_index)
                      if index == -1 else
                      RegionCurveHandle(self, identifier, segment_index, index, (0, 0)))
            handle.sync_position()
            self.scene.addItem(handle)
            self.region_curve_handles.append(handle)
        self._updating_handles = False

    def rebuild_scene(self, selection=None):
        if selection is not None:
            self.selection = selection
        prune_regions(self.graph)
        self.selection.prune(self.graph)
        if any(not group.issubset(self.graph) for group in self._staged_sets):
            self._cancel_staged_extension()
        if not self._full_join_first.issubset(self.graph):
            self._clear_full_join()
        if not self._morphism_first.issubset(self.graph):
            self._clear_morphism(cancel_process=True)
        if not self._minor_first.issubset(self.graph):
            self._clear_minor(cancel_process=True)
        if not self._subgraph_first.issubset(self.graph):
            self._clear_subgraph(cancel_process=True)
        if not self._product_first.issubset(self.graph):
            self._clear_product()
        self._rebuilding = True
        self.scene.set_edge_hover_target(None)
        self.scene.clear_fusion_animation()
        self.scene.set_axis_snap_guides(())
        self.scene.clear()
        self.scene.region_preview_item = None
        self.scene.region_hover_item = None
        self.scene.region_hover_target = None
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
        if self.region_path is not None:
            self.scene.set_region_preview(region_points(
                self.graph, {'mode': 'path', 'segments': self.region_path['segments']}))
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
        self.graph.add_node(node, position=(position.x(), position.y()), style=self.vertex_color)
        self.rebuild_scene()
        self.commit_change()
        self.mark_basic_move('create_vertex')

    def toggle_edge(self, source, target):
        flip_edge(self.graph, source, target, self.edge_color, avoid_obstacles=True)
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
        expanded_guides = []
        endpoints = []
        for index, (guide, (moved_index, reference_index)) in enumerate(zip(guides, matches)):
            start, end = guide
            # The planner emits the x guide before the y guide, including when
            # both guides have zero length and their direction is ambiguous.
            axis = index if start == end and len(guides) == 2 else (0 if start[0] == end[0] else 1)
            along = 1 - axis
            snapped_coordinate = start[axis]
            extent = [start[along], end[along]]
            nodes = {moving[moved_index][0]}
            if reference_index is not None and reference_index < len(references):
                nodes.add(references[reference_index][0])
            for node, item in references:
                position = item.pos().toTuple()
                if abs(position[axis] - snapped_coordinate) <= 1e-6:
                    nodes.add(node)
                    extent.append(position[along])
            for node, item in moving:
                position = item.pos().toTuple()
                if abs(position[axis] + offsets[axis] - snapped_coordinate) <= 1e-6:
                    nodes.add(node)
                    extent.append(position[along] + offsets[along])
            low, high = min(extent), max(extent)
            expanded_guides.append((((snapped_coordinate, low), (snapped_coordinate, high))
                                    if axis == 0 else
                                    ((low, snapped_coordinate), (high, snapped_coordinate))))
            endpoints.append(frozenset(nodes))
        return offsets, tuple(expanded_guides), tuple(endpoints)

    def preview_axis_snap(self, moving_nodes):
        _, guides, endpoints = self.axis_snap_plan(moving_nodes, include_endpoints=True)
        self.scene.set_axis_snap_guides(guides, endpoints)

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
            self.edge_color = (self.edge_color + delta) % self.graph.graph['num_edge_styles']
            self.scene.update()
            return
        if not (self.selection.nodes or self.selection.edges):
            pointer = self.context().pointer_position
            hovered = self.scene.itemAt(QPointF(*pointer), QTransform())
            if isinstance(hovered, NodeItem):
                data = self.graph.nodes[hovered.node]
                custom_look = has_custom_look(data)
                data['style'] = (data.get('style', 0) + delta) % self.graph.graph['num_vertex_styles']
                self.rebuild_scene()
                self.commit_change()
                if self.graph.graph['num_vertex_styles'] > 1:
                    self._observe_tutorial('change_appearance')
                if custom_look:
                    self.report('Style changed, but this vertex has a custom look.', 4)
                return
            self.vertex_color = (self.vertex_color + delta) % self.graph.graph['num_vertex_styles']
            self.report(f'New vertex style: {self.vertex_color}', 2)
            return
        custom_look = (self.graph.graph['num_vertex_styles'] > 1 and any(
            has_custom_look(self.graph.nodes[node]) for node in self.selection.nodes)) or (
            self.graph.graph['num_edge_styles'] > 1 and any(
                has_custom_look(edge_data(self.graph, edge.source, edge.target, edge.key))
                for edge in self.selection.edges))
        changed_vertex_style = bool(self.selection.nodes and self.graph.graph['num_vertex_styles'] > 1)
        for node in self.selection.nodes:
            self.graph.nodes[node]['style'] = (self.graph.nodes[node].get('style', 0) + delta) % self.graph.graph['num_vertex_styles']
        for edge in self.selection.edges:
            source, target, key = edge.source, edge.target, edge.key
            color = (edge_data(self.graph, source, target, key).get('style', 0) + delta) % self.graph.graph['num_edge_styles']
            edge_data(self.graph, source, target, key)['style'] = color
            if not edge.directed and has_edge(self.graph, target, source, key):
                edge_data(self.graph, target, source, key)['style'] = color
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
        self.clipboard = copy_graph_selection(
            self.graph, nodes if nodes or self.selection.regions else None)
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
        self._cancel_staged_extension()
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
        if self._subgraph_first or self._subgraph_process is not None:
            self._clear_subgraph(cancel_process=True)
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
        indices = {int(self.graph.nodes[node].get('style', 0)) for node in self.selection.nodes}
        had_custom = any(has_custom_look(attributes)
                         for _, attributes in self.graph.nodes(data=True)
                         if int(attributes.get('style', 0)) in indices)
        self.scene.clearSelection()
        for node, item in self.node_items.items():
            if int(self.graph.nodes[node].get('style', 0)) in indices:
                item.setSelected(True)
        names = ', '.join(map(str, sorted(indices)))
        note = ' Custom looks were ignored and style indices used.' if had_custom else ''
        term = 'styles' if len(indices) > 1 else 'style'
        self.report(f'Selected vertices with {term} {names}.{note}', 5)

    def select_neighbours(self):
        selected = set(self.selection.nodes)
        if not selected:
            self.report('Select a vertex first.', 4)
            return
        neighbours = set()
        for node in selected:
            adjacent = set(self.graph.successors(node)) | set(self.graph.predecessors(node))
            neighbours.update(adjacent - {node})
        self.scene.clearSelection()
        for node in neighbours:
            self.node_items[node].setSelected(True)

    def remove_coloring(self):
        changed = False
        for _, attributes in self.graph.nodes(data=True):
            changed |= int(attributes.get('style', 0)) != 0 or has_custom_look(attributes)
            use_basic_style(attributes, 0)
        for _, _, attributes in self.graph.edges(data=True):
            changed |= int(attributes.get('style', 0)) != 0 or has_custom_look(attributes)
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
        self.graph.graph['num_vertex_styles'] = count
        self.vertex_color %= count
        for _, data in self.graph.nodes(data=True):
            data['style'] = data.get('style', 0) % count
        self.rebuild_scene()
        self._sync_controls()
        self.commit_change()

    def change_edge_colors(self, count):
        self.graph.graph['num_edge_styles'] = count
        self.edge_color %= count
        for _, _, data in self.graph.edges(data=True):
            data['style'] = data.get('style', 0) % count
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

    def _cancel_staged_extension(self):
        if self._staged_extension is None:
            return
        self._staged_extension = None
        self._staged_sets = []
        self.statusBar().clearMessage()
        for item in self.node_items.values():
            item.update()
        self.update_actions()

    def _request_next_selection(self, title, number=2, total=2, message=None):
        """Common capture feedback for built-in and extension staged actions."""
        self.scene.clearSelection()
        self.selection.clear()
        for item in self.node_items.values():
            item.update()
        self.statusBar().showMessage(message or (
            f'{title}: select set {number} of {total}, '
            'then click again or press Enter. Esc cancels.'))
        self.update_actions()

    def run_extension(self, definition, *, revert_key=None):
        if definition.selections > 1:
            vertices = set(self.selection.nodes)
            if not vertices:
                self.report('Select vertices, then click again or press Enter. Esc cancels.', 5)
                self.update_actions()
                return
            if self._staged_extension is not definition:
                self.deselect()
                self._staged_extension = definition
            self._staged_sets = [group & set(self.graph) for group in self._staged_sets]
            if any(not group for group in self._staged_sets):
                self._cancel_staged_extension()
                self.report('A captured selection was deleted. Start again.', 5)
                self.update_actions()
                return
            self._staged_sets.append(vertices)
            if len(self._staged_sets) < definition.selections:
                self._request_next_selection(definition.display_name(self.context()),
                                             len(self._staged_sets) + 1, definition.selections)
                return
            self._completed_selections = tuple(self._staged_sets)
            self._cancel_staged_extension()
        elif self._staged_extension is not None:
            self._cancel_staged_extension()
        context = self.context()
        before_show = copy.deepcopy(_serialize_graph(self.graph)) if revert_key is not None else None
        # Work on isolated state: failed user code must never partially edit the
        # document, nor leave its selection pointing at deleted vertices.
        context.graph = copy.deepcopy(self.graph)
        context.selection = copy.deepcopy(self.selection)
        old_nodes = set(self.graph)
        try:
            if not execute_action(definition, context):
                return
        finally:
            self._completed_selections = ()
            self.update_actions()
        self.graph = context.graph
        self.selection = context.selection
        self.rebuild_scene()
        if revert_key is not None and _serialize_graph(self.graph) != before_show:
            self._commit_bound_show(revert_key, before_show)
        else:
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
        self.deselect_action.setEnabled(bool(selected_count or self._staged_extension or self._full_join_first or
                                              self._morphism_first or self._morphism_process or
                                              self._minor_first or self._minor_process or
                                              self._subgraph_first or self._subgraph_process or
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
        for action in (self.subgraph_action, self.induced_subgraph_action):
            action.setEnabled(bool(self.selection.nodes or self._subgraph_first or
                                   self._subgraph_process))
        self.select_colors_action.setEnabled(bool(self.selection.nodes))
        self.select_neighbours_action.setEnabled(bool(self.selection.nodes))
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
        self._set_action_tooltip(self.arrange_action)
        if size > 350:
            self.arrange_action.setToolTip(self.arrange_action.toolTip() +
                                           '\nAvailable for graphs with at most 350 vertices.')
        self.pin_action.setEnabled(bool(self.selection.nodes - pins))
        self.unpin_action.setEnabled(bool(self.selection.nodes & pins))
        self.clear_pins_action.setEnabled(bool(pins))
        self.live_layout_action.setEnabled(self.grid_mode == 'automatic' and size <= 200)
        self._set_action_tooltip(self.live_layout_action)
        if size > 200:
            self.live_layout_action.setChecked(False)
            self.live_layout_action.setToolTip(self.live_layout_action.toolTip() +
                                               '\nAvailable for graphs with at most 200 vertices.')
        self.radial_down_action.setEnabled(self.grid_mode == 'radial' and self.radial_divisions > 2)
        self.radial_up_action.setEnabled(self.grid_mode == 'radial' and self.radial_divisions < 99)
        has_precision = self.grid_mode in ('square', 'triangular', 'radial')
        self.grid_down_action.setEnabled(has_precision and self.grid_unit < COORDINATE_UNIT * 16)
        self.grid_up_action.setEnabled(has_precision and self.grid_unit > COORDINATE_UNIT / 64)
        vertex_colors = self.graph.graph['num_vertex_styles']
        edge_colors = self.graph.graph['num_edge_styles']
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
        self.grid_unit_control.set_limits(self.grid_down_action.isEnabled(), self.grid_up_action.isEnabled())
        self.radial_control.set_limits(self.radial_down_action.isEnabled(), self.radial_up_action.isEnabled())
        context = self.context()
        for definition, qt_action in self.extension_actions:
            if definition.selections > 1:
                qt_action.setChecked(self._staged_extension is definition)
            qt_action.setEnabled(definition.is_available(context))
            qt_action.setText(definition.display_name(context))
            self._set_action_tooltip(qt_action)
        from graph_builder_core.ui.extension_menus import refresh_extension_controls
        refresh_extension_controls(self)
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


def launch(actions=(), graph_file=None, *, untitled=False,
           parameters=(), extensions=(),
           tutorial_on_first_run=False, **options):
    app = QApplication.instance() or GraphBuilderApplication(sys.argv)
    from graph_builder_core.io.compact_graphs import COMPACT_SUFFIXES
    compact_path = (Path(graph_file).resolve() if graph_file is not None
                    and Path(graph_file).suffix.lower() in COMPACT_SUFFIXES else None)
    if untitled and graph_file is not None:
        raise ValueError('Choose either graph_file or untitled=True.')
    if untitled or compact_path is not None:
        path = None
        graph = empty_graph(**options)
    else:
        path = Path(graph_file).resolve() if graph_file is not None else Path.cwd() / 'graph.graphml'
        try:
            graph = convert_from_file(path, options)
        except Exception as error:
            QMessageBox.critical(None, 'Could not open graph', str(error))
            return 1
    window = GraphBuilderQt(graph, path, actions, parameters=parameters,
                            extensions=extensions)
    window.show()
    if compact_path is not None:
        QTimer.singleShot(0, lambda: window.open_path(compact_path))
    if isinstance(app, GraphBuilderApplication):
        app.set_open_window(window)
    if graph.number_of_nodes():
        window.fit_graph()
    if tutorial_on_first_run and untitled:
        settings = QSettings('Cyril Pujol', 'Graph Builder')
        # Finder may deliver its file-open event just after the first event loop turn.
        QTimer.singleShot(350, lambda: window.offer_first_run_tutorial(settings)
                          if window.path is None and not getattr(app, '_pending_files', ()) else None)
    return app.exec()


def edit_graph_window(graph=None, *, actions=(), parameters=(), extensions=()):
    """Run a file-optional editor session for the public edit_graph API."""
    import networkx as nx
    from graph_builder_core.extensions import integer_key_input, integer_key_output, normalize_graph, public_graph

    source = nx.Graph() if graph is None else graph
    if not isinstance(source, nx.Graph):
        raise TypeError('edit_graph expects a NetworkX Graph or DiGraph.')
    source = integer_key_input(source)
    from graph_builder_core.model.document import canonical_graph_options
    source.graph.update(canonical_graph_options(source.graph))
    source.graph.pop('num_vertex_colors', None)
    source.graph.pop('num_edge_colors', None)
    initial = empty_graph(graph_type='digraph' if source.is_directed() else 'graph',
                          multiedges=source.is_multigraph(), loops=bool(nx.number_of_selfloops(source)))
    for key in ('num_vertex_styles', 'num_edge_styles', 'show_labels'):
        if key in source.graph:
            initial.graph[key] = source.graph[key]
    normalized, _ = normalize_graph(source, initial)

    app = QApplication.instance() or QApplication([])
    window = GraphBuilderQt(normalized, actions=actions, return_graph_on_close=True,
                            parameters=parameters, extensions=extensions)
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
