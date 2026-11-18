"""Qt scene items and pointer interaction for the Graph Builder canvas."""
from __future__ import annotations

from math import ceil, cos, hypot, pi, sin

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QInputDevice, QPainter, QPainterPath, QPainterPathStroker, QPen, QPolygonF, QTransform
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsItem, QGraphicsPathItem, QGraphicsScene, QGraphicsView

from .lib import (
    _edge_curve_points, _set_edge_curve_points, edge_label, flip_edge,
    edge_samples, labels_visible, radial_grid_divisions, radial_grid_new_spokes,
    triangular_grid_lines,
    vertex_label,
)
from .layout import PIN_ATTRIBUTE
from .regions import (line_controls, region_by_id, region_points, region_polygons,
                      region_segment_points, segment_points,
                      set_line_controls, update_region)
from .styles import base_style, contrast_text_color, effective_style, vertex_boundary_distance

NODE_RADIUS = 17
EDGE_STROKE_WIDTH = 2.6
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
        style = effective_style(self.window.graph, 'vertex', self.window.graph.nodes[self.node])
        radius = NODE_RADIUS if style['shape'] == 'none' else max(NODE_RADIUS, float(style['size']) / 2)
        width = 2 * radius + 20
        if labels_visible(self.window.graph):
            label = vertex_label(self.window.graph, self.node)
            width = max(width, QFontMetricsF(_label_font(13)).horizontalAdvance(label) + 10)
        return QRectF(-width / 2, -radius - 10, width, 2 * radius + 20)

    def shape(self):
        shape = QPainterPath()
        shape.setFillRule(Qt.WindingFill)
        style = effective_style(self.window.graph, 'vertex', self.window.graph.nodes[self.node])
        radius = (NODE_RADIUS + 3 if style['shape'] == 'none' else
                  max(NODE_RADIUS + 3, float(style['size']) / 2 + 3))
        shape.addEllipse(QPointF(0, 0), radius, radius)
        if style['shape'] == 'none' and labels_visible(self.window.graph):
            metrics = QFontMetricsF(_label_font(13))
            width = metrics.horizontalAdvance(vertex_label(self.window.graph, self.node))
            shape.addRect(QRectF(-width/2 - 4, -metrics.height()/2 - 4,
                                 width + 8, metrics.height() + 8))
        return shape

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        style = effective_style(self.window.graph, 'vertex', self.window.graph.nodes[self.node])
        size = float(style['size'])
        radius = size / 2
        kind = style['shape']
        if kind == 'none':
            radius = NODE_RADIUS
        fill = style['fill']
        if kind.startswith('hollow_'):
            kind = kind[7:]
            fill = 'none'
        polygon = None
        if kind == 'diamond':
            polygon = QPolygonF((QPointF(0, -radius), QPointF(radius, 0),
                                 QPointF(0, radius), QPointF(-radius, 0)))
        elif kind == 'triangle':
            polygon = QPolygonF((QPointF(0, -radius), QPointF(radius, radius),
                                 QPointF(-radius, radius)))
        painter.setBrush(Qt.NoBrush if fill == 'none' else QColor(fill))
        painter.setPen(Qt.NoPen if style['outline'] == 'none' else
                       QPen(QColor(style['outline']), float(style['outline_width'])))
        if kind == 'circle':
            painter.drawEllipse(QPointF(0, 0), radius, radius)
        elif kind == 'square':
            painter.drawRect(QRectF(-radius, -radius, size, size))
        elif polygon is not None:
            painter.drawPolygon(polygon)
        if self.isSelected() or kind == 'none':
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(SELECTION_COLOR if self.isSelected() else QColor('#aeb7bb'),
                                2 if self.isSelected() else 1, Qt.DashLine))
            painter.drawEllipse(QPointF(0, 0), max(radius + 4, NODE_RADIUS),
                                max(radius + 4, NODE_RADIUS))
        if (self.node in self.window._full_join_first or
                self.node in self.window._product_first or
                self.node in self.window._morphism_first or
                self.node in self.window._minor_first):
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor('#b87514'), 2.5, Qt.DashLine))
            painter.drawEllipse(QPointF(0, 0), max(radius + 8, NODE_RADIUS + 8),
                                max(radius + 8, NODE_RADIUS + 8))
        if self.window.scene.edge_hover_target == self.node:
            cue = QColor(SELECTION_COLOR)
            cue.setAlpha(160)
            pen = QPen(cue, 2)
            pen.setCosmetic(True)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(pen)
            painter.drawEllipse(QPointF(0, 0), max(radius + 8, NODE_RADIUS + 8),
                                max(radius + 8, NODE_RADIUS + 8))
        if self.window.graph.nodes[self.node].get(PIN_ATTRIBUTE):
            painter.setPen(QPen(QColor('#353b41'), 1.5))
            painter.setBrush(QColor('#f5f6f7'))
            painter.drawEllipse(QPointF(12, -13), 5, 5)
            painter.drawLine(QPointF(12, -8), QPointF(12, -3))
        if labels_visible(self.window.graph):
            label = vertex_label(self.window.graph, self.node)
            font = _label_font(13)
            path = QPainterPath()
            metrics = QFontMetricsF(font)
            bounds = metrics.boundingRect(label)
            path.addText(-bounds.width()/2, (metrics.ascent()-metrics.descent())/2, font, label)
            text_color = style['text']
            if text_color == 'auto':
                text_color = contrast_text_color(fill)
            outline = '#ffffff' if QColor(text_color).lightness() < 128 else '#111111'
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(outline), 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(path)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(text_color))
            painter.drawPath(path)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged and self.node in self.window.graph:
            self.window.graph.nodes[self.node]['position'] = (value.x(), value.y())
            self.window.refresh_adjacent_edges(self.node)
            self.window.refresh_regions()
        return super().itemChange(change, value)

from .edges import edge_data


class EdgeItem(QGraphicsPathItem):
    def __init__(self, window, source, target, key=None):
        super().__init__()
        self.window = window
        self.source = source
        self.target = target
        self.key = key
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setZValue(1)
        self.refresh()

    def refresh(self):
        if not self.window.graph.has_edge(self.source, self.target):
            return
        samples = edge_samples(self.window.graph, self.source, self.target, self.key)
        path = QPainterPath(_point(samples[0]))
        for sample in samples[1:]:
            path.lineTo(_point(sample))
        self.setPath(path)
        style = effective_style(self.window.graph, 'edge', edge_data(self.window.graph, self.source, self.target, self.key))
        self.setPen(QPen(QColor(style['stroke']), float(style['width'])))
        self.update()

    def _appearance(self):
        if self.source in self.window.graph and self.window.graph.has_edge(self.source, self.target):
            return effective_style(self.window.graph, 'edge',
                                   edge_data(self.window.graph, self.source, self.target, self.key))
        return base_style('edge', 0)

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

    def arrow_tip(self):
        path = self.path()
        end, before = path.pointAtPercent(1), path.pointAtPercent(.97)
        dx, dy = end.x() - before.x(), end.y() - before.y()
        length = hypot(dx, dy)
        if not length:
            return end
        style = effective_style(self.window.graph, 'vertex', self.window.graph.nodes[self.target])
        distance = vertex_boundary_distance(style, -dx / length, -dy / length)
        return end - QPointF(dx / length * distance, dy / length * distance)

    def closest_path_point(self, position):
        """Project a click in the edge's hit area onto its visible path."""
        return self.closest_path_position(position)[0]

    def _label_rect(self):
        label = edge_label(self.window.graph, self.source, self.target, self.key)
        metrics = QFontMetricsF(_label_font(12))
        size = metrics.boundingRect(label)
        style = self._appearance()
        t = float(style['label_t'])
        midpoint = self.path().pointAtPercent(t)
        before = self.path().pointAtPercent(max(0, t - .01))
        after = self.path().pointAtPercent(min(1, t + .01))
        dx, dy = after.x() - before.x(), after.y() - before.y()
        length = hypot(dx, dy)
        if length:
            offset = float(style['label_offset'])
            midpoint += QPointF(-dy * offset / length, dx * offset / length)
        return QRectF(midpoint.x() - size.width()/2 - 5,
                      midpoint.y() - size.height()/2 - 3,
                      size.width() + 10, size.height() + 6)

    def boundingRect(self):
        style = self._appearance()
        padding = max(13, float(style['width']) + 5)
        rect = super().boundingRect().adjusted(-padding, -padding, padding, padding)
        if self.window and self.source in self.window.graph and self.window.graph.has_edge(self.source, self.target):
            if labels_visible(self.window.graph) and edge_label(self.window.graph, self.source, self.target, self.key):
                rect = rect.united(self._label_rect())
        return rect

    def shape(self):
        from PySide6.QtGui import QPainterPathStroker
        stroke = QPainterPathStroker()
        style = self._appearance()
        stroke.setWidth(max(12, float(style['width']) + 6))
        shape = stroke.createStroke(self.path())
        if labels_visible(self.window.graph) and edge_label(self.window.graph, self.source, self.target, self.key):
            shape.addRect(self._label_rect())
        return shape

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        style = self._appearance()
        color = QColor(style['stroke'])
        width = float(style['width'])
        pattern = {'solid': Qt.SolidLine, 'dash': Qt.DashLine,
                   'dot': Qt.DotLine, 'dashdot': Qt.DashDotLine}.get(style['pattern'], Qt.SolidLine)
        painter.setBrush(Qt.NoBrush)
        if self.isSelected():
            painter.setPen(QPen(SELECTION_COLOR, width + 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(self.path())
        painter.setOpacity(float(style['opacity']))
        painter.setPen(QPen(color, width, pattern, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(self.path())
        if float(style['opacity']) == 0:
            painter.setOpacity(1)
            painter.setPen(QPen(QColor('#c5cbd0'), max(1, width), Qt.DotLine))
            painter.drawPath(self.path())
            painter.setOpacity(0)
        if self.window.is_directed and self.path().length() > 1:
            end = self.path().pointAtPercent(1)
            before = self.path().pointAtPercent(.97)
            dx, dy = end.x() - before.x(), end.y() - before.y()
            length = hypot(dx, dy)
            if length:
                ux, uy = dx/length, dy/length
                target_style = effective_style(self.window.graph, 'vertex', self.window.graph.nodes[self.target])
                distance = vertex_boundary_distance(target_style, -ux, -uy)
                tip = end - QPointF(ux*distance, uy*distance)
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
            painter.setOpacity(1.0)
            label = edge_label(self.window.graph, self.source, self.target, self.key)
            if label:
                painter.setFont(_label_font(12))
                rect = self._label_rect()
                painter.setPen(Qt.NoPen)
                painter.setBrush(Qt.white)
                painter.drawRoundedRect(rect, 3, 3)
                painter.setPen(QColor('#222222'))
                painter.drawText(rect, Qt.AlignCenter, label)

class RegionItem(QGraphicsPathItem):
    """Selectable translucent polygon behind graph edges and vertices."""

    def __init__(self, window, region):
        super().__init__()
        self.window = window
        self.region_id = region['id']
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setZValue(0.4)
        # QGraphicsPathItem's hit shape includes its interior only when it has
        # a brush. The actual translucent fill is painted below.
        self.setBrush(QColor(0, 0, 0, 1))
        self.setPen(QPen(Qt.transparent, 4))
        self.refresh()

    def refresh(self):
        region = region_by_id(self.window.graph, self.region_id)
        polygons = region_polygons(self.window.graph, region) if region else []
        path = QPainterPath()
        for points in polygons:
            path.moveTo(_point(points[0]))
            for point in points[1:]:
                path.lineTo(_point(point))
            path.closeSubpath()
        self.setPath(path)
        self.update()

    def paint(self, painter, option, widget=None):
        region = region_by_id(self.window.graph, self.region_id)
        if region is None:
            return
        style = region['style']
        painter.setRenderHint(QPainter.Antialiasing)
        if style['fill'] == 'none':
            painter.setBrush(Qt.NoBrush)
        else:
            fill = QColor(style['fill'])
            fill.setAlphaF(float(style['opacity']))
            painter.setBrush(fill)
        if style['outline'] == 'none':
            painter.setPen(Qt.NoPen)
        else:
            outline = QColor(style['outline'])
            outline.setAlphaF(float(style['opacity']))
            painter.setPen(QPen(outline, float(style['width'])))
        painter.drawPath(self.path())
        if self.isSelected() and self.region_id not in self.window._regions_without_selection_cue:
            cue = QColor(SELECTION_COLOR)
            cue.setAlpha(38)
            painter.setBrush(cue)
            painter.setPen(QPen(SELECTION_COLOR, 2.5, Qt.DashLine))
            painter.drawPath(self.path())
        if region.get('label'):
            painter.setOpacity(1)
            painter.setFont(_label_font(11))
            painter.setPen(QColor('#303943'))
            painter.drawText(self.path().boundingRect(), Qt.AlignCenter, str(region['label']))


class RegionBoundaryItem(QGraphicsPathItem):
    """A selected region's boundary, above ordinary graph edges for editing."""

    def __init__(self, window, region_id, segment_index):
        super().__init__()
        self.window = window
        self.region_id = region_id
        self.segment_index = segment_index
        self.setZValue(1.5)
        self.setVisible(False)
        self.refresh()

    def refresh(self):
        region = region_by_id(self.window.graph, self.region_id)
        if region is None or self.segment_index >= len(region.get('segments', [])):
            self.setPath(QPainterPath())
            return
        points = region_segment_points(self.window.graph, region, self.segment_index)
        path = QPainterPath(_point(points[0])) if points else QPainterPath()
        for point in points[1:]:
            path.lineTo(_point(point))
        self.setPath(path)

    def shape(self):
        stroker = QPainterPathStroker()
        stroker.setWidth(13)
        return stroker.createStroke(self.path())

    def boundingRect(self):
        return self.path().boundingRect().adjusted(-7, -7, 7, 7)

    def paint(self, painter, option, widget=None):
        # RegionItem already draws the boundary. This item only supplies a
        # practical click target, even when there is no standalone edge.
        pass


class CurveHandle(QGraphicsEllipseItem):
    def __init__(self, window, source, target, index, position, key=None):
        super().__init__(-6, -6, 12, 12)
        self.window = window
        self.source, self.target, self.index = source, target, index
        self.key = key
        self._syncing = True
        self.setPos(_point(position))
        self._syncing = False
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
        if (change == QGraphicsItem.ItemPositionHasChanged and not self._syncing
                and self.window.graph.has_edge(self.source, self.target)):
            points = _edge_curve_points(self.window.graph, self.source, self.target, self.key)
            if self.index < len(points):
                points[self.index] = (value.x(), value.y())
                _set_edge_curve_points(self.window.graph, self.source, self.target, points, self.key)
                self.window.refresh_adjacent_edges(self.source)
                self.window.refresh_regions()
        return super().itemChange(change, value)

    def sync_position(self):
        if not self.window.graph.has_edge(self.source, self.target):
            return
        points = _edge_curve_points(self.window.graph, self.source, self.target, self.key)
        if self.index < len(points) and self.pos() != _point(points[self.index]):
            self._syncing = True
            self.setPos(_point(points[self.index]))
            self._syncing = False


class RegionCurveHandle(CurveHandle):
    """A region boundary control, including one backed by a real graph edge."""

    def __init__(self, window, region_id, segment_index, index, position):
        self.region_id = region_id
        self.segment_index = segment_index
        self._syncing = True
        super().__init__(window, None, None, index, position)
        self._syncing = False

    def current_position(self):
        region = region_by_id(self.window.graph, self.region_id)
        if region is None or self.segment_index >= len(region.get('segments', [])):
            return None
        segment = region['segments'][self.segment_index]
        if segment['kind'] == 'edge':
            source = segment.get('edge_source', segment['source'])
            target = segment.get('edge_target', segment['target'])
            points = _edge_curve_points(self.window.graph, source, target, segment.get('key'))
        else:
            points = line_controls(self.window.graph, segment)
        if self.index >= len(points):
            return None
        point = points[self.index]
        if not region.get('margin', 0):
            return point
        raw = segment_points(self.window.graph, segment)
        visible = region_segment_points(self.window.graph, region, self.segment_index)
        if not raw or len(raw) != len(visible):
            return point
        nearest = min(range(len(raw)), key=lambda i:
                      (raw[i][0]-point[0])**2 + (raw[i][1]-point[1])**2)
        return visible[nearest]

    def sync_position(self):
        position = self.current_position()
        if position is not None and self.pos() != _point(position):
            self._syncing = True
            self.setPos(_point(position))
            self._syncing = False

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged and not self._syncing:
            region = region_by_id(self.window.graph, self.region_id)
            if region is not None and self.segment_index < len(region.get('segments', [])):
                segment = region['segments'][self.segment_index]
                adjusted = value.toTuple()
                if region.get('margin', 0):
                    raw = segment_points(self.window.graph, segment)
                    visible = region_segment_points(self.window.graph, region, self.segment_index)
                    if raw and len(raw) == len(visible):
                        old = self.current_position()
                        if old is not None:
                            control = (_edge_curve_points(self.window.graph,
                                segment.get('edge_source', segment['source']),
                                segment.get('edge_target', segment['target']),
                                segment.get('key'))[self.index]
                                if segment['kind'] == 'edge'
                                else line_controls(self.window.graph, segment)[self.index])
                            adjusted = (value.x() - (old[0] - control[0]),
                                        value.y() - (old[1] - control[1]))
                if segment['kind'] == 'edge':
                    source = segment.get('edge_source', segment['source'])
                    target = segment.get('edge_target', segment['target'])
                    key = segment.get('key')
                    points = _edge_curve_points(self.window.graph, source, target, key)
                    if self.index < len(points):
                        points[self.index] = adjusted
                        _set_edge_curve_points(self.window.graph, source, target, points, key)
                        edge = self.window.edge_items.get(self.window.edge_key(source, target, key))
                        if edge is not None:
                            edge.refresh()
                else:
                    points = line_controls(self.window.graph, segment)
                    if self.index < len(points):
                        points[self.index] = adjusted
                        set_line_controls(self.window.graph, segment, points)
                        update_region(self.window.graph, self.region_id,
                                      {'segments': region['segments']})
                self.window.refresh_regions()
        return QGraphicsEllipseItem.itemChange(self, change, value)


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
        self.region_boundary_drag = None
        self.lasso_points = []
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
        painter.fillRect(rect, QColor('#fcfcfd'))
        mode = self.window.grid_mode
        if mode is None or mode == 'automatic':
            return
        unit = self.window.grid_unit
        origin = self.window.grid_origin
        if mode == 'axis':
            painter.setPen(QPen(BOLD_GRID_COLOR, 2))
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
        painter.setPen(QPen(SEMIBOLD_GRID_COLOR, 1.15) if unit >= COORDINATE_UNIT
                       else QPen(MINOR_GRID_COLOR, 0))
        for radius, index, divisions in radial_grid_new_spokes(
                maximum, unit, self.window.radial_divisions):
            angle = -pi/2 + 2*pi*index/divisions
            start = origin + QPointF(cos(angle)*radius, sin(angle)*radius)
            end = origin + QPointF(cos(angle)*maximum, sin(angle)*maximum)
            painter.drawLine(start, end)
        if unit < COORDINATE_UNIT:
            painter.setPen(QPen(SEMIBOLD_GRID_COLOR, 1.15))
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
            style = effective_style(self.window.graph, 'edge', {'col': self.window.edge_color})
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
                edge_id = flip_edge(self.window.graph, source, item.node, self.window.edge_color)
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
            self.window.region_path_click(next(
                (item for item in self.items(event.scenePos())
                 if item is not self.region_preview_item), None))
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

    def set_region_preview(self, points):
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
            preview.setPen(QPen(SELECTION_COLOR, 3, Qt.DashLine))
            preview.setZValue(1.8)
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
                if distance <= DRAG_THRESHOLD:
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


class GraphView(QGraphicsView):
    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHint(QPainter.Antialiasing)
        # Windows can leave trails at item and grid boundaries when only the
        # minimal dirty rectangles are repainted during a drag.
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setMouseTracking(True)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
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

    def mousePressEvent(self, event):
        scene_position = self.mapToScene(event.position().toPoint())
        item = next((candidate for candidate in self.scene().items(scene_position)
                     if candidate is not self.scene().region_preview_item), None)
        if self.scene().window.region_path is not None and item is None:
            self.scene().window.region_path_click(None)
            event.accept()
            return
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
        if not delta:
            return
        self.zoom_by_factor(2 ** (float(delta) * 1.5 / 800.0), viewport_position)

    def zoom_by_factor(self, factor, viewport_position):
        """Scale the view around a pointer, regardless of the input device."""
        if factor <= 0:
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
