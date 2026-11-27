"""Pointer gestures and scene overlays."""
from __future__ import annotations

from math import ceil, cos, hypot, pi, sin

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainterPath, QPainterPathStroker, QPen, QTransform
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsPathItem, QGraphicsScene

from graph_builder_core.geometry.curves import _edge_curve_points, _set_edge_curve_points
from graph_builder_core.geometry.guides import (
    radial_grid_divisions, radial_grid_new_spokes, triangular_grid_lines,
)
from graph_builder_core.model.operations import flip_edge
from graph_builder_core.model.regions import (
    line_controls, region_by_id, region_segment_points, segment_points, set_line_controls,
    update_region,
)
from graph_builder_core.ui.items import (
    BOLD_GRID_COLOR, COORDINATE_UNIT, CurveHandle, DRAG_THRESHOLD, EdgeItem, MINOR_GRID_COLOR,
    NODE_RADIUS, NodeItem, RegionAnchorHandle, RegionBoundaryItem, RegionCurveHandle,
    RegionItem, SELECTION_COLOR, SEMIBOLD_GRID_COLOR, _apply_selection, _display_edge_style,
    _is_secondary, _point, _selection_mode,
)


class GraphScene(QGraphicsScene):
    def itemAt(self, position, device_transform):
        """Resolve overlapping arcs by the nearest visible arrowhead."""
        candidates = self.items(position, Qt.IntersectsItemShape, Qt.DescendingOrder,
                                device_transform)
        if not candidates:
            return None
        first = candidates[0]
        if isinstance(first, EdgeItem) and self.window.is_directed:
            edges = [item for item in candidates if isinstance(item, EdgeItem)]
            return min(edges, key=lambda item: (
                (item.arrow_tip().x() - position.x()) ** 2
                + (item.arrow_tip().y() - position.y()) ** 2))
        return first

    def __init__(self, window):
        super().__init__(-10000, -10000, 20000, 20000)
        self.window = window
        self.edge_sources = ()
        self.edge_position = None
        self.edge_drag_active = False
        self.edge_chain_changed = False
        self.edge_chain_added = False
        self.edge_last_auto_node = None
        self.edge_trackpad_path = False
        self.edge_hover_target = None
        self.pressed_item = None
        self.pressed_item_was_selected = False
        self.press_position = None
        self.press_screen_position = None
        self.press_button = None
        self.press_selection_mode = 'replace'
        self.selection_was_empty = True
        self.positions_before_drag = {}
        self.axis_snap_guides = ()
        self.axis_snap_guide_endpoints = ()
        self.fusion_marks = ()
        self.fusion_frame = 0
        self._fusion_timer = QTimer(self)
        self._fusion_timer.setInterval(35)
        self._fusion_timer.timeout.connect(self._advance_fusion_animation)
        self._live_relax_timer = QTimer(self)
        self._live_relax_timer.setInterval(50)
        self._live_relax_timer.timeout.connect(self._relax_held_vertex)
        self.last_click_item = None
        self.last_click_screen_position = None
        self.double_click_candidate = None
        self.created_curve_handle = False
        self.secondary_handle = False
        self.region_press_consumed = False
        self.region_preview_item = None
        self.region_hover_item = None
        self.region_hover_target = None
        self.region_boundary_drag = None
        self.lasso_points = []
        self.touch_trail_points = ()
        self.rubber_rect = None

    def _relax_held_vertex(self):
        if self.positions_before_drag:
            self.window.relax_dragged_neighbors(self.positions_before_drag)

    def set_axis_snap_guides(self, guides, endpoints=None):
        guides = tuple(guides)
        endpoints = (tuple(frozenset(nodes) for nodes in endpoints)
                     if endpoints is not None else tuple(frozenset() for _ in guides))
        if len(endpoints) != len(guides):
            raise ValueError('Each alignment guide needs one endpoint set')
        if guides == self.axis_snap_guides and endpoints == self.axis_snap_guide_endpoints:
            return
        self.axis_snap_guides = guides
        self.axis_snap_guide_endpoints = endpoints
        self.update()

    def set_edge_hover_target(self, node):
        if node == self.edge_hover_target:
            return
        previous = self.edge_hover_target
        self.edge_hover_target = node
        for target in (previous, node):
            item = self.window.node_items.get(target)
            if item is not None:
                item.update()

    def show_fusion_animation(self, positions):
        self.fusion_marks = tuple(QPointF(float(x), float(y)) for x, y in positions)
        self.fusion_frame = 0
        if self.fusion_marks:
            self._fusion_timer.start()
            self.update()

    def clear_fusion_animation(self):
        self._fusion_timer.stop()
        self.fusion_marks = ()
        self.update()

    def _advance_fusion_animation(self):
        self.fusion_frame += 1
        if self.fusion_frame >= 9:
            self.clear_fusion_animation()
        else:
            self.update()

    def drawBackground(self, painter, rect):
        dark = getattr(self.window, 'theme_dark', False)
        minor = QColor('#404a52') if dark else MINOR_GRID_COLOR
        semibold = QColor('#64727b') if dark else SEMIBOLD_GRID_COLOR
        bold = QColor('#9aabb5') if dark else BOLD_GRID_COLOR
        painter.fillRect(rect, QColor('#1c2126') if dark else QColor('#fcfcfd'))
        mode = self.window.grid_mode
        if mode is None or mode == 'automatic':
            return
        unit = self.window.grid_unit
        origin = self.window.grid_origin
        if mode == 'axis':
            painter.setPen(QPen(bold, 2))
            painter.drawLine(QPointF(origin.x(), rect.top()),
                             QPointF(origin.x(), rect.bottom()))
            painter.drawLine(QPointF(rect.left(), origin.y()),
                             QPointF(rect.right(), origin.y()))
            return
        if mode == 'square':
            left = ceil((rect.left()-origin.x())/unit)
            right = ceil((rect.right()-origin.x())/unit)
            top = ceil((rect.top()-origin.y())/unit)
            bottom = ceil((rect.bottom()-origin.y())/unit)
            for index in range(left, right):
                x = origin.x() + index*unit
                if abs(x) < 1e-8:
                    painter.setPen(QPen(bold, 2))
                elif abs(x / COORDINATE_UNIT - round(x / COORDINATE_UNIT)) < 1e-8:
                    painter.setPen(QPen(semibold, 1.15))
                else:
                    painter.setPen(QPen(minor, 0))
                painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            for index in range(top, bottom):
                y = origin.y() + index*unit
                if abs(y) < 1e-8:
                    painter.setPen(QPen(bold, 2))
                elif abs(y / COORDINATE_UNIT - round(y / COORDINATE_UNIT)) < 1e-8:
                    painter.setPen(QPen(semibold, 1.15))
                else:
                    painter.setPen(QPen(minor, 0))
                painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            return
        if mode == 'triangular':
            height = unit * 3 ** .5 / 2
            minor_step = 1
            while height * self.window.view.transform().m11() * minor_step < 4:
                minor_step *= 2
            major_step = max(1, round(COORDINATE_UNIT / unit))
            bounds = (rect.left(), rect.top(), rect.right(), rect.bottom())
            for _, index, start, end in triangular_grid_lines(
                    bounds, origin.toTuple(), unit, minor_step, major_step):
                if index == 0:
                    painter.setPen(QPen(bold, 2))
                elif index % major_step == 0:
                    painter.setPen(QPen(semibold, 1.15))
                else:
                    painter.setPen(QPen(minor, 0))
                painter.drawLine(_point(start), _point(end))
            return
        maximum = max(hypot(corner.x()-origin.x(), corner.y()-origin.y()) for corner in
                      (rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight()))
        for ring in range(1, min(1000, ceil(maximum/unit)+1)):
            divisions = radial_grid_divisions(ring, self.window.radial_divisions)
            if divisions == 0:
                continue
            radius = ring*unit
            if abs(radius / COORDINATE_UNIT - round(radius / COORDINATE_UNIT)) < 1e-8:
                painter.setPen(QPen(semibold, 1.15))
            else:
                painter.setPen(QPen(minor, 0))
            painter.drawEllipse(origin, radius, radius)
        painter.setPen(QPen(semibold, 1.15) if unit >= COORDINATE_UNIT
                       else QPen(minor, 0))
        for radius, index, divisions in radial_grid_new_spokes(
                maximum, unit, self.window.radial_divisions):
            angle = -pi/2 + 2*pi*index/divisions
            start = origin + QPointF(cos(angle)*radius, sin(angle)*radius)
            end = origin + QPointF(cos(angle)*maximum, sin(angle)*maximum)
            painter.drawLine(start, end)
        if unit < COORDINATE_UNIT:
            painter.setPen(QPen(semibold, 1.15))
            for radius, index, divisions in radial_grid_new_spokes(
                    maximum, COORDINATE_UNIT, self.window.radial_divisions):
                angle = -pi/2 + 2*pi*index/divisions
                start = origin + QPointF(cos(angle)*radius, sin(angle)*radius)
                end = origin + QPointF(cos(angle)*maximum, sin(angle)*maximum)
                painter.drawLine(start, end)
        painter.setPen(QPen(BOLD_GRID_COLOR, 2))
        for index in range(self.window.radial_divisions):
            angle = -pi/2 + 2*pi*index/self.window.radial_divisions
            painter.drawLine(origin, origin + QPointF(cos(angle)*maximum, sin(angle)*maximum))
        painter.setBrush(BOLD_GRID_COLOR)
        painter.drawEllipse(origin, 2, 2)

    def drawForeground(self, painter, rect):
        if self.fusion_marks:
            painter.save()
            progress = self.fusion_frame / 9
            color = QColor(SELECTION_COLOR)
            color.setAlpha(round(105 * (1 - progress)))
            pen = QPen(color, 2)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            radius = NODE_RADIUS + 7 + 10 * progress
            for position in self.fusion_marks:
                painter.drawEllipse(position, radius, radius)
            painter.restore()
        if self.axis_snap_guides:
            painter.save()
            pen = QPen(SELECTION_COLOR, 3)
            pen.setCosmetic(True)
            painter.setPen(pen)
            for (start, end), endpoints in zip(
                    self.axis_snap_guides, self.axis_snap_guide_endpoints):
                clip = QPainterPath()
                clip.addRect(rect)
                for node in endpoints:
                    item = self.window.node_items.get(node)
                    if item is not None:
                        clip = clip.subtracted(item.mapToScene(item.shape()))
                painter.setClipPath(clip)
                painter.drawLine(_point(start), _point(end))
            painter.restore()
        if self.edge_sources and self.edge_position is not None:
            style = _display_edge_style(self.window, {'style': self.window.edge_color})
            pattern = {'solid': Qt.SolidLine, 'dash': Qt.DashLine,
                       'dot': Qt.DotLine, 'dashdot': Qt.DashDotLine}.get(
                           style['pattern'], Qt.SolidLine)
            opacity = float(style['opacity'])
            painter.setOpacity(opacity if opacity else 1.0)
            painter.setPen(QPen(QColor(style['stroke'] if opacity else '#c5cbd0'),
                                float(style['width']), pattern if opacity else Qt.DotLine,
                                Qt.RoundCap, Qt.RoundJoin))
            for source in self.edge_sources:
                painter.drawLine(self.window.node_items[source].pos(), self.edge_position)
            painter.setOpacity(1.0)
        if len(self.lasso_points) > 1:
            painter.setPen(QPen(SELECTION_COLOR, 2, Qt.DashLine))
            path = QPainterPath(self.lasso_points[0])
            for point in self.lasso_points[1:]:
                path.lineTo(point)
            painter.drawPath(path)
        if self.rubber_rect is not None:
            painter.setPen(QPen(SELECTION_COLOR, 1.5, Qt.DashLine))
            painter.setBrush(QColor(21, 133, 127, 25))
            painter.drawRect(self.rubber_rect)
        if len(self.touch_trail_points) > 1:
            painter.setBrush(Qt.NoBrush)
            pen = QPen(SELECTION_COLOR, 2, Qt.DashLine, Qt.RoundCap, Qt.RoundJoin)
            pen.setCosmetic(True)
            painter.setPen(pen)
            path = QPainterPath(self.touch_trail_points[0])
            for point in self.touch_trail_points[1:]:
                path.lineTo(point)
            painter.drawPath(path)

    def cancel_edge_creation(self):
        self.set_edge_hover_target(None)
        self.edge_sources = ()
        self.edge_position = None
        self.edge_drag_active = False
        self.edge_chain_changed = False
        self.edge_chain_added = False
        self.edge_last_auto_node = None
        self.edge_trackpad_path = False
        self.update()

    def _edge_source_nodes(self, item):
        return (tuple(self.window.selection.nodes)
                if item.node in self.window.selection.nodes
                and self.window.selection.nodes
                else (item.node,))

    def _vertices_crossed_by_drag(self, start, end):
        """Find visited vertex discs even when one mouse event skips over them."""
        dx, dy = end.x() - start.x(), end.y() - start.y()
        length_squared = dx * dx + dy * dy
        crossed = []
        for node, item in self.window.node_items.items():
            center = item.pos()
            fraction = (0.0 if not length_squared else max(0.0, min(1.0,
                        ((center.x() - start.x()) * dx +
                         (center.y() - start.y()) * dy) / length_squared)))
            closest_x = start.x() + fraction * dx
            closest_y = start.y() + fraction * dy
            distance_squared = ((center.x() - closest_x) ** 2 +
                                (center.y() - closest_y) ** 2)
            if distance_squared <= (NODE_RADIUS + 3) ** 2:
                crossed.append((fraction, node, item))
        crossed.sort(key=lambda entry: (entry[0], str(entry[1])))
        return (item for _, _, item in crossed)

    def _finish_edge(self, sources, item, commit=True):
        if not isinstance(item, NodeItem):
            return False, False
        changed = False
        added = False
        for source in sources:
            if source != item.node or (self.window.graph.graph.get('loops', False)
                                       and self.edge_left_vertex):
                existed = self.window.graph.has_edge(source, item.node)
                edge_id = flip_edge(self.window.graph, source, item.node,
                                    self.window.edge_color, avoid_obstacles=True)
                changed = True
                added |= self.window.graph.is_multigraph() or (not existed and self.window.graph.has_edge(source, item.node))
                if not commit:
                    key = self.window.edge_key(source, item.node, edge_id)
                    old_item = self.window.edge_items.pop(key, None)
                    if old_item is not None:
                        self.removeItem(old_item)
                    if self.window.graph.has_edge(source, item.node):
                        edge = EdgeItem(self.window, source, item.node, edge_id)
                        self.window.edge_items[key] = edge
                        self.addItem(edge)
        if changed:
            if commit:
                self.window.rebuild_scene()
                self.window.commit_change()
                if added:
                    self.window.mark_basic_move('create_edge')
            else:
                self.update()
        return changed, added

    def mousePressEvent(self, event):
        if self.window.region_path is not None:
            self.window.region_path_click(self.region_target_at(event.scenePos()), event.scenePos())
            self.region_press_consumed = True
            event.accept()
            return
        self._live_relax_timer.stop()
        if self.axis_snap_guides:
            self.set_axis_snap_guides(())
        self.window.last_canvas_position = event.scenePos()
        item = self.itemAt(event.scenePos(), QTransform())
        self.region_boundary_drag = None
        self.pressed_item = item
        self.pressed_item_was_selected = isinstance(item, (NodeItem, EdgeItem)) and item.isSelected()
        self.press_position = event.scenePos()
        self.press_screen_position = event.screenPos()
        self.press_button = event.button()
        self.press_selection_mode = _selection_mode(event.modifiers())
        self.selection_was_empty = not bool(self.window.selection.nodes or
                                            self.window.selection.edges or
                                            self.window.selection.regions)
        self.positions_before_drag = {}
        self.created_curve_handle = False
        self.secondary_handle = False
        secondary = _is_secondary(event.button(), event.modifiers())
        trackpad_path = (event.button() == Qt.LeftButton
                         and event.modifiers() & Qt.ControlModifier
                         and event.modifiers() & Qt.ShiftModifier
                         and not event.modifiers() & Qt.AltModifier)

        if (isinstance(item, RegionBoundaryItem) and event.button() == Qt.LeftButton
                and self.press_selection_mode == 'replace'
                and not event.modifiers() & (Qt.ControlModifier | Qt.AltModifier)):
            self.region_boundary_drag = {'item': item, 'index': None, 'kind': None}
            event.accept()
            return

        if isinstance(item, RegionItem) and event.button() == Qt.LeftButton:
            region = region_by_id(self.window.graph, item.region_id)
            if region is not None and region['mode'] in ('hull', 'bag'):
                border = QPainterPathStroker()
                border.setWidth(14)
                if border.createStroke(item.path()).contains(item.mapFromScene(event.scenePos())):
                    self.window.report(
                        'Convex hull edges follow their vertices. Choose Manual boundary in Region properties to reshape them.', 5)

        if (isinstance(item, EdgeItem) and item.isSelected()
                and event.button() == Qt.LeftButton
                and not event.modifiers() & (Qt.ShiftModifier | Qt.AltModifier)):
            # Wait for movement: an ordinary click must still select the edge.
            event.accept()
            return

        if secondary and isinstance(item, CurveHandle):
            self.secondary_handle = True
            event.accept()
            return

        if (secondary or trackpad_path) and isinstance(item, NodeItem):
            self.edge_sources = self._edge_source_nodes(item)
            self.edge_position = None
            self.edge_drag_active = False
            self.edge_left_vertex = False
            self.edge_chain_changed = False
            self.edge_chain_added = False
            self.edge_last_auto_node = item.node
            self.edge_trackpad_path = bool(trackpad_path)
            event.accept()
            return

        if (event.button() == Qt.LeftButton and isinstance(item, NodeItem)
                and self.press_selection_mode == 'replace'):
            self.window._live_drag_changed = False
            if not item.isSelected():
                _apply_selection(self, (item,), 'replace')
            moving = self.window.selection.nodes or {item.node}
            self.positions_before_drag = {
                node: self.window.node_items[node].pos() for node in moving
            }
            if self.window.live_layout_action.isChecked():
                self._live_relax_timer.start()
            super().mousePressEvent(event)
            if self.pressed_item_was_selected and len(moving) > 1:
                for node in moving:
                    if node in self.window.node_items:
                        self.window.node_items[node].setSelected(True)
            return

        if isinstance(item, CurveHandle) and event.button() == Qt.LeftButton:
            self.positions_before_drag = {item: item.pos()}
            super().mousePressEvent(event)
            return

        if isinstance(item, (NodeItem, EdgeItem, RegionItem)):
            event.accept()
            return
        super().mousePressEvent(event)

    def region_target_at(self, position):
        return next((item for item in self.items(position)
                     if isinstance(item, (NodeItem, EdgeItem))), None)

    def set_region_hover(self, item):
        """Cue a boundary vertex or an eligible graph edge."""
        if item is self.region_hover_target:
            return
        self.region_hover_target = item
        node = item.node if isinstance(item, NodeItem) else None
        self.set_edge_hover_target(node)
        if self.region_hover_item is not None:
            self.removeItem(self.region_hover_item)
            self.region_hover_item = None
        if isinstance(item, EdgeItem):
            cue = QGraphicsPathItem(item.path())
            cue.setPen(QPen(SELECTION_COLOR, 5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            cue.setZValue(1.9)
            cue.setAcceptedMouseButtons(Qt.NoButton)
            self.addItem(cue)
            self.region_hover_item = cue

    def set_region_preview(self, points, *, close=False):
        if self.region_preview_item is not None:
            self.removeItem(self.region_preview_item)
            self.region_preview_item = None
        if not points:
            return
        path = QPainterPath(_point(points[0]))
        for point in points[1:]:
            path.lineTo(_point(point))
        preview = QGraphicsPathItem(path)
        if len(points) == 1:
            marker = QPainterPath()
            marker.addEllipse(_point(points[0]), 22, 22)
            preview.setPath(marker)
            preview.setBrush(Qt.NoBrush)
            preview.setPen(QPen(SELECTION_COLOR, 3))
            preview.setZValue(3)
        else:
            if close:
                path.closeSubpath()
                preview.setPath(path)
                fill = QColor(SELECTION_COLOR)
                fill.setAlpha(55)
                preview.setBrush(fill)
            preview.setPen(QPen(SELECTION_COLOR, 2.5, Qt.DashLine))
            preview.setZValue(1.8)
            for point in (points[0], points[-1]):
                marker = QGraphicsEllipseItem(-5, -5, 10, 10, preview)
                marker.setPos(_point(point))
                marker.setBrush(QColor('#ffffff'))
                marker.setPen(QPen(SELECTION_COLOR, 2))
                marker.setAcceptedMouseButtons(Qt.NoButton)
        preview.setAcceptedMouseButtons(Qt.NoButton)
        self.addItem(preview)
        self.region_preview_item = preview

    def mouseMoveEvent(self, event):
        self.window.last_canvas_position = event.scenePos()
        if self.region_boundary_drag is not None:
            distance = (event.screenPos() - self.press_screen_position).manhattanLength()
            if distance > DRAG_THRESHOLD:
                if self.region_boundary_drag['index'] is None:
                    self._start_region_boundary_curve()
                self._move_region_boundary_curve(event.scenePos())
            event.accept()
            return
        if (isinstance(self.pressed_item, EdgeItem)
                and self.pressed_item.isSelected()
                and self.press_button == Qt.LeftButton
                and self.press_selection_mode == 'replace'):
            distance = (event.screenPos() - self.press_screen_position).manhattanLength()
            if distance > DRAG_THRESHOLD:
                edge = self.pressed_item
                handle = self.window.add_curve_point_at(
                    edge.source, edge.target, self.press_position,
                    commit=False, snap_to_path=True, key=edge.key,
                )
                if handle is not None:
                    self.pressed_item = handle
                    self.positions_before_drag = {handle: handle.pos()}
                    self.created_curve_handle = True
                    handle.setPos(event.scenePos())
            event.accept()
            return
        if self.edge_sources and isinstance(self.pressed_item, NodeItem):
            if not self.pressed_item.contains(self.pressed_item.mapFromScene(event.scenePos())):
                self.edge_left_vertex = True
            distance = (event.screenPos() - self.press_screen_position).manhattanLength()
            if distance > DRAG_THRESHOLD:
                self.edge_drag_active = True
                previous = self.edge_position if self.edge_position is not None else self.press_position
                if event.modifiers() & Qt.ShiftModifier:
                    for target in self._vertices_crossed_by_drag(previous, event.scenePos()):
                        if target.node == self.edge_last_auto_node:
                            continue
                        changed, added = self._finish_edge(self.edge_sources, target,
                                                           commit=False)
                        self.edge_chain_changed |= changed
                        self.edge_chain_added |= added
                        if changed:
                            self.edge_sources = (target.node,)
                        self.edge_last_auto_node = target.node
                if not isinstance(self.itemAt(event.scenePos(), QTransform()), NodeItem):
                    self.edge_last_auto_node = None
                hovered = self.itemAt(event.scenePos(), QTransform())
                self.set_edge_hover_target(
                    hovered.node if isinstance(hovered, NodeItem)
                    and (any(source != hovered.node for source in self.edge_sources)
                         or (self.window.graph.graph.get('loops', False) and self.edge_left_vertex)) else None)
                self.edge_position = event.scenePos()
                self.update()
            event.accept()
            return
        if isinstance(self.pressed_item, CurveHandle):
            if self.created_curve_handle:
                self.pressed_item.setPos(event.scenePos())
            elif not self.secondary_handle:
                super().mouseMoveEvent(event)
            return
        if (isinstance(self.pressed_item, NodeItem)
                and self.press_selection_mode == 'replace'
                and self.press_button == Qt.LeftButton):
            super().mouseMoveEvent(event)
            if self.positions_before_drag and any(
                    self.window.node_items[node].pos() != position
                    for node, position in self.positions_before_drag.items()
                    if node in self.window.node_items):
                self.window.relax_dragged_neighbors(self.positions_before_drag)
                self.window.preview_axis_snap(self.positions_before_drag)
            elif self.axis_snap_guides:
                self.set_axis_snap_guides(())
            return
        if self.edge_drag_active:
            self.edge_position = event.scenePos()
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def _start_region_boundary_curve(self):
        state = self.region_boundary_drag
        boundary = state['item']
        region = region_by_id(self.window.graph, boundary.region_id)
        segment = region['segments'][boundary.segment_index]
        raw = segment_points(self.window.graph, segment)
        visible = region_segment_points(self.window.graph, region, boundary.segment_index)
        press = self.press_position
        nearest = min(range(len(visible)), key=lambda i:
                      (visible[i][0]-press.x())**2 + (visible[i][1]-press.y())**2)
        state['padding_offset'] = (visible[nearest][0]-raw[nearest][0],
                                   visible[nearest][1]-raw[nearest][1])
        if segment['kind'] == 'edge':
            source, target, key = (segment.get('edge_source', segment['source']),
                                   segment.get('edge_target', segment['target']), segment.get('key'))
            edge = self.window.edge_items.get(self.window.edge_key(source, target, key))
            if edge is None:
                return
            controls = _edge_curve_points(self.window.graph, source, target, key)
            raw_press = _point(raw[nearest])
            index = self.window._curve_insertion_index(edge, controls, raw_press)
            controls.insert(index, raw[nearest])
            _set_edge_curve_points(self.window.graph, source, target, controls, key)
            state.update(kind='edge', index=index, source=source, target=target, key=key)
            edge.refresh()
        else:
            controls = line_controls(self.window.graph, segment)
            control_indices = [min(range(len(raw)), key=lambda i:
                               (raw[i][0]-x)**2 + (raw[i][1]-y)**2)
                               for x, y in controls]
            index = sum(i < nearest for i in control_indices)
            controls.insert(index, raw[nearest])
            set_line_controls(self.window.graph, segment, controls)
            update_region(self.window.graph, boundary.region_id, {'segments': region['segments']})
            state.update(kind='line', index=index)
        self.window.refresh_regions()
        self.window._update_region_curve_handles()

    def _move_region_boundary_curve(self, position):
        state = self.region_boundary_drag
        if state['index'] is None:
            return
        offset_x, offset_y = state.get('padding_offset', (0, 0))
        raw_position = (position.x() - offset_x, position.y() - offset_y)
        if state['kind'] == 'edge':
            source, target, key = state['source'], state['target'], state['key']
            controls = _edge_curve_points(self.window.graph, source, target, key)
            controls[state['index']] = raw_position
            _set_edge_curve_points(self.window.graph, source, target, controls, key)
            edge = self.window.edge_items.get(self.window.edge_key(source, target, key))
            if edge is not None:
                edge.refresh()
        else:
            boundary = state['item']
            region = region_by_id(self.window.graph, boundary.region_id)
            segment = region['segments'][boundary.segment_index]
            controls = line_controls(self.window.graph, segment)
            controls[state['index']] = raw_position
            set_line_controls(self.window.graph, segment, controls)
            update_region(self.window.graph, boundary.region_id, {'segments': region['segments']})
        self.window.refresh_regions()
        self.update()

    def mouseDoubleClickEvent(self, event):
        if self.window.region_path is not None:
            self.mousePressEvent(event)
            return
        item = self.itemAt(event.scenePos(), QTransform())
        if isinstance(item, RegionBoundaryItem):
            item = self.window.region_items.get(item.region_id)
        same_click = (item is self.last_click_item
                      and self.last_click_screen_position is not None
                      and (event.screenPos() - self.last_click_screen_position).manhattanLength()
                      <= DRAG_THRESHOLD)
        # Qt emits the double-click event in place of the second press. Route it
        # through the normal press path so a subsequent drag still edits the graph.
        self.mousePressEvent(event)
        if same_click and isinstance(item, (NodeItem, EdgeItem, RegionItem)) and event.button() == Qt.LeftButton:
            self.double_click_candidate = item

    def mouseReleaseEvent(self, event):
        if self.region_press_consumed:
            self.region_press_consumed = False
            event.accept()
            return
        self._live_relax_timer.stop()
        if self.axis_snap_guides:
            self.set_axis_snap_guides(())
        self.window.last_canvas_position = event.scenePos()
        if self.region_boundary_drag is not None:
            state = self.region_boundary_drag
            self.region_boundary_drag = None
            if state['index'] is not None:
                self.window._update_region_curve_handles()
                self.window.commit_change()
            else:
                region_item = self.window.region_items.get(state['item'].region_id)
                if region_item is not None and self.double_click_candidate is region_item:
                    self.double_click_candidate = None
                    self.last_click_item = None
                    self.window.edit_region_properties(region_item.region_id)
                elif region_item is not None:
                    _apply_selection(self, (region_item,), self.press_selection_mode)
                    self.last_click_item = region_item
                    self.last_click_screen_position = event.screenPos()
            self.pressed_item = None
            event.accept()
            return
        if (self.press_screen_position is not None
                and (event.screenPos() - self.press_screen_position).manhattanLength()
                > DRAG_THRESHOLD):
            self.last_click_item = None
            self.last_click_screen_position = None
        released_item = self.itemAt(event.scenePos(), QTransform())
        if isinstance(released_item, RegionBoundaryItem):
            released_item = self.window.region_items.get(released_item.region_id)
        if (self.double_click_candidate is not None
                and released_item is self.double_click_candidate
                and (event.screenPos() - self.press_screen_position).manhattanLength()
                <= DRAG_THRESHOLD):
            item = self.double_click_candidate
            self.double_click_candidate = None
            self.last_click_item = None
            self.pressed_item = None
            if isinstance(item, NodeItem):
                self.window.edit_node_properties(item.node)
            elif isinstance(item, RegionItem):
                self.window.edit_region_properties(item.region_id)
            else:
                self.window.edit_edge_properties(item.source, item.target, item.key)
            event.accept()
            return
        self.double_click_candidate = None

        item = self.pressed_item
        selection_mode = self.press_selection_mode
        if self.edge_sources and isinstance(item, NodeItem):
            sources = self.edge_sources
            target = self.itemAt(event.scenePos(), QTransform())
            dragged = self.edge_drag_active
            chain_changed = self.edge_chain_changed
            chain_added = self.edge_chain_added
            trackpad_path = self.edge_trackpad_path
            left_vertex = self.edge_left_vertex
            self.cancel_edge_creation()
            self.edge_left_vertex = left_vertex
            if dragged:
                changed, added = self._finish_edge(sources, target, commit=False)
                if chain_changed or changed:
                    self.window.rebuild_scene()
                    self.window.commit_change()
                    if chain_added or added:
                        self.window.mark_basic_move('create_edge')
            elif trackpad_path:
                _apply_selection(self, (item,), selection_mode)
            elif selection_mode == 'replace':
                self.window.graph.remove_node(item.node)
                self.window.selection.nodes.discard(item.node)
                self.window.rebuild_scene()
                self.window.commit_change()
            else:
                _apply_selection(self, (item,), selection_mode)
            self.pressed_item = None
            event.accept()
            return

        if isinstance(item, CurveHandle):
            if self.secondary_handle:
                distance = (event.screenPos() - self.press_screen_position).manhattanLength()
                if distance <= DRAG_THRESHOLD and not isinstance(item, RegionAnchorHandle):
                    if isinstance(item, RegionCurveHandle):
                        self.window.delete_region_curve_point(
                            item.region_id, item.segment_index, item.index)
                    else:
                        self.window.delete_curve_point(item.source, item.target, item.index, item.key)
                self.pressed_item = None
                self.secondary_handle = False
                event.accept()
                return
            before = self.positions_before_drag.get(item)
            if not self.created_curve_handle:
                super().mouseReleaseEvent(event)
            if self.created_curve_handle or (before is not None and item.pos() != before):
                self.window.commit_change()
                if not isinstance(item, RegionCurveHandle):
                    self.window._observe_tutorial('curve_edge')
            self.pressed_item = None
            self.created_curve_handle = False
            event.accept()
            return

        if (isinstance(item, NodeItem) and event.button() == Qt.LeftButton
                and selection_mode == 'replace'):
            super().mouseReleaseEvent(event)
            if self.pressed_item_was_selected and len(self.positions_before_drag) > 1:
                for node in self.positions_before_drag:
                    if node in self.window.node_items:
                        self.window.node_items[node].setSelected(True)
            moved = any(self.window.node_items[node].pos() != position
                        for node, position in self.positions_before_drag.items()
                        if node in self.window.node_items)
            if moved or self.window._live_drag_changed:
                self.window.finish_pointer_change()
                if any(self.window.node_items[node].pos() != position
                       for node, position in self.positions_before_drag.items()
                       if node in self.window.node_items):
                    self.window.mark_basic_move('move_vertex')
            else:
                if not (self.pressed_item_was_selected and len(self.window.selection.nodes) > 1):
                    _apply_selection(self, (item,), 'replace')
                self.last_click_item = item
                self.last_click_screen_position = event.screenPos()
            self.window._live_drag_changed = False
            self.pressed_item = None
            return

        if isinstance(item, (NodeItem, EdgeItem, RegionItem)):
            keep_group = (selection_mode == 'replace' and self.pressed_item_was_selected
                          and isinstance(item, EdgeItem) and len(self.window.selection.edges) > 1)
            if not keep_group:
                _apply_selection(self, (item,), selection_mode)
            self.last_click_item = item
            self.last_click_screen_position = event.screenPos()
            self.pressed_item = None
            event.accept()
            return

        super().mouseReleaseEvent(event)
        self.pressed_item = None
        self.press_position = None
