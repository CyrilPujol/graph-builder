"""Edge identities shared by simple and parallel-edge documents."""
import copy

import networkx as nx


def edge_data(graph, source, target, key=None):
    if graph.is_multigraph():
        if key is None:
            key = next(iter(graph[source][target]))
        return graph.edges[source, target, key]
    return graph.edges[source, target]


def edge_records(graph):
    if graph.is_multigraph():
        yield from graph.edges(keys=True, data=True)
    else:
        for u, v, data in graph.edges(data=True):
            yield u, v, None, data


def visible_edges(graph):
    seen = set()
    for u, v, key, data in edge_records(graph):
        identity = ((u, v), key) if graph.graph.get('graph_type') != 'graph' else (frozenset((u, v)), key)
        if identity not in seen:
            seen.add(identity)
            yield u, v, key, data


def add_edge(graph, u, v, data, key=None):
    if graph.is_multigraph():
        return graph.add_edge(u, v, key=key, **copy.deepcopy(data))
    graph.add_edge(u, v, **copy.deepcopy(data))
    return None


def has_edge(graph, u, v, key=None):
    return graph.has_edge(u, v, key) if graph.is_multigraph() else graph.has_edge(u, v)


def remove_edge(graph, u, v, key=None):
    if has_edge(graph, u, v, key):
        if graph.is_multigraph():
            graph.remove_edge(u, v, key)
        else:
            graph.remove_edge(u, v)


def set_multiedges(graph, enabled):
    """Convert storage, retaining the first edge when parallel edges are disabled."""
    output = nx.MultiDiGraph() if enabled else nx.DiGraph()
    output.graph.update(copy.deepcopy(graph.graph))
    output.graph['multiedges'] = bool(enabled)
    output.add_nodes_from(copy.deepcopy(list(graph.nodes(data=True))))
    if enabled or graph.graph.get('graph_type') != 'graph':
        for u, v, key, data in edge_records(graph):
            if enabled or not output.has_edge(u, v):
                add_edge(output, u, v, data, key)
    else:
        # The undirected editor stores a mirrored arc for each logical edge.
        # Pick one whole pair so the two surviving arcs cannot have different
        # labels or looks after parallel edges are disabled.
        for u, v, _, data in visible_edges(graph):
            if output.has_edge(u, v) or output.has_edge(v, u):
                continue
            from graph_builder_core.geometry.curves import _edge_curve_points, _set_edge_curve_points
            old_key = next(iter(graph[u][v]))
            points = _edge_curve_points(graph, u, v, old_key)
            add_edge(output, u, v, data)
            if u != v:
                add_edge(output, v, u, data)
            if points:
                _set_edge_curve_points(output, u, v, points)
    return output
