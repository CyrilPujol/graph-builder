"""A personal launcher example: signed-graph actions and parameters.

Copy this file outside the library to customize it. Edge style 0 means
positive, and edge style 1 means negative. Use an undirected document.
"""

import networkx as nx
from graph_builder import button, main, parameter


@button('Switch', selection='vertices')
def switch(graph, vertices):
    """Reverse the signs of edges crossing the selected vertex cut."""
    assert not graph.is_directed() and not graph.is_multigraph()
    chosen = set(vertices)
    for u, v, data in graph.edges(data=True):
        if (u in chosen) != (v in chosen):
            assert data['style'] in (0, 1)
            data['style'] = 1 - data['style']


@button('Double switch graph')
def double_switch(graph):
    """Two signed copies, with the sign reversed across copies."""
    assert not graph.is_directed() and not graph.is_multigraph()
    result = nx.Graph()
    result.graph.update(graph.graph)
    for node, data in graph.nodes(data=True):
        for layer in (0, 1):
            x, y = data['position']
            result.add_node((node, layer), **(data | {
                'label': f"{data.get('label', node)}{'+' if layer == 0 else '-'}",
                'position': (x + (-150 if layer == 0 else 150), y),
            }))
    for u, v, data in graph.edges(data=True):
        assert data['style'] in (0, 1)
        for left in (0, 1):
            for right in (0, 1):
                result.add_edge((u, left), (v, right),
                                **(data | {'style': data['style'] ^ (left != right)}))
    return result

@parameter('Balanced')
def is_balanced(graph):
    """Return True if the signed graph is balanced, False otherwise."""
    double = double_switch(graph)
    double.remove_edges_from([(u, v) for u, v, data in double.edges(data=True)
                              if data['style'] != 0])
    return all(not nx.has_path(double, (node, 0), (node, 1)) for node in graph)


if __name__ == '__main__':
    main()
