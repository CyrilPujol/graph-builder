"""The most basic launcher example, with a dummy custom button.

Copy this file outside the library to customize it.
"""

import networkx as nx
from graph_builder import button, main, parameter

@button('New vertex', shortcut='G', selection='vertex')
def grow(graph, vertex):
    graph.add_edge(vertex, 'new vertex')

@parameter('Density')
def density(graph):
    return round(nx.density(graph), 4)

if __name__ == '__main__':
    main()
