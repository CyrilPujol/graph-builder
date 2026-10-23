"""Qt scene items and pointer interaction for the Graph Builder canvas."""
from __future__ import annotations

from math import ceil, cos, hypot, pi, sin

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsItem, QGraphicsPathItem, QGraphicsScene, QGraphicsView

from graph_builder_lib import (
    _edge_curve_points, _set_edge_curve_points, colormap_1, edge_label, flip_edge,
    edge_samples, labels_visible, radial_grid_divisions, triangular_grid_lines,
    vertex_label,
)

NODE_RADIUS = 17
COORDINATE_UNIT = 8 * NODE_RADIUS
DEFAULT_GRID_PRECISION = COORDINATE_UNIT / 4
SELECTION_COLOR = QColor('#15857f')
DRAG_THRESHOLD = 5
MINOR_GRID_COLOR = QColor('#e0e3e7')
SEMIBOLD_GRID_COLOR = QColor('#bcc4cc')
BOLD_GRID_COLOR = QColor('#7f8992')


def _point(pair):
    return QPointF(float(pair[0]), float(pair[1]))


def _label_font(size):
    font = QFont()
    font.setPointSize(size)
    return font


def _selection_mode(modifiers):
    """Translate modifiers into replace/add/remove selection semantics."""
    if modifiers & Qt.ShiftModifier and modifiers & Qt.ControlModifier:
        return 'remove'
    if modifiers & Qt.ShiftModifier:
        return 'add'
    return 'replace'


def _apply_selection(scene, items, mode):
    items = tuple(items)
    if mode == 'replace':
        scene.clearSelection()
    selected = mode != 'remove'
    for item in items:
        if item.scene() is scene:
            item.setSelected(selected)


def _is_secondary(button, modifiers):
    """Right click, or Ctrl+left click for one-button trackpads."""
    return (button == Qt.RightButton or
            (button == Qt.LeftButton and modifiers & Qt.ControlModifier
             and not modifiers & Qt.ShiftModifier))


class NodeItem(QGraphicsItem):
    def __init__(self, window, node):
        super().__init__()
        self.window = window
        self.node = node
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setZValue(2)
        self.setPos(_point(window.graph.nodes[node]['position']))

    def boundingRect(self):
        width = 2 * NODE_RADIUS + 8
        if labels_visible(self.window.graph):
            label = vertex_label(self.window.graph, self.node)
            width = max(width, QFontMetricsF(_label_font(13)).horizontalAdvance(label) + 10)
        return QRectF(-width / 2, -NODE_RADIUS - 5, width, 2 * NODE_RADIUS + 10)

    def shape(self):
        shape = QPainterPath()
        shape.addEllipse(QPointF(0, 0), NODE_RADIUS + 3, NODE_RADIUS + 3)
        return shape

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(*colormap_1(self.window.graph.nodes[self.node].get('col', 0)))
        painter.setBrush(color)
        painter.setPen(QPen(SELECTION_COLOR if self.isSelected() else QColor('#222222'), 3 if self.isSelected() else 1.5))
        painter.drawEllipse(QPointF(0, 0), NODE_RADIUS, NODE_RADIUS)
        if labels_visible(self.window.graph):
            label = vertex_label(self.window.graph, self.node)
            font = _label_font(13)
            path = QPainterPath()
            metrics = QFontMetricsF(font)
            bounds = metrics.boundingRect(label)
            path.addText(-bounds.width()/2, (metrics.ascent()-metrics.descent())/2, font, label)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor('#111111'), 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(path)
            painter.setPen(Qt.NoPen)
            painter.setBrush(Qt.white)
            painter.drawPath(path)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged and self.node in self.window.graph:
            self.window.graph.nodes[self.node]['position'] = (value.x(), value.y())
            self.window.refresh_adjacent_edges(self.node)
        return super().itemChange(change, value)

class EdgeItem(QGraphicsPathItem):
    def __init__(self, window, source, target):
        super().__init__()
        self.window = window
        self.source = source
        self.target = target
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setZValue(1)
        self.refresh()

    def refresh(self):
        if not self.window.graph.has_edge(self.source, self.target):
            return
        samples = edge_samples(self.window.graph, self.source, self.target)
        path = QPainterPath(_point(samples[0]))
        for sample in samples[1:]:
            path.lineTo(_point(sample))
        self.setPath(path)
        self.setPen(QPen(QColor(*colormap_1(self.window.graph.edges[self.source, self.target].get('col', 0))), 2))
        self.update()

    def closest_path_position(self, position):
        """Return the closest point and its traversal position along the path."""
        path = self.path()
        closest = path.pointAtPercent(0)
        path_position = 0.0
        best_distance = float('inf')
        for index in range(1, path.elementCount()):
            first = path.elementAt(index - 1)
            second = path.elementAt(index)
            dx, dy = second.x - first.x, second.y - first.y
            length_squared = dx * dx + dy * dy
            fraction = (0.0 if length_squared == 0 else max(0.0, min(1.0,
                        ((position.x() - first.x) * dx +
                         (position.y() - first.y) * dy) / length_squared)))
            candidate = QPointF(first.x + fraction * dx, first.y + fraction * dy)
            distance = (candidate.x() - position.x()) ** 2 + (candidate.y() - position.y()) ** 2
            if distance < best_distance:
                closest, best_distance = candidate, distance
                path_position = index - 1 + fraction
        return closest, path_position

    def closest_path_point(self, position):
        """Project a click in the edge's hit area onto its visible path."""
        return self.closest_path_position(position)[0]

    def _label_rect(self):
        label = edge_label(self.window.graph, self.source, self.target)
        metrics = QFontMetricsF(_label_font(12))
        size = metrics.boundingRect(label)
        midpoint = self.path().pointAtPercent(.5)
        return QRectF(midpoint.x() - size.width()/2 - 5,
                      midpoint.y() - size.height()/2 - 3,
                      size.width() + 10, size.height() + 6)

    def boundingRect(self):
        rect = super().boundingRect().adjusted(-13, -13, 13, 13)
        if self.window and self.source in self.window.graph and self.window.graph.has_edge(self.source, self.target):
            if labels_visible(self.window.graph) and edge_label(self.window.graph, self.source, self.target):
                rect = rect.united(self._label_rect())
        return rect

    def shape(self):
        from PySide6.QtGui import QPainterPathStroker
        stroke = QPainterPathStroker()
        stroke.setWidth(12)
        shape = stroke.createStroke(self.path())
        if labels_visible(self.window.graph) and edge_label(self.window.graph, self.source, self.target):
            shape.addRect(self._label_rect())
        return shape

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        color = self.pen().color()
        painter.setBrush(Qt.NoBrush)
        if self.isSelected():
            painter.setPen(QPen(SELECTION_COLOR, 7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(self.path())
        painter.setPen(QPen(color, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(self.path())
        if self.window.is_directed and self.path().length() > 1:
            end = self.path().pointAtPercent(1)
            before = self.path().pointAtPercent(.97)
            dx, dy = end.x() - before.x(), end.y() - before.y()
            length = hypot(dx, dy)
            if length:
                ux, uy = dx/length, dy/length
                tip = end - QPointF(ux*NODE_RADIUS, uy*NODE_RADIUS)
                arrow = QPainterPath(tip)
                arrow.lineTo(tip - QPointF(ux*11 + uy*5, uy*11 - ux*5))
                arrow.lineTo(tip - QPointF(ux*11 - uy*5, uy*11 + ux*5))
                arrow.closeSubpath()
                if self.isSelected():
                    painter.setPen(QPen(SELECTION_COLOR, 5, Qt.SolidLine,
                                        Qt.RoundCap, Qt.RoundJoin))
                    painter.setBrush(SELECTION_COLOR)
                    painter.drawPath(arrow)
                painter.setPen(QPen(color, 1, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                painter.setBrush(color)
                painter.drawPath(arrow)
        if labels_visible(self.window.graph):
            label = edge_label(self.window.graph, self.source, self.target)
            if label:
                painter.setFont(_label_font(12))
                rect = self._label_rect()
                painter.setPen(Qt.NoPen)
                painter.setBrush(Qt.white)
                painter.drawRoundedRect(rect, 3, 3)
                painter.setPen(QColor('#222222'))
                painter.drawText(rect, Qt.AlignCenter, label)

class CurveHandle(QGraphicsEllipseItem):
    def __init__(self, window, source, target, index, position):
        super().__init__(-6, -6, 12, 12)
        self.window = window
        self.source, self.target, self.index = source, target, index
        self.setPos(_point(position))
        self.setBrush(QColor('#f29431'))
        self.setPen(QPen(Qt.white, 2))
        self.setZValue(4)
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)

    def boundingRect(self):
        return QRectF(-10, -10, 20, 20)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        if self.isSelected():
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(SELECTION_COLOR, 2))
            painter.drawEllipse(QPointF(0, 0), 8, 8)
        painter.setBrush(self.brush())
        painter.setPen(self.pen())
        painter.drawEllipse(self.rect())

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged and self.window.graph.has_edge(self.source, self.target):
            points = _edge_curve_points(self.window.graph, self.source, self.target)
            if self.index < len(points):
                points[self.index] = (value.x(), value.y())
                _set_edge_curve_points(self.window.graph, self.source, self.target, points)
                self.window.refresh_adjacent_edges(self.source)
        return super().itemChange(change, value)


class GraphScene(QGraphicsScene):
    def __init__(self, window):
        super().__init__(-10000, -10000, 20000, 20000)
        self.window = window
        self.edge_sources = ()
        self.edge_position = None
        self.edge_drag_active = False
        self.pressed_item = None
        self.press_position = None
        self.press_screen_position = None
        self.press_button = None
        self.press_selection_mode = 'replace'
        self.selection_was_empty = True
        self.positions_before_drag = {}
        self.double_click_handled = False
        self.created_curve_handle = False
        self.secondary_handle = False
        self.lasso_points = []
        self.rubber_rect = None

    def drawBackground(self, painter, rect):
        painter.fillRect(rect, QColor('#fcfcfd'))
        mode = self.window.grid_mode
        if mode is None:
            return
        unit = self.window.grid_unit
        origin = self.window.grid_origin
        if mode == 'square':
            left = ceil((rect.left()-origin.x())/unit)
            right = ceil((rect.right()-origin.x())/unit)
            top = ceil((rect.top()-origin.y())/unit)
            bottom = ceil((rect.bottom()-origin.y())/unit)
            for index in range(left, right):
                x = origin.x() + index*unit
                if abs(x) < 1e-8:
                    painter.setPen(QPen(BOLD_GRID_COLOR, 2))
                elif abs(x / COORDINATE_UNIT - round(x / COORDINATE_UNIT)) < 1e-8:
                    painter.setPen(QPen(SEMIBOLD_GRID_COLOR, 1.15))
                else:
                    painter.setPen(QPen(MINOR_GRID_COLOR, 0))
                painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            for index in range(top, bottom):
                y = origin.y() + index*unit
                if abs(y) < 1e-8:
                    painter.setPen(QPen(BOLD_GRID_COLOR, 2))
                elif abs(y / COORDINATE_UNIT - round(y / COORDINATE_UNIT)) < 1e-8:
                    painter.setPen(QPen(SEMIBOLD_GRID_COLOR, 1.15))
                else:
                    painter.setPen(QPen(MINOR_GRID_COLOR, 0))
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
                    painter.setPen(QPen(BOLD_GRID_COLOR, 2))
                elif index % major_step == 0:
                    painter.setPen(QPen(SEMIBOLD_GRID_COLOR, 1.15))
                else:
                    painter.setPen(QPen(MINOR_GRID_COLOR, 0))
                painter.drawLine(_point(start), _point(end))
            return
        maximum = max(hypot(corner.x()-origin.x(), corner.y()-origin.y()) for corner in
                      (rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight()))
        previous_divisions = self.window.radial_divisions
        for ring in range(1, min(1000, ceil(maximum/unit)+1)):
            divisions = radial_grid_divisions(ring, self.window.radial_divisions)
            if divisions == 0:
                continue
            radius = ring*unit
            if abs(radius / COORDINATE_UNIT - round(radius / COORDINATE_UNIT)) < 1e-8:
                painter.setPen(QPen(SEMIBOLD_GRID_COLOR, 1.15))
            else:
                painter.setPen(QPen(MINOR_GRID_COLOR, 0))
            painter.drawEllipse(origin, radius, radius)
            if divisions > previous_divisions:
                step = divisions // previous_divisions
                painter.setPen(QPen(MINOR_GRID_COLOR, 0))
                for index in range(divisions):
                    if index % step:
                        angle = -pi/2 + 2*pi*index/divisions
                        start = origin + QPointF(cos(angle)*radius, sin(angle)*radius)
                        end = origin + QPointF(cos(angle)*maximum, sin(angle)*maximum)
                        painter.drawLine(start, end)
                previous_divisions = divisions
        painter.setPen(QPen(BOLD_GRID_COLOR, 2))
        for index in range(self.window.radial_divisions):
            angle = -pi/2 + 2*pi*index/self.window.radial_divisions
            painter.drawLine(origin, origin + QPointF(cos(angle)*maximum, sin(angle)*maximum))
        painter.setBrush(BOLD_GRID_COLOR)
        painter.drawEllipse(origin, 2, 2)

    def drawForeground(self, painter, rect):
        if self.edge_sources and self.edge_position is not None:
            painter.setPen(QPen(SELECTION_COLOR, 2, Qt.DashLine))
            for source in self.edge_sources:
                painter.drawLine(self.window.node_items[source].pos(), self.edge_position)
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

    def cancel_edge_creation(self):
        self.edge_sources = ()
        self.edge_position = None
        self.edge_drag_active = False
        self.update()

    def _edge_source_nodes(self, item):
        return (tuple(self.window.selection.nodes)
                if item.node in self.window.selection.nodes
                and self.window.selection.nodes
                else (item.node,))

    def _finish_edge(self, sources, item):
        if not isinstance(item, NodeItem):
            return
        changed = False
        for source in sources:
            if source != item.node:
                flip_edge(self.window.graph, source, item.node, self.window.edge_color)
                changed = True
        if changed:
            self.window.rebuild_scene()
            self.window.commit_change()

    def mousePressEvent(self, event):
        self.window.last_canvas_position = event.scenePos()
        item = self.itemAt(event.scenePos(), QTransform())
        self.pressed_item = item
        self.press_position = event.scenePos()
        self.press_screen_position = event.screenPos()
        self.press_button = event.button()
        self.press_selection_mode = _selection_mode(event.modifiers())
        self.selection_was_empty = not bool(self.window.selection.nodes or
                                            self.window.selection.edges)
        self.positions_before_drag = {}
        self.double_click_handled = False
        self.created_curve_handle = False
        self.secondary_handle = False
        secondary = _is_secondary(event.button(), event.modifiers())

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

        if secondary and isinstance(item, NodeItem):
            self.edge_sources = self._edge_source_nodes(item)
            self.edge_position = None
            self.edge_drag_active = False
            event.accept()
            return

        if (event.button() == Qt.LeftButton and isinstance(item, NodeItem)
                and self.press_selection_mode == 'replace'):
            if not item.isSelected():
                _apply_selection(self, (item,), 'replace')
            moving = self.window.selection.nodes or {item.node}
            self.positions_before_drag = {
                node: self.window.node_items[node].pos() for node in moving
            }
            super().mousePressEvent(event)
            return

        if isinstance(item, CurveHandle) and event.button() == Qt.LeftButton:
            self.positions_before_drag = {item: item.pos()}
            super().mousePressEvent(event)
            return

        if isinstance(item, (NodeItem, EdgeItem)):
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        self.window.last_canvas_position = event.scenePos()
        if (isinstance(self.pressed_item, EdgeItem)
                and self.pressed_item.isSelected()
                and self.press_button == Qt.LeftButton
                and self.press_selection_mode == 'replace'):
            distance = (event.screenPos() - self.press_screen_position).manhattanLength()
            if distance > DRAG_THRESHOLD:
                edge = self.pressed_item
                handle = self.window.add_curve_point_at(
                    edge.source, edge.target, self.press_position,
                    commit=False, snap_to_path=True,
                )
                if handle is not None:
                    self.pressed_item = handle
                    self.positions_before_drag = {handle: handle.pos()}
                    self.created_curve_handle = True
                    handle.setPos(event.scenePos())
            event.accept()
            return
        if self.edge_sources and isinstance(self.pressed_item, NodeItem):
            distance = (event.screenPos() - self.press_screen_position).manhattanLength()
            if distance > DRAG_THRESHOLD:
                self.edge_drag_active = True
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
            return
        if self.edge_drag_active:
            self.edge_position = event.scenePos()
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.cancel_edge_creation()
        item = self.itemAt(event.scenePos(), QTransform())
        if isinstance(item, NodeItem):
            self.double_click_handled = True
            self.window.rename_node(item.node)
            event.accept()
        elif isinstance(item, EdgeItem):
            self.double_click_handled = True
            self.window.rename_edge(item.source, item.target)
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        self.window.last_canvas_position = event.scenePos()
        if self.double_click_handled:
            self.pressed_item = None
            self.double_click_handled = False
            event.accept()
            return

        item = self.pressed_item
        selection_mode = self.press_selection_mode
        if self.edge_sources and isinstance(item, NodeItem):
            sources = self.edge_sources
            target = self.itemAt(event.scenePos(), QTransform())
            dragged = self.edge_drag_active
            self.cancel_edge_creation()
            if dragged:
                self._finish_edge(sources, target)
            elif (self.selection_was_empty and selection_mode == 'replace'):
                self.window.graph.remove_node(item.node)
                self.window.selection.clear()
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
                if distance <= DRAG_THRESHOLD:
                    self.window.delete_curve_point(item.source, item.target, item.index)
                self.pressed_item = None
                self.secondary_handle = False
                event.accept()
                return
            before = self.positions_before_drag.get(item)
            if not self.created_curve_handle:
                super().mouseReleaseEvent(event)
            if self.created_curve_handle or (before is not None and item.pos() != before):
                self.window.commit_change()
            self.pressed_item = None
            self.created_curve_handle = False
            event.accept()
            return

        if (isinstance(item, NodeItem) and event.button() == Qt.LeftButton
                and selection_mode == 'replace'):
            super().mouseReleaseEvent(event)
            moved = any(self.window.node_items[node].pos() != position
                        for node, position in self.positions_before_drag.items()
                        if node in self.window.node_items)
            if moved:
                self.window.finish_pointer_change()
            else:
                _apply_selection(self, (item,), 'replace')
            self.pressed_item = None
            return

        if isinstance(item, (NodeItem, EdgeItem)):
            _apply_selection(self, (item,), selection_mode)
            self.pressed_item = None
            event.accept()
            return

        super().mouseReleaseEvent(event)
        self.pressed_item = None
        self.press_position = None


class GraphView(QGraphicsView):
    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setMouseTracking(True)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._pan_position = None
        self._pan_button = None
        self._empty_start = None
        self._empty_scene_start = None
        self._empty_secondary = False
        self._empty_selection_mode = 'replace'
        self._empty_had_selection = False
        self._empty_dragged = False
        self.setFocusPolicy(Qt.StrongFocus)

    def position_message(self):
        if hasattr(self, 'message_label'):
            label = self.message_label
            label.move(max(8, self.viewport().width() - label.width() - 18), 18)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.position_message()

    def mousePressEvent(self, event):
        scene_position = self.mapToScene(event.position().toPoint())
        item = self.scene().itemAt(scene_position, QTransform())
        option_pan = (event.button() == Qt.LeftButton
                      and event.modifiers() & Qt.AltModifier)
        if event.button() == Qt.MiddleButton or option_pan:
            self._pan_position = event.position().toPoint()
            self._pan_button = event.button()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        secondary = _is_secondary(event.button(), event.modifiers())
        if item is None and (event.button() in (Qt.LeftButton, Qt.RightButton)):
            self._empty_start = event.position().toPoint()
            self._empty_scene_start = scene_position
            self._empty_secondary = secondary
            self._empty_selection_mode = _selection_mode(event.modifiers())
            selection = self.scene().window.selection
            self._empty_had_selection = bool(selection.nodes or selection.edges)
            self._empty_dragged = False
            if secondary:
                self.scene().lasso_points = [scene_position]
            else:
                self.scene().rubber_rect = QRectF(scene_position, scene_position)
            self.scene().update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pan_position is not None:
            position = event.position().toPoint()
            offset = position - self._pan_position
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - offset.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - offset.y())
            self._pan_position = position
            event.accept()
            return
        if self._empty_start is not None:
            if ((event.position().toPoint() - self._empty_start).manhattanLength()
                    > DRAG_THRESHOLD):
                self._empty_dragged = True
            position = self.mapToScene(event.position().toPoint())
            if self._empty_secondary:
                points = self.scene().lasso_points
                if not points or hypot(position.x() - points[-1].x(),
                                       position.y() - points[-1].y()) > 3:
                    points.append(position)
            else:
                self.scene().rubber_rect = QRectF(self._empty_scene_start, position).normalized()
            self.scene().update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def _finish_area_selection(self):
        if self._empty_secondary:
            points = self.scene().lasso_points
            targets = []
            if len(points) >= 3:
                outline = QPainterPath(points[0])
                for point in points[1:]:
                    outline.lineTo(point)
                outline.closeSubpath()
                targets = [item for item in self.scene().window.node_items.values()
                           if outline.contains(item.pos())]
        else:
            rect = self.scene().rubber_rect
            targets = ([item for item in self.scene().window.node_items.values()
                        if rect is not None and rect.contains(item.pos())])
        _apply_selection(self.scene(), targets, self._empty_selection_mode)

    def mouseReleaseEvent(self, event):
        if event.button() == self._pan_button and self._pan_position is not None:
            self._pan_position = None
            self._pan_button = None
            self.unsetCursor()
            event.accept()
            return
        if self._empty_start is not None:
            if self._empty_dragged:
                self._finish_area_selection()
            elif self._empty_selection_mode == 'replace':
                if self._empty_had_selection:
                    self.scene().clearSelection()
                elif not self._empty_secondary:
                    self.scene().window.add_node(self._empty_scene_start)
            self.scene().rubber_rect = None
            self.scene().lasso_points = []
            self.scene().update()
            self._empty_start = None
            self._empty_scene_start = None
            self._empty_secondary = False
            self._empty_selection_mode = 'replace'
            self._empty_had_selection = False
            self._empty_dragged = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        self.zoom_by_delta(event.angleDelta().y(), event.position())
        event.accept()

    def zoom_by_delta(self, delta, viewport_position):
        """Apply slow, symmetric exponential zoom around a viewport point."""
        if not delta:
            return
        current = self.transform().m11()
        factor = 2 ** (float(delta) / 800.0)
        target = max(0.08, min(12.0, current * factor))
        factor = target / current
        viewport_point = viewport_position.toPoint()
        anchor_before = self.mapToScene(viewport_point)
        self.scale(factor, factor)
        displaced = self.mapFromScene(anchor_before) - viewport_point
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + displaced.x())
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() + displaced.y())
