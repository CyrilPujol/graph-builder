"""Public Python interface to Graph Builder.

Example::

    import networkx as nx
    from graph_builder import edit_graph

    graph = edit_graph(nx.path_graph(4))
"""

from graph_builder_core.actions import (
    Action, ContextAction, EdgeAction, GraphAction, VertexAction, VertexGroupAction,
)
from graph_builder_core.algorithms.optimization import optimize as optimize_graph
from graph_builder_core.algorithms.optimization import optimize_one
from graph_builder_core.algorithms.generators import Parameter as GraphParameter
from graph_builder_core.api import edit_graph, main
from graph_builder_core.extensions import (
    ButtonContext, ExtensionMenu, button, discover_buttons, discover_extensions,
    discover_parameters, parameter,
)
from graph_builder_core.io.graphml import convert_from_file, write_graph_file
from graph_builder_core.model.document import empty_graph, unused_label
from graph_builder_core.model.operations import twin

__all__ = [
    'Action', 'ContextAction', 'EdgeAction', 'GraphAction', 'VertexAction',
    'VertexGroupAction', 'ExtensionMenu', 'button', 'parameter', 'convert_from_file',
    'discover_buttons', 'discover_parameters', 'discover_extensions',
    'edit_graph', 'empty_graph', 'main', 'optimize_graph', 'twin', 'unused_label',
    'write_graph_file', 'optimize_one', 'GraphParameter', 'ButtonContext',
]


if __name__ == '__main__':
    raise SystemExit(main(actions=[], untitled=True))
