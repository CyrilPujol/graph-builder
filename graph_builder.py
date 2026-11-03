"""Public Python interface to Graph Builder.

Example::

    import networkx as nx
    from graph_builder import edit_graph

    graph = edit_graph(nx.path_graph(4))
"""

from graph_builder_core.lib import (
    Action,
    ContextAction,
    EdgeAction,
    GraphAction,
    VertexAction,
    VertexGroupAction,
    button,
    convert_from_file,
    discover_buttons,
    edit_graph,
    empty_graph,
    main,
    twin,
    unused_label,
    write_graph_file,
)

__all__ = [
    'Action', 'ContextAction', 'EdgeAction', 'GraphAction', 'VertexAction',
    'VertexGroupAction', 'button', 'convert_from_file', 'discover_buttons',
    'edit_graph', 'empty_graph', 'main', 'twin', 'unused_label',
    'write_graph_file',
]


if __name__ == '__main__':
    raise SystemExit(main(actions=[], untitled=True))
