"""Guides support for Graph Builder."""
from __future__ import annotations

from math import atan2, ceil, cos, floor, hypot, pi, sin, sqrt


def radial_grid_divisions(ring, main_divisions):
    """Increase spoke density on outer rings to keep grid cells useful."""
    if ring <= 0:
        return main_divisions
    cell_threshold = 1 / sqrt(2)
    minimum_ring = max(1, ceil(cell_threshold / (2*sin(pi/main_divisions)) - 1e-12))
    if ring < minimum_ring:
        return 0
    divisions = main_divisions
    while 2*ring*sin(pi/(2*divisions)) >= cell_threshold - 1e-9:
        divisions *= 2
    return divisions


def radial_grid_new_spokes(maximum_radius, unit, main_divisions):
    """Yield (start radius, angular index, divisions) for new radial half-lines."""
    previous_divisions = main_divisions
    for ring in range(1, min(1000, ceil(maximum_radius / unit) + 1)):
        divisions = radial_grid_divisions(ring, main_divisions)
        if divisions > previous_divisions:
            step = divisions // previous_divisions
            for index in range(divisions):
                if index % step:
                    yield ring * unit, index, divisions
            previous_divisions = divisions


def triangular_grid_point(i, j, center=(0, 0), unit=30):
    """A triangular-lattice vertex in the horizontal-row basis."""
    return (center[0] + unit * (i + j / 2),
            center[1] + unit * sqrt(3) * j / 2)


def triangular_grid_coordinates(position, center=(0, 0), unit=30):
    """Inverse of ``triangular_grid_point`` for continuous lattice indices."""
    j = (position[1] - center[1]) / (unit * sqrt(3) / 2)
    return (position[0] - center[0]) / unit - j / 2, j


def triangular_grid_lines(bounds, center=(0, 0), unit=30, minor_step=1,
                          major_step=1):
    """Yield clipped (family, index, start, end) lines of the same lattice.

    Families are the constant-j, constant-i, and constant-(i+j) lines.
    The optional strides omit visually overcrowded minor lines, while always
    retaining integer-coordinate-unit lines via ``major_step``.
    """
    left, top, right, bottom = bounds
    corners = ((left, top), (left, bottom), (right, top), (right, bottom))
    coordinates = []
    for corner in corners:
        i, j = triangular_grid_coordinates(corner, center, unit)
        coordinates.append((j, i, i + j))
    directions = ((1.0, 0.0), (0.5, sqrt(3) / 2),
                  (-0.5, sqrt(3) / 2))
    for family, direction in enumerate(directions):
        first = floor(min(value[family] for value in coordinates)) - 1
        last = ceil(max(value[family] for value in coordinates)) + 1
        indices = (set(range(first - first % minor_step, last + 1, minor_step)) |
                   set(range(first - first % major_step, last + 1, major_step)) |
                   {0})
        dx, dy = direction
        for index in sorted(indices):
            x0, y0 = triangular_grid_point(0 if family == 0 else index,
                                           index if family == 0 else 0,
                                           center, unit)
            low, high = float('-inf'), float('inf')
            for coordinate, delta, minimum, maximum in (
                    (x0, dx, left, right), (y0, dy, top, bottom)):
                if abs(delta) < 1e-12:
                    if coordinate < minimum or coordinate > maximum:
                        break
                else:
                    one, two = (minimum - coordinate) / delta, (maximum - coordinate) / delta
                    low, high = max(low, min(one, two)), min(high, max(one, two))
            else:
                if low <= high:
                    yield (family, index, (x0 + low * dx, y0 + low * dy),
                           (x0 + high * dx, y0 + high * dy))


def nearest_grid_point(position, mode, center=(0, 0), unit=30, radial_divisions=5):
    if mode == 'square':
        return tuple(center[i] + round((position[i] - center[i]) / unit)*unit for i in (0, 1))
    if mode == 'triangular':
        i, j = triangular_grid_coordinates(position, center, unit)
        best, best_distance = None, float('inf')
        # The closest point in this 60-degree basis is among the four corners
        # of the lattice-coordinate cell. Iterate j, then i for stable ties.
        for row in (floor(j), floor(j) + 1):
            for column in (floor(i), floor(i) + 1):
                candidate = triangular_grid_point(column, row, center, unit)
                distance = ((candidate[0] - position[0]) ** 2 +
                            (candidate[1] - position[1]) ** 2)
                if distance < best_distance - 1e-12 * unit * unit:
                    best, best_distance = candidate, distance
        return best
    if mode != 'radial':
        return position
    dx, dy = position[0] - center[0], position[1] - center[1]
    radius = hypot(dx, dy)
    base_ring = round(radius / unit)
    best, best_distance = center, radius
    minimum_ring = max(1, ceil((1/sqrt(2)) / (2*sin(pi/radial_divisions)) - 1e-12))
    for ring in range(max(minimum_ring, base_ring - 1), max(minimum_ring, base_ring + 2) + 1):
        divisions = radial_grid_divisions(ring, radial_divisions)
        angle = atan2(dy, dx)
        index = round(((angle + pi/2) % (2*pi)) / (2*pi/divisions)) % divisions
        candidate_angle = -pi/2 + 2*pi*index/divisions
        candidate = (round(center[0] + ring*unit*cos(candidate_angle), 12),
                     round(center[1] + ring*unit*sin(candidate_angle), 12))
        distance = hypot(position[0]-candidate[0], position[1]-candidate[1])
        if distance < best_distance:
            best, best_distance = candidate, distance
    return best


def axis_alignment_plan(moved_positions, reference_positions, pixels_per_unit=1.0,
                        axis_visible=(False, False), origin_visible=False,
                        include_matches=False):
    """Find a shared translation and the guide lines that explain it.

    Each coordinate is independent, so a horizontal and vertical alignment may
    use different reference vertices. Distances are measured in screen pixels
    for consistent behavior at every zoom level. Farther references require a
    closer alignment before they attract the moved group. ``axis_visible`` is
    (vertical axis, horizontal axis). An axis has zero along-line separation.
    When requested, return the moved and reference indices behind each guide.
    A virtual axis target has no reference index.
    """
    if pixels_per_unit <= 0:
        empty = ((0.0, 0.0), ())
        return (*empty, ()) if include_matches else empty
    moved_positions = list(moved_positions)
    references = list(reference_positions)
    if origin_visible and (0, 0) not in references:
        references.append((0.0, 0.0))
    offsets = [0.0, 0.0]
    guides = []
    matches = []
    for axis in (0, 1):
        best = None
        for moved_index, moved in enumerate(moved_positions):
            for reference_index, reference in enumerate(references):
                gap = abs(moved[axis] - reference[axis]) * pixels_per_unit
                separation = abs(moved[1-axis] - reference[1-axis]) * pixels_per_unit
                threshold = 18 / (1 + separation / 240)
                if gap <= threshold:
                    score = (gap / threshold, gap, separation, tuple(moved), tuple(reference))
                    if best is None or score < best[0]:
                        projected = ((reference[0], moved[1]) if axis == 0 else
                                     (moved[0], reference[1]))
                        best = (score, reference[axis] - moved[axis],
                                (tuple(reference), projected), moved_index, reference_index)
            if axis_visible[axis]:
                gap = abs(moved[axis]) * pixels_per_unit
                if gap <= 18:
                    projected = ((0.0, moved[1]) if axis == 0 else
                                 (moved[0], 0.0))
                    score = (gap / 18, gap, 0.0, tuple(moved), projected)
                    if best is None or score < best[0]:
                        best = (score, -moved[axis], ((0.0, 0.0), projected),
                                moved_index, None)
        if best is not None:
            offsets[axis] = best[1]
            guides.append(best[2])
            matches.append((best[3], best[4]))
    result = (tuple(offsets), tuple(guides))
    return (*result, tuple(matches)) if include_matches else result


def axis_alignment_offset(moved_positions, reference_positions, pixels_per_unit=1.0):
    """Return only the translation of an alignment plan."""
    return axis_alignment_plan(moved_positions, reference_positions,
                               pixels_per_unit)[0]


def snap_unselected_vertices(graph, selected_nodes, mode, center=(0, 0), unit=30,
                             radial_divisions=5):
    """Snap vertices outside the active selection, returning changed positions."""
    if mode not in ('square', 'triangular', 'radial'):
        return {}
    changed = {}
    for node, attributes in graph.nodes(data=True):
        if node in selected_nodes:
            continue
        old = attributes['position']
        new = nearest_grid_point(old, mode, center, unit, radial_divisions)
        if hypot(old[0] - new[0], old[1] - new[1]) > 1e-9:
            attributes['position'] = new
            changed[node] = new
    return changed
