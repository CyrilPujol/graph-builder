"""Hull and round polygon offsets shared by canvas regions and TikZ export."""
from math import hypot


def _hull(points):
    points = sorted(set((float(x), float(y)) for x, y in points))
    if len(points) <= 1:
        return points

    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    lower = []
    for point in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper = []
    for point in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def _area(points):
    return abs(_signed_area(points))


def _signed_area(points):
    return (sum(x * points[(i + 1) % len(points)][1]
                - points[(i + 1) % len(points)][0] * y
                for i, (x, y) in enumerate(points)) / 2
            if len(points) >= 3 else 0)


def _offset_polygon(points, padding):
    """Approximate a segment's padded position for its edit handle."""
    points = [(float(x), float(y)) for x, y in points]
    if len(points) < 3 or not padding:
        return points
    closed = hypot(points[0][0] - points[-1][0],
                   points[0][1] - points[-1][1]) < 1e-7
    outline = points[:-1] if closed else points
    if len(outline) < 3:
        return points
    signed_area = sum(x * outline[(i + 1) % len(outline)][1]
                      - outline[(i + 1) % len(outline)][0] * y
                      for i, (x, y) in enumerate(outline))
    side = 1 if signed_area >= 0 else -1
    normals = []
    for index, (x, y) in enumerate(outline):
        next_x, next_y = outline[(index + 1) % len(outline)]
        dx, dy = next_x - x, next_y - y
        length = hypot(dx, dy)
        normals.append((side * dy / length, -side * dx / length)
                       if length > 1e-9 else (0.0, 0.0))
    result = []
    for index, (x, y) in enumerate(outline):
        before, after = normals[index - 1], normals[index]
        dot = before[0]*after[0] + before[1]*after[1]
        divisor = max(.08, 1 + dot)
        offset_x = padding * (before[0] + after[0]) / divisor
        offset_y = padding * (before[1] + after[1]) / divisor
        length = hypot(offset_x, offset_y)
        limit = 4 * abs(padding)
        if length > limit:
            offset_x *= limit / length
            offset_y *= limit / length
        result.append((x + offset_x, y + offset_y))
    return result + [result[0]] if closed else result


def _buffer_polygons(points, padding):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPainterPath, QPainterPathStroker

    """Disk dilation or erosion of a filled polygon, including rounded corners."""
    if len(points) < 3 or _area(points) <= 1e-8:
        return []
    path = QPainterPath()
    path.moveTo(*points[0])
    for point in points[1:]:
        path.lineTo(*point)
    path.closeSubpath()
    path.setFillRule(Qt.OddEvenFill)
    if padding:
        stroker = QPainterPathStroker()
        stroker.setWidth(2 * abs(padding))
        stroker.setJoinStyle(Qt.RoundJoin)
        stroker.setCapStyle(Qt.RoundCap)
        stroke = stroker.createStroke(path)
        path = path.united(stroke) if padding > 0 else path.subtracted(stroke)
    polygons = [[(point.x(), point.y()) for point in polygon]
                for polygon in path.toSubpathPolygons()]
    return [polygon for polygon in polygons if _area(polygon) > 1e-6]
