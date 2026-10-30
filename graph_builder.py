"""Graph Builder entry point and editable examples of custom graph actions."""

from __future__ import annotations

import copy
import random

import networkx as nx

# This is the user's script: remove any examples you do not want, or add your
# own @button functions. A minimal script needs only this import and main().
from graph_builder_lib import *


@button
def graph_coloring(graph):
    """A plain NetworkX function: no editor or Qt knowledge needed."""
    colors = nx.coloring.greedy_color(graph.to_undirected())
    nx.set_node_attributes(graph, colors, 'col')
    return graph


@button('Twin', shortcut='w', selection='vertices')
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
                if not directed:
                    graph.add_edge(target, new_vertex, **copy.deepcopy(attributes))
            if directed and target == vertex:
                graph.add_edge(source, new_vertex, **copy.deepcopy(attributes))
            elif not graph.is_directed() and target == vertex:
                graph.add_edge(new_vertex, source, **copy.deepcopy(attributes))
    return (graph, new_vertices) if return_new_vertices else graph


@button('Randomize', selection='vertices')
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


@button('Switch', shortcut='s', selection='vertices')
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


def missing_colors_within_two(graph, vertices):
    """For each selected vertex, find component colors absent within distance two.

    Directions are ignored for both connected components and distances. The
    vertex itself counts, since its distance is zero.
    """
    simple = graph.to_undirected(as_view=True) if graph.is_directed() else graph
    selected = set(vertices) & set(graph)
    missing = {}
    for component in nx.connected_components(simple):
        chosen = selected & component
        if not chosen:
            continue
        component_colors = {graph.nodes[node].get('col', 0) for node in component}
        for node in chosen:
            nearby = nx.single_source_shortest_path_length(simple, node, cutoff=2)
            visible = {graph.nodes[other].get('col', 0) for other in nearby}
            missing[node] = component_colors - visible
    return missing


def check_distance_two_colors(context):
    missing = missing_colors_within_two(context.graph, context.selection.nodes)
    failures = [(node, colors) for node, colors in missing.items() if colors]
    if not failures:
        message = (f'Yes: all {len(missing)} selected vertices see every color '
                   'in their connected component within distance 2.')
    else:
        details = []
        for node, colors in failures[:8]:
            label = context.graph.nodes[node].get('label', str(node))
            name = str(label) if str(label) == str(node) else f'{label} (ID {node})'
            details.append(f'{name}: missing {", ".join(map(str, sorted(colors)))}')
        extra = f' (and {len(failures) - 8} more)' if len(failures) > 8 else ''
        message = (f'No: {len(failures)} of {len(missing)} selected vertices miss colors '
                   f'within distance 2{extra}.\n' + '\n'.join(details))
    context.box.write(message, duration=12)


distance_two_colors = ContextAction(
    check_distance_two_colors,
    available=lambda context: bool(context.selection.nodes),
    name='Distance-2 colors',
)


if __name__ == '__main__':
    main()
