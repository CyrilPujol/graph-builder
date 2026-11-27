"""Run with: python examples/example_extension.py

Try the Showcase menu, Properties → Custom, and Standard graphs → Wheel.
Importing this file only declares the extension. It does not open a window.
"""
import math

import networkx as nx

from graph_builder import ExtensionMenu, GraphParameter, button, main, optimize_one


showcase = ExtensionMenu('Showcase')
showcase.text(lambda graph: f'{len(graph)} vertices')
showcase.separator()


@showcase.button('Intersection', selection=['vertices', 'vertices'], context=True)
def intersection(graph, first, second, editor):
    """Select the vertices common to two successive selections."""
    editor.select(first & second)
    editor.message(f'{len(first & second)} common vertices')


@showcase.button('Center selection', selection='vertices', context=True)
def center_selection(graph, vertices, editor):
    """Center the view on the selected vertices, or the whole graph."""
    vertices = vertices or set(graph)
    if vertices:
        positions = [graph.nodes[v]['position'] for v in vertices]
        editor.center_on(*(sum(p[i] for p in positions) / len(positions) for i in (0, 1)))


showcase.submenu('Selection', [intersection, center_selection])


def shift(graph, amount):
    for _, data in graph.nodes(data=True):
        x, y = data['position']
        data['position'] = (x + amount, y)


showcase.step('Move', lambda graph: shift(graph, -20), lambda graph: shift(graph, 20),
              can_decrease=bool, can_increase=bool)

showcase.separator()

def label_nodes(graph, enabled):
    for vertex in graph:
        graph.nodes[vertex]['label'] = showcase.value('Prefix') + str(vertex) if enabled else ''


showcase.toggle('Names', default=True, on_change=label_nodes,
                checked=lambda graph: all(data.get('label', '') for _, data in graph.nodes(data=True)))
showcase.input('Prefix', default='', placeholder='v')
showcase.choice('Style', (0, 1, 2, 3, 4), default=1)


@showcase.button('Paint', selection='vertices', when=bool)
def paint(graph, vertices):
    """Apply the chosen style to selected vertices, or all vertices."""
    style = showcase.value('Style')
    graph.graph['num_vertex_styles'] = max(graph.graph['num_vertex_styles'], style + 1)
    for vertex in vertices or set(graph):
        graph.nodes[vertex]['style'] = style



@showcase.parameter('Independent set')
def independent_set(graph, result):
    """Largest set of pairwise nonadjacent vertices."""
    sol = nx.maximal_independent_set(graph)
    result.data = set(sol)
    return f"α ≥  {len(sol)}"


@independent_set.compute
def compute_independent_set(graph, result):
    solution = optimize_one(graph, 'independent', seconds=2, workers=4)
    result.data = set(solution.witness)
    low, high = solution.lower, solution.upper
    if low == high:
        return f"α = {low}"
    else:
        return f"{low} ≤ α ≤ {high}"


@independent_set.show
def show_independent_set(graph, value, result):
    """Color the witness saved by Compute.

    ``value`` is the displayed answer, such as ``'α = 4'``. This callback
    does not need it because ``result.data`` already contains the vertex set.
    """
    if result.data is None:
        raise ValueError('Compute the independent set first.')
    graph.graph['num_vertex_styles'] = max(2, graph.graph['num_vertex_styles'])
    for vertex in graph:
        graph.nodes[vertex]['style'] = int(vertex in result.data)


@showcase.standard_graph(
    'Wheel', parameters=[GraphParameter('length', 'Length', 6, 3, 30)],
    estimate=lambda values: (values['length'] + 1, 2 * values['length']),
    layout=lambda graph, values: {
        vertex: ((0, 0) if vertex == 0 else
                 (3 * math.cos(2 * math.pi * (vertex - 1) / values['length']),
                  3 * math.sin(2 * math.pi * (vertex - 1) / values['length'])))
        for vertex in graph})
def wheel(values):
    return nx.wheel_graph(values['length'] + 1)


if __name__ == '__main__':
    main(extensions=[showcase])
