"""Beginner-friendly custom actions, independent of Qt.

The public graph is an ordinary NetworkX graph; conversion and validation are
kept here rather than spread between user scripts and the window class.
"""
import copy
import inspect
import json
import math
from dataclasses import dataclass, field
from importlib.metadata import entry_points

import networkx as nx

from graph_builder_core.model.edges import (
    edge_data, edge_records, visible_edges, add_edge, has_edge,
)


@dataclass
class ParameterDefinition:
    """A quick graph measure with optional deeper computation and drawing."""

    name: str
    quick: object
    compute: object = None
    show: object = None
    description: str = ''


@dataclass
class ParameterResult:
    """Store one parameter's displayed value and optional Show data.

    Parameters
    ----------
    value : object, optional
        The quick or computed value displayed in the Properties panel.
    data : object, optional
        A witness or other data saved by a callback for its Show action.
    computed : bool, optional
        Whether the Compute callback supplied the current value.

    Examples
    --------
    In a Compute callback, ``result.data = set(vertices)`` saves a witness.
    A Show callback can then read that set without parsing ``value``.
    """

    value: object = None
    data: object = None
    computed: bool = False


def parameter(name=None, *, compute=None, show=None):
    """Register a graph measure in Properties → Custom.

    Parameters
    ----------
    name : str, optional
        Display name. Defaults to the decorated function's name.
    compute : callable, optional
        Deeper calculation for the Compute button.
    show : callable, optional
        Action for Show. It receives ``(graph, value)`` and may also accept
        ``result`` and ``selection`` by name.

    Returns
    -------
    callable
        The decorated quick function, with ``.compute`` and ``.show``
        decorators for attaching callbacks later.

    Notes
    -----
    The quick and Compute callbacks return the value displayed in the panel.
    Either callback may accept ``result`` and set ``result.data`` to retain a
    witness. Show receives the *displayed value* as its second argument and
    the same result object as an optional third argument. Its graph is an
    editable copy. Return it or modify it in place and return ``None``.

    Examples
    --------
    A measure can keep its human-readable answer separate from its witness::

        @measure.compute
        def compute(graph, result):
            result.data = {1, 3}
            return 'Two vertices found'

        @measure.show
        def show(graph, value, result):
            for vertex in result.data:
                graph.nodes[vertex]['style'] = 1

    For a quick-only measure, ``@parameter`` is enough::

        @parameter
        def order(graph):
            return len(graph)
    """
    def decorate(function):
        title = name if isinstance(name, str) else function.__name__.replace('_', ' ').capitalize()
        documentation = inspect.getdoc(function) or ''
        definition = ParameterDefinition(title, function, compute, show,
                                         documentation.splitlines()[0] if documentation else '')
        function.__graph_parameter__ = definition

        def add_compute(callback):
            definition.compute = callback
            return callback

        def add_show(callback):
            definition.show = callback
            return callback

        function.compute = add_compute
        function.show = add_show
        return function

    return decorate(name) if callable(name) else decorate


def discover_parameters(namespace):
    """Discover parameters defined in a caller's module, without duplicates."""
    found, seen = [], set()
    for value in namespace.values():
        definition = (value if isinstance(value, ParameterDefinition)
                      else getattr(value, '__graph_parameter__', None))
        if isinstance(definition, ParameterDefinition) and id(definition) not in seen:
            found.append(definition)
            seen.add(id(definition))
    return found


@dataclass
class MenuItem:
    kind: str
    label: str = ''
    action: object = None
    other: object = None
    options: tuple = ()
    key: str = ''
    minimum: int = 0
    maximum: int = 100
    when: object = None


@dataclass
class ExtensionMenu:
    """Declare a top-level menu using graph-facing controls.

    Parameters
    ----------
    name : str
        Title displayed in the menu bar.

    Notes
    -----
    Pass the menu to ``main(extensions=[menu])`` or expose it through a
    ``graph_builder.menus`` package entry point. Controls keep their own UI
    state, while graph-changing callbacks are undoable actions.

    Examples
    --------
    >>> menu = ExtensionMenu('Research')
    >>> menu.text('Tools for this graph family')
    """

    name: str
    items: list = field(default_factory=list)
    state: dict = field(default_factory=dict)
    parameters: list = field(default_factory=list)
    generators: list = field(default_factory=list)

    def button(self, name=None, *, shortcut=None, selection=None, when=None,
               context=False):
        """Add an action button to this menu.

        Parameters
        ----------
        name, shortcut, selection, context
            Have the same meanings as in :func:`button`.
        when : callable, optional
            Fast ``when(graph)`` predicate controlling availability.

        Returns
        -------
        callable
            Decorator for a NetworkX graph-editing function.

        Examples
        --------
        ``@menu.button('Paint', selection='vertices')`` adds a button that
        passes the selected vertex IDs to the decorated function.
        """
        def decorate(function):
            decorated = button(name if isinstance(name, str) else None,
                               shortcut=shortcut, selection=selection,
                               context=context)(function)
            action = decorated.__graph_button__
            decorated.__graph_extension_menu__ = self
            action.group = f'menu:{self.name}'
            action.id += f':{self.name}:{action.name}'
            if when is not None:
                original_available = action.available
                action.available = lambda context: (original_available(context)
                    and bool(when(public_graph(context.graph))))
            self.items.append(MenuItem('button', action=action))
            return decorated
        return decorate(name) if callable(name) else decorate

    def parameter(self, name=None, **options):
        """Register a Properties → Custom measure with this extension.

        Parameters
        ----------
        name : str, optional
            Display name of the measure.
        **options
            Optional ``compute`` and ``show`` callbacks, as in :func:`parameter`.

        Returns
        -------
        callable
            Decorator whose result supports ``.compute`` and ``.show``.

        Examples
        --------
        ``@menu.parameter('Order')`` can decorate a function returning
        ``len(graph)``.
        """
        def decorate(function):
            result = parameter(name if isinstance(name, str) else None, **options)(function)
            self.parameters.append(result.__graph_parameter__)
            return result
        return decorate(name) if callable(name) else decorate

    def standard_graph(self, name, *, parameters=(), layout=None, estimate):
        """Add a generated graph family to Standard graphs.

        Parameters
        ----------
        name : str
            Name in the graph-family dropdown.
        parameters : iterable of GraphParameter, optional
            Inputs shown for this family.
        layout : callable, optional
            ``layout(graph, values)`` returning node-to-``(x, y)`` positions.
            Defaults to a circular layout.
        estimate : callable
            ``estimate(values)`` returning approximate vertex and edge counts
            before generation, so oversized requests can be rejected.

        Returns
        -------
        callable
            Decorator for ``generate(values)``, which returns a NetworkX graph.

        Examples
        --------
        ``@menu.standard_graph('Path', estimate=lambda v: (v['n'], v['n']-1))``
        can decorate a function returning ``nx.path_graph(values['n'])``.
        """
        from graph_builder_core.algorithms.generators import GraphDefinition, _circle
        def decorate(function):
            key = f'extension:{self.name}:{function.__name__}'
            self.generators.append(GraphDefinition(key, name, tuple(parameters),
                                                  function, layout or _circle, estimate))
            return function
        return decorate

    def text(self, text):
        """Add text to the menu.

        Parameters
        ----------
        text : str or callable
            Static text or ``text(graph)`` refreshed after graph edits.

        Examples
        --------
        ``menu.text(lambda graph: f'{len(graph)} vertices')``.
        """
        self.items.append(MenuItem('text', label=text if isinstance(text, str) else '',
                                   other=text if callable(text) else None))

    def input(self, label, *, key=None, default='', placeholder=''):
        """Add a small text field to the menu.

        Parameters
        ----------
        label : str
            Caption beside the field.
        key : str, optional
            State key, defaulting to ``label``.
        default, placeholder : str, optional
            Initial value and empty-field hint.

        Examples
        --------
        ``menu.input('Prefix', default='v')`` is read with
        ``menu.value('Prefix')``.
        """
        key = key or label
        self.state[key] = str(default)
        self.items.append(MenuItem('input', label=label, key=key, other=placeholder))

    def separator(self):
        """Add a vertical divider between neighboring menu controls."""
        self.items.append(MenuItem('separator'))

    def step(self, label, decrease, increase, *, can_decrease=None, can_increase=None):
        """Add a compact −/+ action pair.

        Parameters
        ----------
        label : str
            Caption shared by the two buttons.
        decrease, increase : callable
            ``callback(graph)`` actions for each direction.
        can_decrease, can_increase : callable, optional
            ``predicate(graph)`` controlling each button's availability.

        Examples
        --------
        ``menu.step('Move', move_left, move_right, can_increase=bool)``.
        """
        first = self.button(f'{label} −', when=can_decrease)(decrease).__graph_button__
        second = self.button(f'{label} +', when=can_increase)(increase).__graph_button__
        self.items[-2:] = [MenuItem('step', label, first, second)]

    def choice(self, label, options, *, key=None, default=None):
        """Add a dropdown whose selected value is kept in menu state.

        Parameters
        ----------
        label : str
            Caption beside the dropdown.
        options : iterable
            Available values, in display order.
        key : str, optional
            State key, defaulting to ``label``.
        default : object, optional
            Initial choice, defaulting to the first option.

        Examples
        --------
        ``menu.choice('Style', (0, 1, 2), default=1)`` can be read with
        ``menu.value('Style')``.
        """
        choices = tuple(options)
        if not choices:
            raise ValueError('A choice control needs at least one option.')
        key = key or label
        selected = choices[0] if default is None else default
        if selected not in choices:
            raise ValueError('Default choice must be one of the options.')
        self.state[key] = selected
        self.items.append(MenuItem('choice', label=label, options=choices, key=key))

    def toggle(self, label, *, key=None, default=False, on_change=None, checked=None):
        """Add an on/off control.

        Parameters
        ----------
        label : str
            Button caption.
        key : str, optional
            State key, defaulting to ``label``.
        default : bool, optional
            Initial local state.
        on_change : callable, optional
            ``on_change(graph, enabled)`` edits the graph as one undoable action.
        checked : callable, optional
            ``checked(graph)`` reads document state, including after undo.

        Examples
        --------
        ``menu.toggle('Names', on_change=set_names, checked=has_names)``.
        """
        key = key or label
        self.state[key] = bool(default)
        action = None
        if on_change is not None:
            def changed(graph):
                return on_change(graph, self.value(key))
            changed.__name__ = f'toggle_{key}'
            action = self.button(label)(changed).__graph_button__
            self.items.pop()
        self.items.append(MenuItem('toggle', label=label, key=key, action=action, when=checked))

    def slider(self, label, minimum, maximum, *, key=None, default=None):
        """Add a bounded integer slider.

        Parameters
        ----------
        label : str
            Caption beside the slider.
        minimum, maximum : int
            Inclusive bounds, with ``minimum < maximum``.
        key : str, optional
            State key, defaulting to ``label``.
        default : int, optional
            Initial value, defaulting to ``minimum``.

        Examples
        --------
        ``menu.slider('Distance', 1, 10, default=3)`` is read with
        ``menu.value('Distance')``.
        """
        if minimum >= maximum:
            raise ValueError('Slider minimum must be below maximum.')
        key = key or label
        value = minimum if default is None else default
        if not minimum <= value <= maximum:
            raise ValueError('Slider default must be within its limits.')
        self.state[key] = value
        self.items.append(MenuItem('slider', label=label, key=key,
                                   minimum=minimum, maximum=maximum))

    def submenu(self, label, actions):
        """Group extension buttons in a drop-down list.

        Parameters
        ----------
        label : str
            Caption of the list button.
        actions : iterable of callable
            Functions already decorated with ``@menu.button``.

        Examples
        --------
        ``menu.submenu('Selection', [select_all, select_none])``.
        """
        entries = tuple(actions)
        if any(not hasattr(action, '__graph_button__') for action in entries):
            raise TypeError('Submenu entries must be extension button functions.')
        used = {id(action.__graph_button__) for action in entries}
        self.items[:] = [item for item in self.items
                         if item.kind != 'button' or id(item.action) not in used]
        self.items.append(MenuItem('submenu', label=label,
                                   options=tuple(action.__graph_button__ for action in entries)))

    def value(self, key):
        """Return the current value of an input, choice, toggle, or slider.

        Parameters
        ----------
        key : str
            The control's key or, if no key was supplied, its label.

        Returns
        -------
        object
            Current value held by this menu instance.
        """
        return self.state[key]

    def actions(self):
        for item in self.items:
            if item.kind == 'button' or (item.kind == 'toggle' and item.action is not None):
                yield item.action
            elif item.kind == 'step':
                yield item.action
                yield item.other
            elif item.kind == 'submenu':
                yield from item.options


def discover_extensions(namespace):
    found, seen = [], set()
    for value in namespace.values():
        if isinstance(value, ExtensionMenu) and id(value) not in seen:
            found.append(value)
            seen.add(id(value))
    return found


def installed_extensions():
    """Load trusted, installed menu entry points for Python-library launches."""
    found = []
    for entry in entry_points(group='graph_builder.menus'):
        menu = entry.load()
        if callable(menu) and not isinstance(menu, ExtensionMenu):
            menu = menu()
        if not isinstance(menu, ExtensionMenu):
            raise TypeError(f'Extension {entry.name!r} must expose an ExtensionMenu.')
        found.append(menu)
    return found


def discover_buttons(namespace):
    """Discover explicitly registered buttons, preserving definition order."""
    from graph_builder_core.actions import Action
    actions, seen = [], set()
    for value in namespace.values():
        if getattr(value, '__graph_extension_menu__', None) is not None:
            continue
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
    if graph.is_multigraph():
        result = nx.MultiGraph() if graph.graph.get('graph_type') == 'graph' else nx.MultiDiGraph()
    else:
        result = nx.Graph() if graph.graph.get('graph_type') == 'graph' else nx.DiGraph()
    result.graph.update(copy.deepcopy(graph.graph))
    result.add_nodes_from(copy.deepcopy(list(graph.nodes(data=True))))
    for u, v, key, data in visible_edges(graph):
        add_edge(result, u, v, data, key)
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
    from graph_builder_core.model.regions import remap_regions
    remap_regions(result, mapping)
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
    from graph_builder_core.model.regions import remap_regions
    remap_regions(result, mapping)
    for node, identifier in mapping.items():
        if 'label' not in result.nodes[identifier]:
            result.nodes[identifier]['label'] = str(node)
    return result


def normalize_graph(result, original, center=(0, 0), orientations=None):
    """Validate a public result and supply editor attributes, without mutation."""
    from graph_builder_core.model.document import (
        DEFAULT_GRAPH_OPTIONS, canonical_graph_options, empty_graph, unused_label,
    )
    from graph_builder_core.geometry.curves import _set_edge_curve_points
    if not isinstance(result, nx.Graph):
        raise TypeError('Return a NetworkX Graph/DiGraph, or return None after editing the graph in place. '
                        f'Received {type(result).__name__}.')
    if result.is_multigraph() and not original.graph.get('multiedges', False):
        raise ValueError('Parallel edges require Multiedges in Structure. Enable it before returning a MultiGraph.')
    if nx.number_of_selfloops(result) and not original.graph.get('loops', False):
        raise ValueError('Self-loops require Loops in Structure. Enable it before adding a self-loop.')
    directed = original.graph.get('graph_type') != 'graph'
    if result.is_directed() != directed:
        raise ValueError('The returned graph changes directedness. Change it in Structure first, '
                         'or return a graph with the same directedness as the input.')
    graph = empty_graph(multiedges=original.graph.get('multiedges', False))
    graph.graph.update(copy.deepcopy(original.graph))
    graph.graph.update(copy.deepcopy({key: value for key, value in canonical_graph_options(result.graph).items()
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
        legacy_style = data.pop('col', None)
        data['style'] = _number(legacy_style if legacy_style is not None else data.get('style', 0),
                                f'Vertex {node!r} style', True)
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
    for u, v, key, attributes in edge_records(result):
        data = copy.deepcopy(edge_data(original, u, v, key)) if has_edge(original, u, v, key) else {}
        data.update(copy.deepcopy(attributes))
        legacy_style = data.pop('col', None)
        data['style'] = _number(legacy_style if legacy_style is not None else data.get('style', 0),
                                f'Edge {u!r}–{v!r} style', True)
        data['label'] = str(data.get('label', ''))
        a, b = mapping[u], mapping[v]
        curves = data.pop('curve_offsets', None)
        absolute = data.pop('curve_points', None)
        key = add_edge(graph, a, b, data, key)
        if not directed:
            add_edge(graph, b, a, data, key)
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
            _set_edge_curve_points(graph, a, b, points, key)
    for key, values in (('num_vertex_styles', [d['style'] for _, d in graph.nodes(data=True)]),
                        ('num_edge_styles', [d['style'] for _, _, d in graph.edges(data=True)])):
        graph.graph[key] = max(graph.graph[key], max(values, default=0) + 1)
    from graph_builder_core.model.regions import prune_regions, remap_regions
    remap_regions(graph, mapping)
    prune_regions(graph)
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


class ButtonContext:
    """Access selection, viewport, and notifications from a custom button.

    Notes
    -----
    Set ``context=True`` on ``@button`` or ``@menu.button`` to receive this
    object as the callback's final argument. It controls the editor, while
    graph edits still belong on the callback's NetworkX graph argument.

    Examples
    --------
    ``editor.select({0, 1})`` selects two vertices, and
    ``editor.message('Done')`` shows a short notice.
    """

    def __init__(self, context):
        self._context = context

    @property
    def selected_vertices(self):
        """Return the currently selected vertex IDs as a new set."""
        return set(self._context.selection.nodes)

    def select(self, vertices):
        """Replace the vertex selection with ``vertices``.

        Parameters
        ----------
        vertices : iterable
            Vertex IDs to select after the action completes.
        """
        self._context.selection.clear()
        self._context.selection.nodes.update(vertices)

    @property
    def view_center(self):
        """Return the visible viewport center as graph ``(x, y)`` coordinates."""
        view = self._context.interaction.view
        return tuple(view.mapToScene(view.viewport().rect().center()).toTuple())

    def center_on(self, x, y):
        """Center the viewport on graph coordinates ``(x, y)``."""
        self._context.interaction.view.centerOn(x, y)

    def zoom(self, factor):
        """Multiply the current zoom by a positive finite ``factor``."""
        if not math.isfinite(factor) or factor <= 0:
            raise ValueError('Zoom factor must be positive and finite.')
        view = self._context.interaction.view
        view.zoom_by_factor(factor, view.viewport().rect().center())

    def fit(self):
        """Center and fit the graph in the visible viewport."""
        self._context.interaction.fit_graph()

    def message(self, text):
        """Show ``text`` as a brief editor notification."""
        self._context.interaction.report(str(text), 5)


def button(name=None, *, shortcut=None, selection=None, context=False):
    """Register a graph-editing function as a Custom button.

    Parameters
    ----------
    name : str, optional
        Button text, defaulting to the function's name.
    shortcut : str, optional
        Keyboard shortcut.
    selection : {None, 'vertex', 'vertices', 'edge', 'edges', 'any'} or iterable, optional
        Extra input passed after the graph. A single vertex ID requires
        exactly one selected vertex. ``'vertices'`` passes a set, possibly
        empty. An edge is ``(source, target)`` or ``(source, target, key)``
        when multiedges are enabled. ``'edges'`` passes a set of edge tuples.
        ``'any'`` passes a snapshot with ``nodes``, ``edges`` (tuples), and
        ``regions`` sets. An iterable such as ``['vertex', 'edges', 'vertex']``
        collects those inputs successively, in order. It is consumed once.
        Each successive input must be nonempty. Enter confirms the next input
        and Esc cancels.
    context : bool, optional
        Append a :class:`ButtonContext` argument for selection and view access.

    Returns
    -------
    callable
        Decorator that registers the function and returns it unchanged.

    Notes
    -----
    The first callback argument is an ordinary NetworkX graph copy. Edit it
    in place and return ``None``, or return a replacement graph. One
    successful invocation is one undoable action. The function's first
    docstring line becomes the button tooltip.

    Examples
    --------
    ``@button('Grow', shortcut='G', selection='vertex')`` can decorate a
    function ``grow(graph, vertex)`` that adds a neighbor.
    """
    from graph_builder_core.actions import Action
    from graph_builder_core.model.selection import capture_selection, selection_argument, selection_matches
    if selection is None or isinstance(selection, str):
        kinds = () if selection is None else (selection,)
    else:
        try:
            kinds = tuple(selection)
        except TypeError as error:
            raise ValueError('selection must be an input kind or an iterable of kinds.') from error
        if not kinds:
            raise ValueError('selection must contain at least one input kind.')
    valid_kinds = ('vertex', 'vertices', 'edge', 'edges', 'any')
    if any(kind not in valid_kinds for kind in kinds):
        raise ValueError("Selection kinds must be 'vertex', 'vertices', 'edge', 'edges', or 'any'.")
    use_context = context

    def decorate(function):
        title = name if isinstance(name, str) else function.__name__.replace('_', ' ').capitalize()
        documentation = inspect.getdoc(function)
        description = documentation.splitlines()[0] if documentation else None

        def available(context):
            return (len(kinds) > 1 or not kinds
                    or selection_matches(context.selection, kinds[0]))

        def invoke(context):
            graph = public_graph(context.graph)
            orientations = {frozenset((u, v)): (u, v) for u, v in graph.edges()} if not graph.is_directed() else None
            args = [graph]
            if len(kinds) > 1:
                args.extend(selection_argument(group, kind, graph.is_multigraph())
                            for group, kind in zip(context.interaction._completed_selections, kinds))
            elif kinds:
                args.append(selection_argument(capture_selection(context.selection, kinds[0]),
                                               kinds[0], graph.is_multigraph()))
            if use_context:
                args.append(ButtonContext(context))
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
                                          shortcut, invoke, available, description=description,
                                          selection_types=kinds)
        return function

    return decorate(name) if callable(name) else decorate
