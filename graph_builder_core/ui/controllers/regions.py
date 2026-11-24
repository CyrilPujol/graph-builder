"""RegionController methods hosted by GraphBuilderQt."""
from __future__ import annotations

from math import hypot

from PySide6.QtCore import QPointF

from graph_builder_core.model.regions import (
    add_region, cycle_from_edges, hull_region_nodes, path_segment, region_points,
    valid_boundary,
)
from graph_builder_core.model.selection import EdgeRef, SelectionState
from graph_builder_core.ui.items import EdgeItem, NodeItem


class RegionController:
    def _cancel_region_path(self):
        self.region_path = None
        self.make_region_action.setChecked(False)
        self.scene.set_region_hover(None)
        self.scene.set_region_preview(())
        self.scene.update()

    def make_region(self, checked=False):
        """Fill an edge cycle, a vertex hull, or start an interactive boundary."""
        if self.region_path is not None:
            self._cancel_region_path()
            self.update_actions()
            self.report('Region path cancelled.', 3)
            return
        if self.selection.edges:
            segments = cycle_from_edges(self.graph, self.selection.edges)
            if segments is not None:
                identifier = add_region(self.graph, mode='path', segments=segments)
                self.make_region_action.setChecked(False)
                self.selection = SelectionState(set(), set(), {identifier})
                self.rebuild_scene()
                self.commit_change()
                self.report('Region created from the selected edges.', 4)
                return
        elif self.selection.nodes:
            hull = hull_region_nodes(self.graph, self.selection.nodes)
            if hull is not None:
                nodes, margin = hull
                identifier = add_region(self.graph, mode='hull', nodes=nodes, margin=margin)
                self.make_region_action.setChecked(False)
                self.selection = SelectionState(set(), set(), {identifier})
                self.rebuild_scene()
                self.commit_change()
                self.report('Region created around the selected vertices.', 4)
                return
        self.scene.clearSelection()
        self.region_path = {'start': None, 'end': None, 'segments': []}
        self.make_region_action.setChecked(True)
        self.update_actions()
        self.report('Click vertices, adjacent edges, or empty space to trace a boundary. Enter closes it, Esc cancels.', 8)

    def _region_anchor_position(self, anchor):
        return anchor if isinstance(anchor, tuple) else self.graph.nodes[anchor]['position']

    def _region_path_candidate(self, item, position):
        """Resolve a hovered graph item or a free boundary point."""
        path = self.region_path
        if isinstance(item, NodeItem):
            if item.node == path['end']:
                return None, None, False
            return item.node, None, True
        if isinstance(item, EdgeItem):
            first, second = item.source, item.target
            if path['end'] is None:
                return second, path_segment(first, second,
                    EdgeRef(first, second, self.is_directed, item.key)), True
            if path['end'] in (first, second):
                following = second if path['end'] == first else first
                return following, path_segment(path['end'], following,
                    EdgeRef(first, second, self.is_directed, item.key)), True
            return None, None, False
        point = (float(position.x()), float(position.y())) if isinstance(position, QPointF) else position
        if point is None:
            return None, None, False
        if isinstance(path['start'], tuple) and len(path['segments']) >= 2:
            start = self._region_anchor_position(path['start'])
            if hypot(point[0] - start[0], point[1] - start[1]) <= 14:
                return path['start'], None, True
        return tuple(point), None, True

    def region_path_hover(self, item, position):
        """Preview the boundary and enclosed area if the hovered point is clicked."""
        if self.region_path is None:
            return
        path = self.region_path
        anchor, edge_segment, valid = self._region_path_candidate(item, position)
        self.scene.set_region_hover(item if valid else None)
        if not valid or anchor is None:
            self.scene.set_region_preview(region_points(
                self.graph, {'mode': 'path', 'segments': path['segments']}))
            return
        if path['start'] is None:
            points = (self._region_anchor_position(anchor),)
            if edge_segment is not None:
                points = region_points(self.graph, {'mode': 'path', 'segments': [edge_segment]})
            self.scene.set_region_preview(points)
            return
        segments = list(path['segments'])
        if anchor != path['end']:
            segments.append(edge_segment or path_segment(path['end'], anchor))
        points = region_points(self.graph, {'mode': 'path', 'segments': segments})
        closed = False
        if anchor != path['start'] and len(segments) >= 2:
            closing = path_segment(anchor, path['start'])
            candidate = segments + [closing]
            closed = valid_boundary(self.graph, candidate)
        elif anchor == path['start'] and len(segments) >= 3:
            closed = valid_boundary(self.graph, segments)
        self.scene.set_region_preview(points, close=closed)

    def region_path_click(self, item, position=None):
        """Advance an interactive region path by a vertex, edge, or free point."""
        if self.region_path is None:
            return
        path = self.region_path
        anchor, edge_segment, valid = self._region_path_candidate(item, position)
        if not valid:
            self.report('Choose an edge touching the end of the boundary.', 4)
            return
        if anchor is None:
            return
        if edge_segment is not None and path['start'] is None:
            path['start'] = edge_segment['source']
            path['end'] = anchor
            path['segments'].append(edge_segment)
            if path['start'] == anchor:
                self._close_region_path(path['segments'])
                return
        elif path['start'] is None:
            path['start'] = path['end'] = anchor
            self.scene.set_region_preview((self._region_anchor_position(anchor),))
            self.report('Boundary started. Click another point or an adjacent edge.', 5)
            return
        elif anchor != path['end']:
            candidate = path['segments'] + [edge_segment or path_segment(path['end'], anchor)]
            if anchor == path['start']:
                self._close_region_path(candidate)
                return
            path['segments'] = candidate
            path['end'] = anchor
        self.scene.set_region_hover(None)
        self.scene.set_region_preview(region_points(
            self.graph, {'mode': 'path', 'segments': path['segments']}))
        self.scene.update()

    def _close_region_path(self, segments):
        if not valid_boundary(self.graph, segments):
            self.report('The boundary needs to enclose a visible area.', 4)
            return
        identifier = add_region(self.graph, mode='path', segments=segments)
        self._cancel_region_path()
        self.selection = SelectionState(set(), set(), {identifier})
        self.rebuild_scene()
        self.commit_change()
        self.report('Region created. Double-click it to edit its look.', 5)

    def finish_region_path(self):
        """Close an interactive boundary from its current end to its start."""
        path = self.region_path
        if path is None:
            return
        if path['start'] is None or path['end'] == path['start']:
            self.report('Add boundary points before closing the region.', 4)
            return
        self._close_region_path(path['segments'] +
                                [path_segment(path['end'], path['start'])])
