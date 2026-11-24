"""Public launch/edit entry points, with lazy Qt imports and caller discovery."""
from __future__ import annotations

from graph_builder_core.extensions import (
    discover_buttons, discover_extensions, discover_parameters, installed_extensions,
)


def _caller_actions(actions, namespace):
    if actions is None:
        return discover_buttons(namespace)
    return [getattr(action, '__graph_button__', action) for action in actions]


def _caller_parameters(parameters, namespace):
    if parameters is None:
        return discover_parameters(namespace)
    return [getattr(item, '__graph_parameter__', item) for item in parameters]


def _caller_extensions(extensions, namespace):
    if extensions is not None:
        return list(extensions)
    local = discover_extensions(namespace)
    installed = installed_extensions()
    names = {menu.name for menu in local}
    return local + [menu for menu in installed if menu.name not in names]


def main(actions=None, graph_file=None, *, untitled=False,
         parameters=None, extensions=None, **options):
    """Open Graph Builder and block until its window closes.

    Parameters
    ----------
    actions : iterable, optional
        Custom buttons. By default, discover ``@button`` functions in the
        calling module.
    graph_file : str or path-like, optional
        Graph file to open. Otherwise the launcher may read ``--graph``.
    untitled : bool, optional
        Start a new drawing that asks where to save. Cannot be combined with
        ``graph_file``.
    parameters : iterable, optional
        Custom ``@parameter`` measures. Discovered from the caller by default.
    extensions : iterable of ExtensionMenu, optional
        Menus to install. By default, discover caller menus and installed
        extension packages.

    Returns
    -------
    int
        Application exit code, not the edited graph. Use ``edit_graph`` if
        the surrounding Python program needs the graph afterward.

    Examples
    --------
    A personal launcher can consist of::

        from graph_builder import *
        main()
    """
    import inspect
    import argparse
    frame = inspect.currentframe()
    try:
        namespace = frame.f_back.f_globals
        actions = _caller_actions(actions, namespace)
        parameters = _caller_parameters(parameters, namespace)
        extensions = _caller_extensions(extensions, namespace)
    finally:
        del frame
    if untitled and graph_file is not None:
        raise ValueError('Choose either graph_file or untitled=True.')
    if graph_file is None and not untitled:
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument('--graph')
        arguments, _ = parser.parse_known_args()
        graph_file = arguments.graph
    from graph_builder_core.ui.window import launch
    return launch(actions=actions, parameters=parameters, extensions=extensions,
                  graph_file=graph_file, untitled=untitled, **options)


def edit_graph(graph=None, *, actions=None, parameters=None, extensions=None):
    """Edit a NetworkX graph and return the drawing when the window closes.

    Parameters
    ----------
    graph : networkx.Graph, optional
        Starting graph. It is copied, so the input remains unchanged. Omit it
        to start with an empty undirected graph.
    actions : iterable, optional
        Custom buttons, discovered from the calling module by default.
    parameters : iterable, optional
        Custom measures, discovered from the caller by default.
    extensions : iterable of ExtensionMenu, optional
        Extension menus. Caller and installed menus are found by default.

    Returns
    -------
    networkx.Graph
        Graph shown when the window closes, with integer vertex keys.
        Noninteger input keys become visible labels. Added vertices receive
        positions and drawing attributes automatically.

    Examples
    --------
    Continue a Python workflow after editing::

        import networkx as nx
        from graph_builder import edit_graph

        graph = edit_graph(nx.path_graph(4))
        print(graph.number_of_edges())
    """
    import inspect
    frame = inspect.currentframe()
    try:
        namespace = frame.f_back.f_globals
        actions = _caller_actions(actions, namespace)
        parameters = _caller_parameters(parameters, namespace)
        extensions = _caller_extensions(extensions, namespace)
    finally:
        del frame
    from graph_builder_core.ui.window import edit_graph_window
    return edit_graph_window(graph, actions=actions, parameters=parameters,
                             extensions=extensions)
