"""Bounded graph homomorphism search and appearance lifting.

The two selected vertex sets induce G and H. A homomorphism may identify
vertices, but every directed arc or undirected edge of G must map to one in H.
Parallel edges impose the same adjacency condition as a single edge.
"""
from __future__ import annotations

import networkx as nx

from graph_builder_core.model.edges import edge_data, visible_edges
from graph_builder_core.model.styles import (
    basic_index_for_appearance, effective_style, has_custom_look, use_basic_style,
)


MAX_VERTICES_PER_SIDE = 180
MAX_TABLE_ENTRIES = 1_000_000


def _simple(graph):
    return nx.DiGraph(graph) if graph.is_directed() else nx.Graph(graph)


def find_morphism(graph, sources, targets, seconds=60, workers=4):
    """Return status and a mapping, using the shared CP-SAT solver.

    Status is ``found``, ``none``, or ``timeout``. A timeout is never
    presented as proof that no morphism exists.
    """
    from graph_builder_core.algorithms.optimization import _solver

    sources, targets = set(sources), set(targets)
    if not sources or not targets or not sources <= set(graph) or not targets <= set(graph):
        raise ValueError('Select nonempty vertex sets that exist in the graph.')
    if max(len(sources), len(targets)) > MAX_VERTICES_PER_SIDE:
        raise ValueError(f'Morphism search is limited to {MAX_VERTICES_PER_SIDE} vertices per set.')
    simple = _simple(graph)
    source = simple.subgraph(sources)
    target = simple.subgraph(targets)
    source_nodes = sorted(source, key=str)
    target_nodes = sorted(target, key=str)
    target_index = {node: index for index, node in enumerate(target_nodes)}
    allowed = {(target_index[u], target_index[v]) for u, v in target.edges()}
    if not target.is_directed():
        allowed |= {(v, u) for u, v in allowed}
    source_edges = list(source.edges())
    if len(source_edges) * max(1, len(allowed)) > MAX_TABLE_ENTRIES:
        raise ValueError('Morphism search is too large for the editor’s current limit.')
    if source_edges and not allowed:
        return {'status': 'none', 'mapping': []}
    cp_model, solver = _solver(seconds, workers)
    model = cp_model.CpModel()
    image = {node: model.new_int_var(0, len(target_nodes) - 1, f'image_{index}')
             for index, node in enumerate(source_nodes)}
    for u, v in source_edges:
        if u == v:
            loop_images = [(index,) for index in range(len(target_nodes)) if (index, index) in allowed]
            if not loop_images:
                return {'status': 'none', 'mapping': []}
            model.add_allowed_assignments([image[u]], loop_images)
        else:
            model.add_allowed_assignments([image[u], image[v]], sorted(allowed))
    status = solver.solve(model)
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {'status': 'found',
                'mapping': [[node, target_nodes[solver.value(image[node])]]
                            for node in source_nodes]}
    if status == cp_model.INFEASIBLE:
        return {'status': 'none', 'mapping': []}
    return {'status': 'timeout', 'mapping': []}


def _edge_identity(graph, source, target):
    return (source, target) if graph.graph.get('graph_type') != 'graph' else frozenset((source, target))


def lift_morphism_styles(graph, sources, targets, mapping, *, allow_extra_edges=False,
                         highlight_uncolored=False, highlight_uncolored_edges=True):
    """Lift H's basic style indices to G without creating custom looks.

    Labels, positions, endpoints and curve points are untouched. If H is
    uniform, its vertices first receive distinct basic styles 1..|H|.
    Subgraph witnesses can instead give a wholly uncolored H one shared style.
    Overlapping G/H objects ultimately display the lifted source appearance.
    """
    sources, targets = set(sources), set(targets)
    mapping = dict(mapping)
    if set(mapping) != sources or not set(mapping.values()) <= targets:
        raise ValueError('The morphism no longer matches the selected vertices.')
    vertex_looks = [effective_style(graph, 'vertex', graph.nodes[node]) for node in targets]
    target_edges = [(u, v, key, data) for u, v, key, data in visible_edges(graph)
                    if u in targets and v in targets]
    edge_looks = [effective_style(graph, 'edge', data) for _, _, _, data in target_edges]
    vertex_uniform = all(style == vertex_looks[0] for style in vertex_looks[1:])
    edge_uniform = not edge_looks or all(style == edge_looks[0] for style in edge_looks[1:])
    uncolored = (all(int(graph.nodes[node].get('style', 0)) == 0 and
                     not has_custom_look(graph.nodes[node]) for node in targets)
                 and all(int(data.get('style', 0)) == 0 and not has_custom_look(data)
                         for _, _, _, data in target_edges))
    auto_colored = uncolored if highlight_uncolored else vertex_uniform and edge_uniform
    if auto_colored and highlight_uncolored:
        graph.graph['num_vertex_styles'] = max(int(graph.graph.get('num_vertex_styles', 1)), 2)
        for node in targets:
            use_basic_style(graph.nodes[node], 1)
        if highlight_uncolored_edges:
            graph.graph['num_edge_styles'] = max(int(graph.graph.get('num_edge_styles', 1)), 2)
            for u, v, key, _ in target_edges:
                use_basic_style(edge_data(graph, u, v, key), 1)
                if graph.graph.get('graph_type') == 'graph' and u != v:
                    use_basic_style(edge_data(graph, v, u, key), 1)
    elif auto_colored:
        graph.graph['num_vertex_styles'] = max(graph.graph['num_vertex_styles'], len(targets) + 1)
        for color, node in enumerate(sorted(targets, key=str), 1):
            attributes = graph.nodes[node]
            attributes['style'] = color
            attributes.pop('style_overrides', None)
            attributes.pop('style_preset', None)

    # Snapshot H before changing any source object, since G and H may overlap.
    vertex_snapshots = {
        node: (int(graph.nodes[node].get('style', 0)) if auto_colored else
               basic_index_for_appearance(graph, 'vertex',
                                          effective_style(graph, 'vertex', graph.nodes[node])))
        for node in targets
    }
    edge_snapshots = {}
    for u, v, key, data in target_edges:
        identity = _edge_identity(graph, u, v)
        edge_snapshots.setdefault(identity,
            basic_index_for_appearance(graph, 'edge', effective_style(graph, 'edge', data)))
    source_edges = [(u, v, key) for u, v, key, _ in visible_edges(graph)
                    if u in sources and v in sources]
    for node in sources:
        use_basic_style(graph.nodes[node], vertex_snapshots[mapping[node]])
    for u, v, key in source_edges:
        identity = _edge_identity(graph, mapping[u], mapping[v])
        if identity not in edge_snapshots and not allow_extra_edges:
            raise ValueError('The morphism witness contains an edge absent from the target.')
        color = edge_snapshots.get(identity, 0)
        use_basic_style(edge_data(graph, u, v, key), color)
        if graph.graph.get('graph_type') == 'graph' and u != v:
            use_basic_style(edge_data(graph, v, u, key), color)
    graph.graph['num_vertex_styles'] = max(
        int(graph.graph.get('num_vertex_styles', 1)),
        max(vertex_snapshots.values(), default=0) + 1)
    graph.graph['num_edge_styles'] = max(
        int(graph.graph.get('num_edge_styles', 1)),
        max(edge_snapshots.values(), default=0) + 1)
    return auto_colored
