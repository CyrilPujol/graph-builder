"""Beginner-friendly custom actions, independent of Qt.

The public graph is an ordinary NetworkX graph; conversion and validation are
kept here rather than spread between user scripts and the window class.
"""
import copy
import inspect
import json
import math

import networkx as nx


def discover_buttons(namespace):
    """Discover explicitly registered buttons, preserving definition order."""
    from .lib import Action
    actions, seen = [], set()
    for value in namespace.values():
        action = value if isinstance(value, Action) else getattr(value, '__graph_button__', None)
        if isinstance(action, Action) and id(action) not in seen:
            actions.append(action)
            seen.add(id(action))
    return actions


def _number(value, description, integer=False):
    try:
        number = float(value)
        if not math.isfinite(number) or (integer and (number < 0 or not number.is_integer())):
            raise ValueError
        return int(number) if integer else number
    except (TypeError, ValueError, OverflowError):
        kind = 'a nonnegative integer' if integer else 'a finite number'
        raise ValueError(f'{description} must be {kind}; got {value!r}.') from None


def _point(value, description):
    try:
        if isinstance(value, (str, bytes)) or len(value) != 2:
            raise ValueError
        return tuple(_number(x, description) for x in value)
    except (TypeError, ValueError):
        raise ValueError(f'{description} must be two finite numbers, e.g. (100, 50); got {value!r}.') from None


def public_graph(graph):
    """Copy the document without exposing paired undirected arcs."""
    from .lib import logical_edges
    result = nx.Graph() if graph.graph.get('graph_type') == 'graph' else nx.DiGraph()
    result.graph.update(copy.deepcopy(graph.graph))
    result.add_nodes_from(copy.deepcopy(list(graph.nodes(data=True))))
    for u, v in logical_edges(graph):
        result.add_edge(u, v, **copy.deepcopy(graph.edges[u, v]))
    return result


def integer_key_input(graph):
    """Prepare an API graph for editing while retaining existing integer keys."""
    occupied = {node for node in graph if type(node) is int}
    mapping = {}
    candidate = 0
    for node in graph:
        if type(node) is int:
            identifier = node
        else:
            while candidate in occupied:
                candidate += 1
            identifier = candidate
            occupied.add(identifier)
            candidate += 1
        mapping[node] = str(identifier)
    result = nx.relabel_nodes(graph, mapping, copy=True)
    for node, identifier in mapping.items():
        if type(node) is not int and 'label' not in result.nodes[identifier]:
            result.nodes[identifier]['label'] = str(node)
    return result


def integer_key_output(graph):
    """Return a graph whose keys are all integers, including newly added nodes."""
    def canonical_integer(node):
        if type(node) is int:
            return node
        if not isinstance(node, str):
            return None
        try:
            integer = int(node)
        except ValueError:
            return None
        return integer if str(integer) == node else None

    mapping = {}
    occupied = set()
    for node in graph:
        integer = canonical_integer(node)
        if integer is not None:
            mapping[node] = integer
            occupied.add(integer)
    candidate = 0
    for node in graph:
        if node in mapping:
            continue
        while candidate in occupied:
            candidate += 1
        mapping[node] = candidate
        occupied.add(candidate)
        candidate += 1
    result = nx.relabel_nodes(graph, mapping, copy=True)
    for node, identifier in mapping.items():
        if 'label' not in result.nodes[identifier]:
            result.nodes[identifier]['label'] = str(node)
    return result


def normalize_graph(result, original, center=(0, 0), orientations=None):
    """Validate a public result and supply editor attributes, without mutation."""
    from .lib import DEFAULT_GRAPH_OPTIONS, empty_graph, unused_label, _set_edge_curve_points
    if not isinstance(result, nx.Graph):
        raise TypeError('Return a NetworkX Graph/DiGraph, or return None after editing the graph in place. '
                        f'Received {type(result).__name__}.')
    if result.is_multigraph():
        raise ValueError('Parallel edges (MultiGraph/MultiDiGraph) are not supported by the editor.')
    if nx.number_of_selfloops(result):
        raise ValueError('Self-loops are not supported by the editor; remove edges from a vertex to itself.')
    directed = original.graph.get('graph_type') != 'graph'
    if result.is_directed() != directed:
        raise ValueError('The returned graph changes directedness. Change it in Graph properties first, '
                         'or return a graph with the same directedness as the input.')
    graph = empty_graph()
    graph.graph.update(copy.deepcopy(original.graph))
    graph.graph.update(copy.deepcopy({key: value for key, value in result.graph.items()
                                     if key not in DEFAULT_GRAPH_OPTIONS}))
    # Reserve string keys before allocating IDs for arbitrary hashable NX keys.
    reserved = nx.Graph()
    reserved.add_nodes_from(original)
    reserved.add_nodes_from(n for n in result if isinstance(n, str))
    mapping = {}
    for node in result:
        mapping[node] = node if isinstance(node, str) else unused_label(reserved)
        reserved.add_node(mapping[node])
    missing = []
    for node, attributes in result.nodes(data=True):
        data = copy.deepcopy(original.nodes[node]) if node in original else {}
        data.update(copy.deepcopy(attributes))
        data['label'] = str(data.get('label', node))
        data['col'] = _number(data.get('col', 0), f'Vertex {node!r} color (col)', True)
        if data.get('position') is None:
            missing.append(node)
            data.pop('position', None)
        else:
            data['position'] = _point(data['position'], f'Vertex {node!r} position')
        graph.add_node(mapping[node], **data)
    occupied = [d['position'] for _, d in graph.nodes(data=True) if 'position' in d]
    for node in missing:
        neighbors = list(result.neighbors(node))
        if directed:
            neighbors += list(result.predecessors(node))
        positions = [graph.nodes[mapping[n]]['position'] for n in neighbors
                     if 'position' in graph.nodes[mapping[n]]]
        origin = tuple(sum(p[i] for p in positions) / len(positions) for i in (0, 1)) if positions else center
        for attempt in range(len(occupied) * 8 + 2):
            radius = 65 * math.sqrt(attempt)
            angle = attempt * 2.399963229728653
            position = (origin[0] + radius * math.cos(angle), origin[1] + radius * math.sin(angle))
            if all(math.dist(position, p) >= 45 for p in occupied):
                break
        graph.nodes[mapping[node]]['position'] = position
        occupied.append(position)
    for u, v, attributes in result.edges(data=True):
        data = copy.deepcopy(original.edges[u, v]) if original.has_edge(u, v) else {}
        data.update(copy.deepcopy(attributes))
        data['col'] = _number(data.get('col', 0), f'Edge {u!r}–{v!r} color (col)', True)
        data['label'] = str(data.get('label', ''))
        a, b = mapping[u], mapping[v]
        curves = data.pop('curve_offsets', None)
        absolute = data.pop('curve_points', None)
        graph.add_edge(a, b, **data)
        if not directed:
            graph.add_edge(b, a, **copy.deepcopy(data))
        if curves or absolute:
            raw = curves or absolute
            try:
                points = json.loads(raw) if isinstance(raw, str) else raw
                points = [_point(p, f'Edge {u!r}–{v!r} curve point') for p in points]
            except (TypeError, ValueError):
                raise ValueError(f'Edge {u!r}–{v!r}: curve points must be a list of coordinate pairs.') from None
            if not directed and orientations and orientations.get(frozenset((u, v)), (u, v)) != (u, v):
                points.reverse()
            if curves:
                p, q = graph.nodes[a]['position'], graph.nodes[b]['position']
                points = [(x + (p[0] + q[0]) / 2, y + (p[1] + q[1]) / 2) for x, y in points]
            _set_edge_curve_points(graph, a, b, points)
    for key, values in (('num_vertex_colors', [d['col'] for _, d in graph.nodes(data=True)]),
                        ('num_edge_colors', [d['col'] for _, _, d in graph.edges(data=True)])):
        graph.graph[key] = max(graph.graph[key], max(values, default=0) + 1)
    # Reject attributes that would work on canvas but later break GraphML saving.
    for description, data in [('Graph', graph.graph)] + [(f'Vertex {n!r}', d) for n, d in graph.nodes(data=True)] + [(f'Edge {u!r}–{v!r}', d) for u, v, d in graph.edges(data=True)]:
        for key, value in data.items():
            if key == 'position' and description.startswith('Vertex'):
                continue
            if description == 'Graph' and key in ('node_default', 'edge_default') and isinstance(value, dict):
                continue  # NetworkX's own GraphML metadata, not an item attribute.
            if not isinstance(key, str) or not isinstance(value, (str, bool, int, float)):
                raise ValueError(f'{description} attribute {key!r} cannot be saved. Use a string, number or boolean (JSON text for structured data).')
    return graph, mapping


def button(name=None, *, shortcut=None, selection=None):
    """Add a function as a button in the Custom menu.

Use @button, @button('Button name'), or
@button('Button name', shortcut='G', selection='vertex').

The decorator's `name` sets the button text, `shortcut` sets its keyboard
shortcut, and `selection` determines what the decorated function receives.

The decorated function always receives a NetworkX graph as its first
argument: nx.Graph for an undirected document, nx.DiGraph for a directed one.
It may modify that graph in place and return None, or return a graph.

With selection='vertex', its second argument is one vertex ID.
With selection='vertices', it is a (possibly empty) set of vertex IDs.
With selection='edge', it is a (source, target) pair.
Without `selection`, the function receives only the graph.
"""
    from .lib import Action, selected_vertices
    if selection not in (None, 'vertex', 'vertices', 'edge'):
        raise ValueError("selection must be None, 'vertex', 'vertices', or 'edge'.")

    def decorate(function):
        title = name if isinstance(name, str) else function.__name__.replace('_', ' ').capitalize()
        documentation = inspect.getdoc(function)
        description = documentation.splitlines()[0] if documentation else None

        def available(context):
            if selection == 'vertex':
                return context.selection.single_node() is not None
            if selection == 'edge':
                return len(context.selection.edges) == 1 and not context.selection.nodes
            return True

        def invoke(context):
            graph = public_graph(context.graph)
            orientations = {frozenset((u, v)): (u, v) for u, v in graph.edges} if not graph.is_directed() else None
            args = [graph]
            if selection == 'vertex':
                args.append(context.selection.single_node())
            elif selection == 'vertices':
                args.append(selected_vertices(context.selection))
            elif selection == 'edge':
                edge = next(iter(context.selection.edges))
                args.append((edge.source, edge.target))
            result = function(*args)
            center = (0, 0)
            if context.interaction is not None:
                view = context.interaction.view
                center = tuple(view.mapToScene(view.viewport().rect().center()).toTuple())
            normalized, _ = normalize_graph(graph if result is None else result, context.graph, center, orientations)
            added = set(normalized) - set(context.graph)
            context.graph = normalized
            if added:
                context.selection.clear()
                context.selection.nodes.update(added)
            context.selection.prune(normalized)

        function.__graph_button__ = Action(f'button:{function.__module__}.{function.__name__}', title,
                                          shortcut, invoke, available, description=description)
        return function

    return decorate(name) if callable(name) else decorate
