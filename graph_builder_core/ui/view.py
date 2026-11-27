"""Viewport navigation, zoom and area-selection gestures."""
from __future__ import annotations

from math import hypot, isfinite
from time import monotonic

from PySide6.QtCore import QEvent, QRectF, Qt, QTimer, QSignalBlocker
from PySide6.QtGui import QInputDevice, QPainter, QPainterPath, QPainterPathStroker
from PySide6.QtWidgets import QGraphicsView

from graph_builder_core.ui.items import (
    DRAG_THRESHOLD, NodeItem, EdgeItem, RegionItem, RegionBoundaryItem,
    _apply_selection, _is_secondary, _selection_mode,
)


class GraphView(QGraphicsView):
    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHint(QPainter.Antialiasing)
        # Windows can leave trails at item and grid boundaries when only the
        # minimal dirty rectangles are repainted during a drag.
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setMouseTracking(True)
        self.setDragMode(QGraphicsView.NoDrag)
        # Zoom is anchored explicitly using the event position below. Qt's
        # implicit mouse anchor can use a stale cursor position after dialogs.
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        # Menus and docks resize the viewport. They must
        # not move the camera towards whichever control the mouse last visited.
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._pan_position = None
        self._pan_button = None
        self._pan_start = None
        self._pan_dragged = False
        self._pan_region_position = None
        self._empty_start = None
        self._empty_scene_start = None
        self._empty_secondary = False
        self._empty_selection_mode = 'replace'
        self._empty_had_selection = False
        self._empty_dragged = False
        self.pending_selection_tool = None
        self._active_selection_tool = None
        self._ignore_selection_release = False
        self._touch_targets = set()
        self._touch_previous = None
        self._touch_trail = []
        self._touch_timer = QTimer(self)
        self._touch_timer.setInterval(33)
        self._touch_timer.timeout.connect(self._expire_touch_trail)
        self.setFocusPolicy(Qt.StrongFocus)

    def arm_selection_tool(self, kind):
        self.cancel_selection_tool()
        if self.scene().window.region_path is not None:
            self.scene().window.make_region()
        self.pending_selection_tool = kind
        self.setCursor(Qt.CrossCursor)
        message = ('Drag around vertices to select them' if kind == 'lasso' else
                   'Drag over vertices, edges, or regions to select them')
        self.scene().window.report(message, 6)
        self.scene().window.update_actions()
        self.setFocus()

    def cancel_selection_tool(self):
        armed = self.pending_selection_tool is not None or self._active_selection_tool is not None
        self.pending_selection_tool = None
        if self._active_selection_tool is not None:
            self._ignore_selection_release = self._empty_start is not None
            self._empty_start = self._empty_scene_start = None
            self.scene().lasso_points = []
            self.scene().rubber_rect = None
            self._active_selection_tool = None
        if armed:
            self._touch_targets.clear()
            self.unsetCursor()
            self.scene().update()
            self.scene().window.update_actions()
        if self._touch_trail:
            self._touch_trail.clear()
            self.scene().touch_trail_points = ()
            self._touch_timer.stop()
            self.scene().update()
        return armed

    def _expire_touch_trail(self):
        now = monotonic()
        self._touch_trail = [(stamp, point) for stamp, point in self._touch_trail if now-stamp <= 1]
        self.scene().touch_trail_points = tuple(point for _, point in self._touch_trail)
        self.scene().update()
        if not self._touch_trail:
            self._touch_timer.stop()

    def _touch_segment(self, position):
        path = QPainterPath(self._touch_previous)
        path.lineTo(position)
        stroker = QPainterPathStroker()
        stroker.setWidth(2 / max(abs(self.transform().m11()), 1e-6))
        for item in self.scene().items(stroker.createStroke(path), Qt.IntersectsItemShape):
            if isinstance(item, RegionBoundaryItem):
                item = self.scene().window.region_items.get(item.region_id)
            if isinstance(item, (NodeItem, EdgeItem, RegionItem)):
                self._touch_targets.add(item)
        # Apply the complete accumulated set, so sparse mouse events still
        # select everything crossed and replace mode keeps earlier hits.
        with QSignalBlocker(self.scene()):
            _apply_selection(self.scene(), self._touch_targets, self._empty_selection_mode)
        self.scene().window.selection_changed()
        self._touch_previous = position
        self._touch_trail.append((monotonic(), position))
        self._expire_touch_trail()

    def position_message(self):
        if hasattr(self, 'message_label'):
            label = self.message_label
            label.move(max(8, self.viewport().width() - label.width() - 18), 18)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.position_message()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self.cancel_selection_tool():
            event.accept()
            return
        if event.key() == Qt.Key_Escape and self.scene().window.region_path is not None:
            self.scene().window.make_region()
            event.accept()
            return
        if (event.key() in (Qt.Key_Return, Qt.Key_Enter)
                and not event.modifiers() & (Qt.ControlModifier | Qt.AltModifier |
                                           Qt.MetaModifier | Qt.ShiftModifier)
                and self.scene().window.region_path is not None):
            self.scene().window.finish_region_path()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        self._ignore_selection_release = False
        scene_position = self.mapToScene(event.position().toPoint())
        if self.scene().window.region_path is not None:
            target = self.scene().region_target_at(scene_position)
            self.scene().window.region_path_click(target, scene_position)
            event.accept()
            return
        item = next((candidate for candidate in self.scene().items(scene_position)
                     if candidate is not self.scene().region_preview_item), None)
        option_pan = (event.button() == Qt.LeftButton
                      and event.modifiers() & Qt.AltModifier)
        if event.button() == Qt.MiddleButton or option_pan:
            self.cancel_selection_tool()
            self._pan_position = event.position().toPoint()
            self._pan_button = event.button()
            self._pan_start = self._pan_position
            self._pan_dragged = False
            self._pan_region_position = (scene_position if option_pan and isinstance(item, RegionItem)
                                         else None)
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        secondary = _is_secondary(event.button(), event.modifiers())
        if ((item is None or self.pending_selection_tool is not None)
                and event.button() in (Qt.LeftButton, Qt.RightButton)):
            self._active_selection_tool = self.pending_selection_tool
            self.pending_selection_tool = None
            self._empty_start = event.position().toPoint()
            self._empty_scene_start = scene_position
            self._empty_secondary = self._active_selection_tool == 'lasso' or (
                secondary and self._active_selection_tool != 'touch')
            self._empty_selection_mode = _selection_mode(event.modifiers())
            selection = self.scene().window.selection
            self._empty_had_selection = bool(selection.nodes or selection.edges or selection.regions)
            self._empty_dragged = False
            if self._active_selection_tool == 'touch':
                self._touch_targets = set()
                self._touch_previous = scene_position
                self._touch_trail = [(monotonic(), scene_position)]
                self._touch_timer.start()
            elif self._empty_secondary:
                self.scene().lasso_points = [scene_position]
            else:
                self.scene().rubber_rect = QRectF(scene_position, scene_position)
            self.scene().update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.scene().window.region_path is not None:
            position = self.mapToScene(event.position().toPoint())
            target = self.scene().region_target_at(position)
            self.scene().window.region_path_hover(target, position)
            event.accept()
            return
        if self._pan_position is not None:
            position = event.position().toPoint()
            if (position - self._pan_start).manhattanLength() > DRAG_THRESHOLD:
                self._pan_dragged = True
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
            if self._active_selection_tool == 'touch':
                if self._empty_dragged:
                    self._touch_segment(position)
            elif self._empty_secondary:
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
        if self._ignore_selection_release:
            self._ignore_selection_release = False
            event.accept()
            return
        if event.button() == self._pan_button and self._pan_position is not None:
            create_inside_region = not self._pan_dragged and self._pan_region_position is not None
            region_position = self._pan_region_position
            self._pan_position = None
            self._pan_button = None
            self._pan_start = None
            self._pan_region_position = None
            self.unsetCursor()
            if create_inside_region:
                self.scene().window.add_node(region_position)
            event.accept()
            return
        if self._empty_start is not None:
            if ((event.position().toPoint() - self._empty_start).manhattanLength()
                    > DRAG_THRESHOLD):
                self._empty_dragged = True
            if self._empty_dragged:
                position = self.mapToScene(event.position().toPoint())
                if self._active_selection_tool == 'touch':
                    self._touch_segment(position)
                else:
                    if self._empty_secondary:
                        self.scene().lasso_points.append(position)
                    else:
                        self.scene().rubber_rect = QRectF(self._empty_scene_start, position).normalized()
                    self._finish_area_selection()
            elif self._empty_selection_mode == 'replace' and self._active_selection_tool is None:
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
            self._active_selection_tool = None
            self._touch_targets.clear()
            self.unsetCursor()
            self.scene().window.update_actions()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        # Keep wheel mice zooming. A touchpad scroll pans in both directions,
        # while a native pinch is handled separately by viewportEvent.
        pixels = event.pixelDelta()
        angles = event.angleDelta()
        touchpad = (event.device() is not None and
                    event.device().type() == QInputDevice.DeviceType.TouchPad)
        if touchpad and not event.modifiers() & Qt.ControlModifier:
            if not pixels.isNull():
                self.pan_by_pixels(pixels.x(), pixels.y())
            else:
                self.pan_by_pixels(angles.x() / 2, angles.y() / 2)
        elif angles.y():
            self.zoom_by_delta(angles.y(), event.position())
        elif angles.x():
            self.pan_by_pixels(angles.x() / 2, 0)
        event.accept()

    def viewportEvent(self, event):
        if (event.type() == QEvent.NativeGesture and
                event.gestureType() == Qt.ZoomNativeGesture):
            self.zoom_by_factor(1 + event.value(), event.position())
            event.accept()
            return True
        return super().viewportEvent(event)

    def pan_by_pixels(self, x, y):
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - round(x))
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() - round(y))

    def zoom_by_delta(self, delta, viewport_position):
        """Apply symmetric exponential zoom around a viewport point."""
        if not delta or not isfinite(delta):
            return
        exponent = max(-20.0, min(20.0, float(delta) * 1.5 / 800.0))
        self.zoom_by_factor(2 ** exponent, viewport_position)

    def zoom_by_factor(self, factor, viewport_position):
        """Scale the view around a pointer, regardless of the input device."""
        if not isfinite(factor) or factor <= 0:
            return
        current = self.transform().m11()
        target = max(0.08, min(12.0, current * factor))
        factor = target / current
        viewport_point = viewport_position.toPoint()
        anchor_before = self.mapToScene(viewport_point)
        self.scale(factor, factor)
        displaced = self.mapFromScene(anchor_before) - viewport_point
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + displaced.x())
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() + displaced.y())
