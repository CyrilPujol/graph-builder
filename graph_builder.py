"""Example graph-editor application with useful graph transformations."""

from __future__ import annotations

import argparse
import copy
from math import cos, pi, sin
import random

from graph_builder_lib import (
    Action,
    ContextAction,
    _edge_curve_points,
    _set_edge_curve_points,
    main,
    unused_label,
)


def _selected_nodes(selection):
    """Return vertices selected directly or through selected edges."""
    nodes = set(selection.nodes)
    for edge in selection.edges:
        nodes.update((edge.source, edge.target))
    return nodes


def twin(graph, vertices, return_new_vertices=False):
    """Add one twin for every selected vertex, using the original adjacency."""
    originals = [vertex for vertex in graph.nodes if vertex in vertices]
    if not originals:
        return (graph, set()) if return_new_vertices else graph
    directed = graph.graph.get('graph_type') != 'graph'
    original_edges = [
        (source, target, copy.deepcopy(attributes))
        for source, target, attributes in graph.edges(data=True)
    ]
    new_vertices = set()
    for index, vertex in enumerate(originals, start=1):
        new_vertex = unused_label(graph)
        new_vertices.add(new_vertex)
        x, y = graph.nodes[vertex]['position']
        graph.add_node(new_vertex, position=(x + 20 * index, y + 20 * index), col=graph.nodes[vertex]['col'])
        for source, target, attributes in original_edges:
            if source == vertex:
                graph.add_edge(new_vertex, target, **copy.deepcopy(attributes))
            if directed and target == vertex:
                graph.add_edge(source, new_vertex, **copy.deepcopy(attributes))
    return (graph, new_vertices) if return_new_vertices else graph


def contract(graph, vertices):
    """Contract selected vertices (or selected-edge endpoints) into one vertex."""
    vertices = set(vertices) & set(graph.nodes)
    if len(vertices) < 2:
        return graph
    new_vertex = unused_label(graph)
    positions = [graph.nodes[vertex]['position'] for vertex in vertices]
    position = (sum(x for x, _ in positions) / len(positions), sum(y for _, y in positions) / len(positions))
    new_graph = graph.__class__()
    new_graph.graph.update(copy.deepcopy(graph.graph))
    for vertex, attributes in graph.nodes(data=True):
        if vertex not in vertices:
            new_graph.add_node(vertex, **copy.deepcopy(attributes))
    representative = next(vertex for vertex in graph.nodes if vertex in vertices)
    new_graph.add_node(new_vertex, position=position, col=graph.nodes[representative].get('col', 0))
    for source, target, attributes in graph.edges(data=True):
        source = new_vertex if source in vertices else source
        target = new_vertex if target in vertices else target
        if source != target:
            new_graph.add_edge(source, target, **copy.deepcopy(attributes))
    return new_graph


def complement(graph, vertices):
    """Complement the graph induced by ``vertices``, or the whole graph."""
    vertices = set(vertices) & set(graph.nodes)
    vertices = list(vertices or graph.nodes)
    if graph.graph.get('graph_type') == 'graph':
        for index, source in enumerate(vertices):
            for target in vertices[index + 1:]:
                if graph.has_edge(source, target) or graph.has_edge(target, source):
                    graph.remove_edges_from(((source, target), (target, source)))
                else:
                    graph.add_edge(source, target, col=0)
                    graph.add_edge(target, source, col=0)
    else:
        for source in vertices:
            for target in vertices:
                if source != target:
                    if graph.has_edge(source, target):
                        graph.remove_edge(source, target)
                    else:
                        graph.add_edge(source, target, col=0)
    return graph


def randomize(graph, vertices, random_source=random.random):
    """Replace induced edges by independent probability-one-half edges."""
    vertices = list(set(vertices) & set(graph.nodes)) or list(graph.nodes)
    if graph.graph.get('graph_type') == 'graph':
        for index, source in enumerate(vertices):
            for target in vertices[index + 1:]:
                graph.remove_edges_from(((source, target), (target, source)))
                if random_source() < 0.5:
                    graph.add_edge(source, target, col=0)
                    graph.add_edge(target, source, col=0)
    else:
        for source in vertices:
            for target in vertices:
                if source != target:
                    graph.remove_edge(source, target) if graph.has_edge(source, target) else None
                    if random_source() < 0.5:
                        graph.add_edge(source, target, col=0)
    return graph


def switch(graph, vertices):
    """Cycle the colour of every edge incident to a selected vertex."""
    vertices = set(vertices) & set(graph.nodes)
    directed = graph.graph.get('graph_type') != 'graph'
    visited = set()
    for source, target in list(graph.edges):
        selected_endpoints = (source in vertices) + (target in vertices)
        if selected_endpoints != 1:
            continue
        logical_edge = (source, target) if directed else frozenset((source, target))
        if logical_edge in visited:
            continue
        visited.add(logical_edge)
        color = (graph.edges[source, target].get('col', 0) + 1) % graph.graph['num_edge_colors']
        graph.edges[source, target]['col'] = color
        if not directed and graph.has_edge(target, source):
            graph.edges[target, source]['col'] = color
    return graph


def degree_summary(graph):
    if graph.graph.get('graph_type') == 'graph':
        degrees = [value / 2 for _, value in graph.degree()]
        edge_count = graph.number_of_edges() / 2
    else:
        degrees = [value for _, value in graph.degree()]
        edge_count = graph.number_of_edges()
    if not degrees:
        return 'Empty graph'
    return (
        f'Vertices: {graph.number_of_nodes()}   Edges: {edge_count:.0f}\n'
        f'Degree — min: {min(degrees):.0f}   avg: {sum(degrees) / len(degrees):.3f}   max: {max(degrees):.0f}'
    )


def rotate(graph, vertices, degrees):
    """Rotate all other vertices around the one selected pivot."""
    if len(vertices) != 1:
        return graph
    pivot = next(iter(vertices))
    angle = degrees * pi / 180
    pivot_x, pivot_y = graph.nodes[pivot]['position']

    directed = graph.graph.get('graph_type') != 'graph'
    seen_edges = set()
    curve_points = {}
    for source, target in graph.edges:
        edge_key = (source, target) if directed else frozenset((source, target))
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)
        curve_points[(source, target)] = _edge_curve_points(graph, source, target)

    def rotate_point(point):
        x, y = point[0] - pivot_x, point[1] - pivot_y
        return (
            x * cos(angle) - y * sin(angle) + pivot_x,
            x * sin(angle) + y * cos(angle) + pivot_y,
        )

    for vertex in graph.nodes:
        if vertex == pivot:
            continue
        graph.nodes[vertex]['position'] = rotate_point(graph.nodes[vertex]['position'])
    for (source, target), points in curve_points.items():
        if points:
            _set_edge_curve_points(graph, source, target, [rotate_point(point) for point in points])
    return graph


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Interactive graph editor')
    parser.add_argument('--graph', metavar='FILE', help='GraphML file to open and save')
    args = parser.parse_args()

    def selected(context):
        return _selected_nodes(context.selection)

    def show_degree(context):
        context.box.write(degree_summary(context.graph), 5, (.8, .2))

    def make_twins(context):
        graph, new_vertices = twin(context.graph, selected(context), return_new_vertices=True)
        context.selection.clear()
        context.selection.nodes.update(new_vertices)
        return graph

    actions = [
        ContextAction(show_degree, 'd', name='Degree'),
        ContextAction(make_twins, 'w', available=lambda context: bool(selected(context)), name='Twin'),
        ContextAction(lambda context: switch(context.graph, selected(context)), 's', available=lambda context: bool(selected(context)), name='Switch'),
        ContextAction(lambda context: contract(context.graph, selected(context)), 'o', available=lambda context: len(selected(context)) >= 2, name='Contract', group='basic'),
        ContextAction(lambda context: complement(context.graph, selected(context)), None, name='Complement', group='basic'),
        ContextAction(lambda context: randomize(context.graph, context.selection.nodes), None, name='Randomize'),
        Action('custom:rotate_minus', 'Rotate', None, lambda context: rotate(context.graph, selected(context), -10), lambda context: len(selected(context)) == 1, group='basic', pair_label='Rotate', pair_id='rotate'),
        Action('custom:rotate_plus', 'Rotate', None, lambda context: rotate(context.graph, selected(context), 10), lambda context: len(selected(context)) == 1, group='basic', pair_label='Rotate', pair_id='rotate'),
    ]
    main(actions=actions, graph_file=args.graph, graph_type='graph', num_edge_colors=2, num_vertex_colors=4)
