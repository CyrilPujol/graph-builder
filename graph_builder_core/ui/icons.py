"""Vector toolbar icons."""
from __future__ import annotations

from math import cos, sin, pi, sqrt

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def _transformation_icon(kind, *, dark=False):
    """Compact, consistently weighted vector transformation icons."""
    image = QPixmap(52, 52)
    image.setDevicePixelRatio(2)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    color = QColor('#edf0f2' if dark else '#111111')
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


def _gear_icon(*, dark=False):
    """Draw a centered cog without platform-dependent font bearings."""
    image = QPixmap(48, 48)
    image.setDevicePixelRatio(2)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.translate(12, 12)
    painter.scale(0.9, 0.9)
    painter.translate(-12, -12)
    path = QPainterPath()
    for i in range(64):
        angle = 2 * pi * i / 64
        radius = 10 if i % 8 in (2, 3, 4, 5) else 7.8
        point = QPointF(12 + radius * cos(angle), 12 + radius * sin(angle))
        if i == 0:
            path.moveTo(point)
        else:
            path.lineTo(point)
    path.closeSubpath()
    path.addEllipse(QPointF(12, 12), 3.8, 3.8)
    painter.fillPath(path, QColor('#ffffff' if dark else '#2D2D2D'))
    painter.end()
    return QIcon(image)


def _search_icon(*, dark=False):
    image = QPixmap(48, 48)
    image.setDevicePixelRatio(2)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor('#ffffff' if dark else '#111111'), 2.1, Qt.SolidLine, Qt.RoundCap))
    painter.drawEllipse(QPointF(10, 10), 5.5, 5.5)
    painter.drawLine(QPointF(14, 14), QPointF(20, 20))
    painter.end()
    return QIcon(image)
