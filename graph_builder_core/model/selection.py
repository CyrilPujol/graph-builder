"""Selection support for Graph Builder."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from graph_builder_core.model.document import unused_label
from graph_builder_core.model.edges import edge_records, add_edge, has_edge


@dataclass(frozen=True)
class EdgeRef:
    source: Any
    target: Any
    directed: bool
    key: Any = None

    def __hash__(self):
        return hash((self.key, self.directed, (self.source, self.target) if self.directed else frozenset((self.source, self.target))))

    def __eq__(self, other):
        if not isinstance(other, EdgeRef) or self.directed != other.directed or self.key != other.key:
            return False
        return ((self.source, self.target) == (other.source, other.target) if self.directed
                else frozenset((self.source, self.target)) == frozenset((other.source, other.target)))


@dataclass
class SelectionState:
    nodes: set = field(default_factory=set)
    edges: set = field(default_factory=set)
    regions: set = field(default_factory=set)

    def clear(self):
        self.nodes.clear()
        self.edges.clear()
        self.regions.clear()

    def single_node(self):
        return next(iter(self.nodes)) if len(self.nodes) == 1 and not self.edges and not self.regions else None

    def prune(self, graph):
        self.nodes.intersection_update(graph.nodes)
        self.edges = {edge for edge in self.edges if has_edge(graph, edge.source, edge.target, edge.key)}
        from graph_builder_core.model.regions import regions
        self.regions.intersection_update(region['id'] for region in regions(graph))


@dataclass
class SelectionSnapshot:
    """Public snapshot for ``selection='any'``.

    ``nodes`` contains vertex IDs, ``edges`` contains NetworkX edge tuples,
    and ``regions`` contains region IDs. Its sets are independent of the UI.
    """

    nodes: set = field(default_factory=set)
    edges: set = field(default_factory=set)
    regions: set = field(default_factory=set)


def selection_matches(selection, kind, *, nonempty=False):
    """Check a button input without changing the current selection."""
    if kind == 'vertex':
        return selection.single_node() is not None
    if kind == 'edge':
        return len(selection.edges) == 1 and not selection.nodes
    if not nonempty:
        return True
    if kind == 'vertices':
        return bool(selected_vertices(selection))
    if kind == 'edges':
        return bool(selection.edges)
    return bool(selection.nodes or selection.edges or selection.regions)


def capture_selection(selection, kind):
    """Capture only the objects requested by one button input."""
    if kind in ('vertex', 'vertices'):
        return SelectionState(nodes=(set(selection.nodes) if kind == 'vertex'
                                     else selected_vertices(selection)))
    if kind in ('edge', 'edges'):
        return SelectionState(edges=set(selection.edges))
    return copy.deepcopy(selection)


def selection_argument(selection, kind, multigraph):
    """Convert a captured selection to a normal callback argument."""
    def edge_tuple(edge):
        return ((edge.source, edge.target, edge.key) if multigraph
                else (edge.source, edge.target))

    if kind == 'vertex':
        return next(iter(selection.nodes))
    if kind == 'vertices':
        return set(selection.nodes)
    if kind == 'edge':
        return edge_tuple(next(iter(selection.edges)))
    edges = {edge_tuple(edge) for edge in selection.edges}
    if kind == 'edges':
        return edges
    return SelectionSnapshot(set(selection.nodes), edges, set(selection.regions))


def selected_vertices(selection):
    """Include the endpoints of selected edges in a vertex selection."""
    vertices = set(selection.nodes)
    for edge in selection.edges:
        vertices.update((edge.source, edge.target))
    return vertices


@dataclass
class GraphClipboard:
    nodes: tuple
    node_attributes: dict
    internal_edges: tuple
    boundary_edges: tuple
    regions: tuple = ()


def copy_graph_selection(graph, selected_nodes=None):
    selected = set(graph.nodes) if selected_nodes is None else set(selected_nodes) & set(graph)
    nodes = tuple(node for node in graph if node in selected)
    internal, boundary = [], []
    for source, target, key, data in edge_records(graph):
        if source in selected and target in selected:
            internal.append((source, target, key, copy.deepcopy(data)))
        elif source in selected or target in selected:
            boundary.append((source, target, key, copy.deepcopy(data)))
    from graph_builder_core.model.regions import regions
    def referenced_nodes(region):
        if region['mode'] in ('hull', 'bag'):
            return set(region['nodes'])
        return {node for segment in region.get('segments', [])
                for node in (segment['source'], segment['target']) if node is not None}
    copied_regions = tuple(copy.deepcopy(region) for region in regions(graph)
                           if referenced_nodes(region) <= selected)
    return GraphClipboard(nodes, {node: copy.deepcopy(dict(graph.nodes[node])) for node in nodes},
                          tuple(internal), tuple(boundary), copied_regions)


def paste_graph_selection(graph, clipboard, offset=(20, 20), *, return_regions=False):
    output = copy.deepcopy(graph)
    mapping = {}
    for old in clipboard.nodes:
        new = unused_label(output)
        data = copy.deepcopy(clipboard.node_attributes[old])
        x, y = data.get('position', (0, 0))
        data['position'] = (x + offset[0], y + offset[1])
        output.add_node(new, **data)
        mapping[old] = new
    for source, target, key, data in (*clipboard.internal_edges, *clipboard.boundary_edges):
        if source in mapping or target in mapping:
            new_source, new_target = mapping.get(source, source), mapping.get(target, target)
            if new_source in output and new_target in output:
                add_edge(output, new_source, new_target, data, key)
    from graph_builder_core.model.regions import add_region
    region_ids = set()
    for region in clipboard.regions:
        remapped = copy.deepcopy(region)
        remapped['nodes'] = [mapping[node] for node in region.get('nodes', [])]
        if 'anchors' in remapped:
            remapped['anchors'] = [({'point': [anchor['point'][0] + offset[0],
                                                 anchor['point'][1] + offset[1]]}
                                    if isinstance(anchor, dict) else mapping[anchor])
                                   for anchor in remapped['anchors']]
        for segment in remapped.get('segments', []):
            for field in ('source', 'target', 'edge_source', 'edge_target'):
                if field in segment and segment[field] is not None:
                    segment[field] = mapping[segment[field]]
            for field in ('source_point', 'target_point'):
                if field in segment:
                    segment[field] = [segment[field][0] + offset[0],
                                      segment[field][1] + offset[1]]
        identifier = add_region(output, mode=remapped['mode'], nodes=remapped['nodes'],
                                segments=remapped['segments'], label=remapped['label'],
                                style=remapped['style'], margin=remapped.get('margin', 0),
                                anchors=remapped.get('anchors'))
        region_ids.add(identifier)
    if return_regions:
        return output, set(mapping.values()), region_ids
    return output, set(mapping.values())
