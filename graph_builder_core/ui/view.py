"""Viewport navigation, zoom and area-selection gestures."""
from __future__ import annotations

from math import hypot, isfinite

from PySide6.QtCore import QEvent, QRectF, Qt
from PySide6.QtGui import QInputDevice, QPainter, QPainterPath
from PySide6.QtWidgets import QGraphicsView

from graph_builder_core.ui.items import (
    DRAG_THRESHOLD, RegionItem, _apply_selection, _is_secondary, _selection_mode,
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
        # Menus, docks and the onboarding hint resize the viewport. They must
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
        self.setFocusPolicy(Qt.StrongFocus)

    def position_message(self):
        if hasattr(self, 'message_label'):
            label = self.message_label
            label.move(max(8, self.viewport().width() - label.width() - 18), 18)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.position_message()

    def keyPressEvent(self, event):
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
        if item is None and (event.button() in (Qt.LeftButton, Qt.RightButton)):
            self._empty_start = event.position().toPoint()
            self._empty_scene_start = scene_position
            self._empty_secondary = secondary
            self._empty_selection_mode = _selection_mode(event.modifiers())
            selection = self.scene().window.selection
            self._empty_had_selection = bool(selection.nodes or selection.edges or selection.regions)
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
