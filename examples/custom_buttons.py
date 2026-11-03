"""Copy this file to make a personal launcher with your own Custom buttons."""

import networkx as nx

from graph_builder import button, main


@button('Color graph')
def color_graph(graph):
    """Give adjacent vertices different types where possible."""
    colors = nx.coloring.greedy_color(graph.to_undirected())
    nx.set_node_attributes(graph, colors, 'col')


if __name__ == '__main__':
    main()
