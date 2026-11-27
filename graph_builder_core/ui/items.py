"""Canvas objects, handles and shared appearance constants."""
from __future__ import annotations

from math import hypot

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPainterPathStroker, QPen, QPolygonF,
)
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsItem, QGraphicsPathItem

from graph_builder_core.geometry.curves import (
    _edge_curve_points, _set_edge_curve_points, edge_samples, visible_edge_cubics,
)
from graph_builder_core.geometry.layout import PIN_ATTRIBUTE
from graph_builder_core.model.document import edge_label, labels_visible, vertex_label
from graph_builder_core.model.edges import edge_data
from graph_builder_core.model.selection import EdgeRef
from graph_builder_core.model.regions import (
    line_controls, region_by_id, region_polygons, region_segment_points, segment_points,
    set_line_controls, update_region,
)
from graph_builder_core.model.styles import (
    base_style, effective_style, vertex_label_visible, vertex_text_color,
)


NODE_RADIUS = 17
EDGE_STROKE_WIDTH = 2.6
COORDINATE_UNIT = 8 * NODE_RADIUS
DEFAULT_GRID_PRECISION = COORDINATE_UNIT / 4
SELECTION_COLOR = QColor('#15857f')
DRAG_THRESHOLD = 5
MINOR_GRID_COLOR = QColor('#e0e3e7')
SEMIBOLD_GRID_COLOR = QColor('#bcc4cc')
BOLD_GRID_COLOR = QColor('#7f8992')


def _display_edge_style(window, attributes):
    """Keep the document style intact while making default black edges visible in dark mode."""
    style = effective_style(window.graph, 'edge', attributes)
    if (getattr(window, 'theme_dark', False) and
            int(attributes.get('style', 0)) == 0 and
            QColor(style['stroke']) == QColor('#000000')):
        return dict(style, stroke='#ffffff')
    return style


def _point(pair):
    return QPointF(float(pair[0]), float(pair[1]))


def _label_font(size):
    font = QFont()
    font.setPointSize(size)
    return font


def draw_vertex_body(painter, style):
    """Draw a vertex at the painter origin, also used by the style sample."""
    size = float(style['size'])
    radius = size / 2
    kind = style['shape']
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
    return fill


def edge_pen(style):
    pattern = {'solid': Qt.SolidLine, 'dash': Qt.DashLine,
               'dot': Qt.DotLine, 'dashdot': Qt.DashDotLine}.get(style['pattern'], Qt.SolidLine)
    return QPen(QColor(style['stroke']), float(style['width']), pattern,
                Qt.RoundCap, Qt.RoundJoin)


def edge_arrow_path(tip, ux, uy, style):
    """The canvas arrowhead geometry, shared with the basic-style sample."""
    length = float(style.get('arrow_length', 11))
    half_width = float(style.get('arrow_width', 10)) / 2
    back = tip - QPointF(ux * length, uy * length)
    left = back - QPointF(uy * half_width, -ux * half_width)
    right = back + QPointF(uy * half_width, -ux * half_width)
    arrow = QPainterPath(tip)
    arrow.lineTo(left)
    shape = style.get('arrow_shape', 'triangle')
    if shape == 'stealth':
        arrow.lineTo(tip - QPointF(ux * length * .62, uy * length * .62))
    elif shape == 'latex':
        arrow.lineTo(tip - QPointF(ux * length * .78, uy * length * .78))
    arrow.lineTo(right)
    arrow.closeSubpath()
    return arrow


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
        if vertex_label_visible(self.window.graph, self.window.graph.nodes[self.node]):
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
        if style['shape'] == 'none' and vertex_label_visible(self.window.graph, self.window.graph.nodes[self.node]):
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
        draw_vertex_body(painter, style)
        if self.isSelected() or kind == 'none':
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(SELECTION_COLOR if self.isSelected() else QColor('#aeb7bb'),
                                2 if self.isSelected() else 1, Qt.DashLine))
            painter.drawEllipse(QPointF(0, 0), max(radius + 4, NODE_RADIUS),
                                max(radius + 4, NODE_RADIUS))
        if (any(self.node in group.nodes for group in self.window._staged_sets) or
                self.node in self.window._full_join_first or
                self.node in self.window._product_first or
                self.node in self.window._morphism_first or
                self.node in self.window._minor_first or
                self.node in self.window._subgraph_first):
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
        if vertex_label_visible(self.window.graph, self.window.graph.nodes[self.node]):
            label = vertex_label(self.window.graph, self.node)
            font = _label_font(13)
            path = QPainterPath()
            metrics = QFontMetricsF(font)
            bounds = metrics.boundingRect(label)
            path.addText(-bounds.width()/2, (metrics.ascent()-metrics.descent())/2, font, label)
            text_color = vertex_text_color(style)
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


class EdgeItem(QGraphicsPathItem):
    def __init__(self, window, source, target, key=None):
        super().__init__()
        self.window = window
        self.source = source
        self.target = target
        self.key = key
        self._visible_path = QPainterPath()
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
        visible = QPainterPath()
        for index, (start, c1, c2, end) in enumerate(visible_edge_cubics(
                self.window.graph, self.source, self.target, self.key)):
            if index == 0:
                visible.moveTo(_point(start))
            visible.cubicTo(_point(c1), _point(c2), _point(end))
        self.prepareGeometryChange()
        self._visible_path = visible
        self.setPath(path)
        style = _display_edge_style(self.window, edge_data(self.window.graph, self.source, self.target, self.key))
        self.setPen(QPen(QColor(style['stroke']), float(style['width'])))
        self.update()

    def _appearance(self):
        if self.source in self.window.graph and self.window.graph.has_edge(self.source, self.target):
            return _display_edge_style(self.window,
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
        return self._visible_path.pointAtPercent(1)

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
        rect = super().boundingRect().united(self._visible_path.boundingRect()).adjusted(
            -padding, -padding, padding, padding)
        if self.window and self.source in self.window.graph and self.window.graph.has_edge(self.source, self.target):
            if labels_visible(self.window.graph) and edge_label(self.window.graph, self.source, self.target, self.key):
                rect = rect.united(self._label_rect())
        return rect

    def shape(self):
        from PySide6.QtGui import QPainterPathStroker
        stroke = QPainterPathStroker()
        style = self._appearance()
        stroke.setWidth(max(12, float(style['width']) + 6))
        shape = stroke.createStroke(self._visible_path)
        if labels_visible(self.window.graph) and edge_label(self.window.graph, self.source, self.target, self.key):
            shape.addRect(self._label_rect())
        return shape

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        style = self._appearance()
        color = QColor(style['stroke'])
        width = float(style['width'])
        painter.setBrush(Qt.NoBrush)
        identity = EdgeRef(self.source, self.target, self.window.is_directed, self.key)
        if any(identity in group.edges for group in self.window._staged_sets):
            painter.setPen(QPen(QColor('#b87514'), width + 6, Qt.DashLine,
                                Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(self._visible_path)
        if self.isSelected():
            painter.setPen(QPen(SELECTION_COLOR, width + 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(self._visible_path)
        painter.setOpacity(float(style['opacity']))
        painter.setPen(edge_pen(style))
        painter.drawPath(self._visible_path)
        if float(style['opacity']) == 0:
            painter.setOpacity(1)
            painter.setPen(QPen(QColor('#c5cbd0'), max(1, width), Qt.DotLine))
            painter.drawPath(self._visible_path)
            painter.setOpacity(0)
        if self.window.is_directed and self._visible_path.length() > 1:
            tip = self.arrow_tip()
            control = self._visible_path.elementAt(self._visible_path.elementCount()-2)
            dx, dy = tip.x() - control.x, tip.y() - control.y
            length = hypot(dx, dy)
            if length:
                ux, uy = dx/length, dy/length
                shape = style.get('arrow_shape', 'triangle')
                arrow = edge_arrow_path(tip, ux, uy, style)
                if self.isSelected():
                    painter.setPen(QPen(SELECTION_COLOR, 5, Qt.SolidLine,
                                        Qt.RoundCap, Qt.RoundJoin))
                    painter.setBrush(SELECTION_COLOR)
                    painter.drawPath(arrow)
                painter.setPen(QPen(color, 1, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                painter.setBrush(Qt.NoBrush if shape == 'open' else color)
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


class RegionAnchorHandle(RegionCurveHandle):
    """Movable region-only boundary point, shared by its adjoining segments."""

    def __init__(self, window, region_id, anchor_index):
        super().__init__(window, region_id, anchor_index, -1, (0, 0))
        self.setBrush(QColor('#57a7bd'))
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.sync_position()

    def current_position(self):
        region = region_by_id(self.window.graph, self.region_id)
        if region is None:
            return None
        if region['mode'] == 'path':
            segments = region.get('segments', [])
            if self.segment_index < len(segments):
                return segments[self.segment_index].get('source_point')
        else:
            anchors = region.get('anchors', [])
            if self.segment_index < len(anchors):
                anchor = anchors[self.segment_index]
                return anchor.get('point') if isinstance(anchor, dict) else None
        return None

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged and not self._syncing:
            region = region_by_id(self.window.graph, self.region_id)
            if region is not None:
                point = [value.x(), value.y()]
                if region['mode'] == 'path':
                    segments = region.get('segments', [])
                    if self.segment_index < len(segments):
                        segments[self.segment_index]['source_point'] = point
                        segments[self.segment_index - 1]['target_point'] = point.copy()
                        update_region(self.window.graph, self.region_id, {'segments': segments})
                else:
                    anchors = region.get('anchors', [])
                    if self.segment_index < len(anchors):
                        anchors[self.segment_index]['point'] = point
                        update_region(self.window.graph, self.region_id, {'anchors': anchors})
                self.window.refresh_regions()
        return QGraphicsEllipseItem.itemChange(self, change, value)
