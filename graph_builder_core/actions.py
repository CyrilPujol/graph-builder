"""Command contracts and built-in actions, independent of Qt widgets."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import networkx as nx

from graph_builder_core.model.operations import (
    complement, contract, flip_horizontal, flip_vertical, fuse, pendant, rotate,
    scale_selection, twin,
)
from graph_builder_core.model.selection import SelectionState, selected_vertices


@dataclass
class EditorContext:
    graph: nx.DiGraph | nx.MultiDiGraph
    selection: SelectionState
    box: Any
    interaction: Any = None
    pointer_position: tuple = (0, 0)

    def replace_graph(self, graph):
        self.graph = graph


@dataclass
class Action:
    id: str
    name: str | Callable[[EditorContext], str]
    shortcut: str | None
    handler: Callable[[EditorContext], Any]
    available: Callable[[EditorContext], bool]
    library: bool = False
    group: str = 'custom'
    checked: Callable[[EditorContext], bool] | None = None
    pair_label: str | Callable[[EditorContext], str] | None = None
    pair_id: str | None = None
    description: str | None = None
    selections: int = 1

    def is_available(self, context):
        return bool(self.available(context))

    def display_name(self, context):
        return self.name(context) if callable(self.name) else self.name


def execute_action(action, context):
    if not action.is_available(context):
        return False
    result = action.handler(context)
    if isinstance(result, nx.Graph):
        context.replace_graph(result)
    return True


def ContextAction(function, shortcut=None, available=lambda context: True, name=None, group='custom'):
    def invoke(context):
        result = function(context)
        if isinstance(result, nx.Graph):
            context.replace_graph(result)
    return Action(f'custom:{shortcut or name or function.__name__}', name or function.__name__,
                  shortcut, invoke, available, group=group)


def GraphAction(function, shortcut=None, name=None, group='custom'):
    return ContextAction(lambda context: function(context.graph), shortcut, name=name or function.__name__, group=group)


def VertexAction(function, shortcut=None, name=None, group='custom'):
    return ContextAction(lambda context: function(context.graph, context.selection.single_node()),
                         shortcut, lambda context: context.selection.single_node() is not None,
                         name or function.__name__, group)


def VertexGroupAction(function, shortcut=None, name=None, group='custom'):
    return ContextAction(lambda context: function(context.graph, set(context.selection.nodes)),
                         shortcut, lambda context: bool(context.selection.nodes), name or function.__name__, group)


def EdgeAction(function, shortcut=None, name=None, group='custom'):
    def invoke(context):
        edge = next(iter(context.selection.edges))
        identity = ((edge.source, edge.target, edge.key) if context.graph.is_multigraph()
                    else (edge.source, edge.target))
        return function(context.graph, identity)
    return ContextAction(invoke, shortcut,
                         lambda context: len(context.selection.edges) == 1 and not context.selection.nodes,
                         name or function.__name__, group)


def builtin_editor_actions():
    """Editing commands present regardless of a user's custom action script."""
    def selected(context):
        return selected_vertices(context.selection)

    def transform_vertices(context):
        return selected(context) or set(context.graph.nodes)

    can_transform = lambda context: len(transform_vertices(context)) >= 2

    def add_pendants(context):
        interaction = context.interaction
        pendant(context.graph, context.selection.nodes,
                vertex_color=getattr(interaction, 'vertex_color', None),
                edge_color=getattr(interaction, 'edge_color', 0))

    def add_twins(context):
        _, added = twin(context.graph, selected(context), return_new_vertices=True)
        context.selection.clear()
        context.selection.nodes.update(added)

    def fuse_nearby(context):
        graph, added = fuse(context.graph, context.selection.nodes)
        context.graph = graph
        if added:
            context.selection.nodes.intersection_update(graph)
            context.selection.nodes.update(added)
            context.selection.edges.clear()

    return (
        Action('builtin:twin', 'Twin', 'w', add_twins,
               lambda context: bool(selected(context)), library=True, group='edition',
               description='Add a false twin vertex.'),
        Action('builtin:contract', 'Contract', 'o',
               lambda context: contract(context.graph, selected(context)),
               can_transform, library=True, group='edition',
               description='Contract the selection.'),
        Action('builtin:fuse', 'Fuse', 'f', fuse_nearby,
               lambda context: bool(context.graph), library=True, group='edition',
               description='Identify vertices with the same position.'),
        Action('builtin:complement', 'Complement', None,
               lambda context: complement(context.graph, selected(context)),
               lambda context: True, library=True, group='edition'),
        Action('builtin:pendant', 'Pendant', 'p', add_pendants,
               lambda context: bool(context.selection.nodes), library=True, group='edition',
               description='Add a pendant vertex.'),
        Action('builtin:rotate_left', 'Rotate left 10°', None,
               lambda context: rotate(context.graph, transform_vertices(context), -10),
               can_transform, library=True, group='basic',
               pair_id='transformation', pair_label='Transformation'),
        Action('builtin:rotate_right', 'Rotate right 10°', None,
               lambda context: rotate(context.graph, transform_vertices(context), 10),
               can_transform, library=True, group='basic',
               pair_id='transformation', pair_label='Transformation'),
        Action('builtin:flip_horizontal', 'Flip horizontally', None,
               lambda context: flip_horizontal(context.graph, transform_vertices(context)),
               can_transform, library=True, group='basic',
               pair_id='transformation', pair_label='Transformation'),
        Action('builtin:flip_vertical', 'Flip vertically', None,
               lambda context: flip_vertical(context.graph, transform_vertices(context)),
               can_transform, library=True, group='basic',
               pair_id='transformation', pair_label='Transformation'),
        Action('builtin:half_turn', 'Central symmetry (180°)', None,
               lambda context: rotate(context.graph, transform_vertices(context), 180),
               can_transform, library=True, group='basic',
               pair_id='transformation', pair_label='Transformation'),
        Action('builtin:grow', 'Grow ×1.1', None,
               lambda context: scale_selection(context.graph, transform_vertices(context), 1.1),
               can_transform, library=True, group='basic',
               pair_id='transformation', pair_label='Transformation'),
        Action('builtin:shrink', 'Shrink ÷1.1', None,
               lambda context: scale_selection(context.graph, transform_vertices(context), 1/1.1),
               can_transform, library=True, group='basic',
               pair_id='transformation', pair_label='Transformation'),
    )
