# Custom Python functions

Install the Python library as described in the [README](../README.md#use-it-as-a-python-library). The downloadable desktop app does not execute personal Python files. Copy [the basic example](../examples/example_basic.py) to your own project, edit it there, and run your copy. The graph data section below explains the drawing attributes available to your functions.

To try the example against a development checkout, open a terminal in the project folder and run it with the Python environment used for that checkout. For example, on macOS or Linux with a project virtual environment:

```sh
./.venv/bin/python -m examples.example_basic
```

This opens the editor from the current source tree. It does not launch or update an installed desktop app.

The smallest launcher is:

```python
from graph_builder import *
main()
```

## Graph format

Callbacks receive an ordinary `nx.Graph`, `nx.DiGraph`, `nx.MultiGraph`, or
`nx.MultiDiGraph`, matching the document. Use normal NetworkX operations.

```python
graph.add_node(7, label='A', style=2, position=(100, 50))
graph.add_edge(7, 8, label=r'$\alpha$', style=1)
```

**Vertex IDs and labels.** `edit_graph()` preserves integer keys and reassigns
other keys to integers, retaining their text as labels unless already supplied.
Its return value has integer keys. Editor callbacks currently receive string
IDs such as `'0'`. Treat these as opaque keys, not labels. New keys supplied by
callbacks are normalized when accepted. Labels may repeat. Vertex labels
default to their key, edge labels to an empty string. Labels are LaTeX source
in TikZ export.

| Attribute | Applies to | Format |
| --- | --- | --- |
| `position` | vertex | `(x, y)` canvas coordinates, positive y downward |
| `style` | vertex, edge | Nonnegative shared style index, default `0` |
| `label` | vertex, edge | Visible text |
| `style_overrides` | vertex, edge | JSON object of individual style values |
| `curve_offsets` | edge | JSON list of control-point offsets from the endpoints' midpoint |

Missing positions, styles, and labels are supplied for new vertices. Missing
drawing attributes on existing vertices are retained when possible.
Style indices expand the available choices as needed.

**Shared styles.** Graph attributes `vertex_styles` and `edge_styles` hold JSON
style definitions. Effective appearance is built-in defaults, then the shared
style, then individual overrides. `num_vertex_styles` and `num_edge_styles`
control the available style counts. Prefer the Properties dialog for exact
colors, shapes, sizes, and TikZ options. Vertex `show_label` is a style property,
separate from label text. The graph-level `show_labels` switch hides all labels.

**Edges.** Public callbacks see one edge per undirected pair. Multigraph edges
use ordinary NetworkX keys. Directed opposite arcs may have different attributes.
Internally, undirected edges are stored as paired arcs with matching attributes.
Only low-level actions and file helpers expose that representation.

**Document settings.** `graph.graph` contains `graph_type` (`'graph'` or
`'digraph'`), `loops`, `multiedges`, and drawing settings. Enable Loops,
Multiedges, or Directed in Structure before adding those objects in a callback.
Normal callbacks cannot silently change the document's graph model.

**Regions and persistence.** Regions are JSON in `graph.graph['regions']`, not
NetworkX vertices or edges. Use the canvas tools unless you need their internal
boundary format. GraphML stores positions as `position_x` and `position_y`,
restoring `position` on load. Extra saved attributes must be strings, numbers,
or booleans. Encode structured values as JSON strings.

## Opening the editor

### main

Open the editor and block until its window closes.

```python
main(actions=None, graph_file=None, *, untitled=False,
     parameters=None, extensions=None, **options)
```

**Parameters**

- `graph_file`: GraphML or graph6-family file to open. Otherwise reads `--graph`,
  then defaults to `graph.graphml` in the current folder.
- `untitled=True`: start a blank, unnamed drawing instead. Cannot accompany `graph_file`.
- `actions`, `parameters`, `extensions`: explicit collections. `None` discovers
  declarations in the calling module. Extensions also include installed
  `graph_builder.menus` entry points. Use `[]` to disable a category.
- `**options`: document defaults, such as `num_vertex_styles=5`.

**Returns** An integer application exit code.

```python
from graph_builder import main
main(untitled=True)
```

### edit_graph

Edit a copy of a NetworkX graph, then continue your Python program.

```python
edit_graph(graph=None, *, actions=None, parameters=None, extensions=None)
```

**Parameters** `graph` is a NetworkX graph, or `None` for an empty graph.
The other arguments select custom functions and extensions as in `main`.

**Returns** The edited NetworkX graph with integer keys. The input is unchanged.

```python
import networkx as nx
from graph_builder import edit_graph
graph = edit_graph(nx.path_graph(4))
print(graph.number_of_edges())
```

## Custom actions and parameters

### button

Register a normal graph-editing function in Custom.

```python
@button(name=None, *, shortcut=None, selection=None, context=False)
```

**Parameters**

- `name`: button caption, defaulting to the function name.
- `shortcut`: shortcut string, for example `'G'`.
- `selection`: extra argument after the graph.

  | Value | Callback input |
  | --- | --- |
  | `None` | `function(graph)` |
  | `'vertex'` | `function(graph, vertex)`, available for one selected vertex |
  | `'vertices'` | `function(graph, vertices)`, a set including selected edges' endpoints |
  | `'edge'` | `function(graph, edge)`, one selected edge as `(u, v)` or `(u, v, key)` |
  | `'edges'` | `function(graph, edges)`, a set of those edge tuples |
  | `'any'` | `function(graph, selected)`, a snapshot with `nodes`, `edges`, and `regions` sets |

- `selection` may also be an iterable of input kinds, consumed once.
  For `['vertex', 'edges', 'vertex']`, the callback receives
  `graph, start_vertex, required_edges, end_vertex`. Each stage requires a
  nonempty selection of the requested kind. Click again or press Enter to
  confirm. Esc cancels. Captured vertices and edges remain marked in amber.
- `context=True`: append a `ButtonContext` argument.

**Returns** The original function, still callable normally. Supports `@button`,
`@button('Name')`, and `@button(...)`.

**Notes** Edit the graph copy in place and return `None`, or return a replacement
NetworkX graph. A successful graph change is one undo step. Exceptions propagate
to Python without committing a partial drawing. Annotations are optional.
The first docstring line becomes the tooltip.
For `'any'`, `nodes` contains IDs, `edges` contains NetworkX tuples, and
`regions` contains region IDs. Changing these snapshot sets does not change
the editor's selection. Use `ButtonContext.select()` to select vertices.

```python
from graph_builder import button, main

@button('Grow a leaf', shortcut='G', selection='vertex')
def grow(graph, vertex):
    """Add a neighbor to the selected vertex."""
    graph.add_edge(vertex, 'new vertex')

main()
```

### parameter

Register a measure in Properties → Custom, shown only when nonempty.

```python
@parameter(name=None, *, compute=None, show=None)
```

**Parameters** `name` defaults to the function name. `compute` and `show` are
optional callbacks, also attachable through the decorators below.

**Returns** The original quick function, with `.compute` and `.show` decorators.
Supports `@parameter` and `@parameter('Name')`.

**Callback interfaces**

| Callback | Input | Return |
| --- | --- | --- |
| Quick | `quick(graph)` or `quick(graph, result)` | Displayed value |
| `measure.compute` | `compute(graph)` or `compute(graph, result)` | Replacement displayed value |
| `measure.show` | `show(graph, value, result=None, selection=None)` | Modified graph or `None` |

`result` and `selection` are optional named callback arguments, not decorator
options. `value` is the displayed answer, not the stored solution.

- `result.value`: displayed value.
- `result.data`: arbitrary witness data assigned by Quick or Compute.
- `result.computed`: whether Compute supplied the current result.
- `selection`: selected vertex IDs, or `None` for the whole graph. Only Show
  receives this argument. Quick and Compute already receive the scoped subgraph.

Show edits a copy of the full document. It becomes Revert after a change.
Revert is also undoable. Showing or reverting preserves the parameter result.
Other document edits reset Show and may make the panel outdated.
With a Compute callback, Show is enabled after Compute or when Quick sets
`result.data`. Without Compute, Show is available immediately.
Results are window-local, not saved in GraphML. Callbacks run synchronously,
so keep computations short. Exceptions propagate to Python.

```python
from graph_builder import parameter, optimize_one

@parameter('Independent set')
def independent(graph):
    return 'Click Compute'

@independent.compute
def compute_independent(graph, result):
    answer = optimize_one(graph, 'independent', seconds=2)
    result.data = answer.witness
    return f'{answer.lower} ≤ α ≤ {answer.upper}'

@independent.show
def show_independent(graph, value, result):
    for vertex in graph:
        graph.nodes[vertex]['style'] = int(vertex in result.data)
```

## Extension menus

### ExtensionMenu

Declare a top-level menu without modifying the editor.

```python
menu = ExtensionMenu('Research')
```

**Parameters** `name` is the menu title.

**Returns** A menu declaration. Expose it in the calling module for discovery,
or pass `extensions=[menu]` to `main` or `edit_graph`.

| Method | Purpose |
| --- | --- |
| `menu.button(name=None, *, shortcut=None, selection=None, when=None, context=False)` | Like `@button`, with optional `when(graph)` availability |
| `menu.parameter(name=None, **options)` | Like `@parameter`, including `.compute` and `.show` |
| `menu.standard_graph(name, *, parameters=(), layout=None, estimate=...)` | Decorate `generate(values)` returning a NetworkX graph |
| `menu.text(text)` | Static text or fast `text(graph)` callback |
| `menu.input(label, *, key=None, default='', placeholder='')` | Text input |
| `menu.choice(label, options, *, key=None, default=None)` | Dropdown, default first option |
| `menu.toggle(label, *, key=None, default=False, on_change=None, checked=None)` | Local toggle, optional `on_change(graph, enabled)` and `checked(graph)` |
| `menu.slider(label, minimum, maximum, *, key=None, default=None)` | Integer slider, default minimum |
| `menu.step(label, decrease, increase, *, can_decrease=None, can_increase=None)` | −/+ actions and optional availability predicates, each receiving `graph` |
| `menu.separator()` | Vertical divider |
| `menu.submenu(label, actions)` | Dropdown grouping already decorated menu buttons |
| `menu.value(key)` | Current input, choice, toggle, or slider value |
| `menu.actions()` | Iterate the menu's low-level `Action` objects |

Control keys default to their labels. Control state is not saved in GraphML.
Graph-changing callbacks remain undoable.
For graph families, `estimate(values)` must return vertex and edge counts.
Optional `layout(graph, values)` returns node positions, defaulting to a circle.

```python
from graph_builder import ExtensionMenu
research = ExtensionMenu('Research')

@research.button('Connect sets', selection=['vertices', 'vertices'])
def connect(graph, first, second):
    graph.add_edges_from((u, v) for u in first for v in second if u != v)
```

See [Extensions](EXTENSIONS.md) for packaging and
[the showcase](../examples/example_extension.py) for runnable controls.

### GraphParameter

Describe a numeric input for a standard graph generator.

```python
GraphParameter(key, label, default, minimum, maximum, kind='int')
```

**Parameters** `key` identifies the value passed to generator callbacks.
`label` is its caption. `default`, `minimum`, and `maximum` define its numeric
value and limits. `kind` is `'int'`, `'probability'`, or `'optional_seed'`.

**Returns** An immutable input specification for `menu.standard_graph`.

```python
GraphParameter('n', 'Vertices', 6, 1, 100)
```

### ButtonContext

Access selection, view, and notifications from `@button(context=True)`.
The editor supplies it as the final callback argument.

| Member | Meaning |
| --- | --- |
| `selected_vertices` | A copy of selected vertex IDs |
| `select(vertices)` | Replace the vertex selection |
| `view_center` | Viewport center as graph coordinates `(x, y)` |
| `center_on(x, y)` | Move the viewport center |
| `zoom(factor)` | Multiply zoom by a positive finite factor |
| `fit()` | Center and fit the drawing |
| `message(text)` | Show a short notice |

View-only and selection-only changes do not create undo entries.
Edit the callback's graph argument for undoable document changes.

```python
@button(context=True)
def focus(graph, editor):
    editor.fit()
    editor.message(f'{len(graph)} vertices')
```

## Discovery

### discover_buttons

`discover_buttons(namespace)` returns registered `Action` objects in definition
order, without duplicates. Includes `@button` functions and explicit actions,
but excludes buttons owned by extension menus.

### discover_parameters

`discover_parameters(namespace)` returns parameter definitions without duplicates.

### discover_extensions

`discover_extensions(namespace)` returns `ExtensionMenu` objects without duplicates.
It does not load installed entry points.

For all three, `namespace` is a module dictionary, usually `globals()`.
Normally `main` and `edit_graph` handle discovery.

```python
actions = discover_buttons(globals())
main(actions=actions)
```

## File and document helpers

These helpers work with the **internal editor document**, not the normalized
public graph supplied to ordinary callbacks. Prefer `edit_graph(nx.Graph(...))`
for a Python workflow.

### empty_graph

`empty_graph(**options)` returns an empty internal `nx.DiGraph`, or
`nx.MultiDiGraph` when `multiedges=True`. Defaults: undirected document,
4 vertex styles, 2 edge styles, labels visible, no loops or multiedges.

```python
document = empty_graph(graph_type='digraph', num_vertex_styles=5)
```

### unused_label

`unused_label(graph)` returns the first unused internal string ID
`'0'`, `'1'`, … without changing the graph. Despite its name, it allocates
an ID, not a visible label. Use with internal string-key documents.

```python
vertex = unused_label(document)
document.add_node(vertex, label='A', style=0, position=(0, 0))
```

### convert_from_file

`convert_from_file(graph_file, kwargs=None, *, graph_index=0)` reads GraphML or
a graph6-family file into an internal document. `kwargs` supplies document
defaults. `graph_index` selects a zero-based graph in a compact file.

**Returns** The internal graph. A missing path returns an empty document.
Invalid file contents raise an exception.

### write_graph_file

`write_graph_file(graph, path)` saves an internal document as GraphML, creates
parent directories, and returns the destination `Path`. Positions, settings,
styles, and regions are serialized.

```python
document = convert_from_file('drawing.graphml')
write_graph_file(document, 'copy.graphml')
```

## Solver helpers

### optimize_one

Compute certified bounds and a witness for one invariant, without modifying
the input graph.

```python
optimize_one(graph, problem, seconds=60.0, workers=4)
```

**Parameters** `graph` is a NetworkX graph. `seconds` caps solver time and
`workers` sets the number of CP-SAT workers.

| `problem` | Witness |
| --- | --- |
| `'clique'`, `'independent'`, `'vertex_cover'`, `'domination'` | Vertex set |
| `'chromatic'`, `'domatic'` | Vertex-to-class dictionary |
| `'edge_chromatic'` | Edge-to-class dictionary |
| `'matching'`, `'edge_cover'` | Edge set |
| `'treewidth'` | Tree-decomposition witness |

Edge witnesses use `(source, target, key)`, with `key=None` for simple graphs.
Vertex and edge cover mean minimum cover. Matching means maximum matching.
Domination and domatic number respect arc direction. Most other invariants
use the underlying graph, with problem-specific handling of loops and parallel
edges. Proper coloring rejects loops. Size limits may reject large models.

**Returns** A result with `lower`, `upper`, `witness`, `optimal`, `elapsed`,
`name`, and `note`. Bounds remain valid after a timeout.
Matching and edge cover use NetworkX. Other searches may require OR-Tools.

```python
answer = optimize_one(graph, 'independent', seconds=2)
print(answer.lower, answer.upper, answer.witness)
```

### optimize_graph

`optimize_graph(graph, seconds=60.0, workers=4)` computes clique number,
independence number, and chromatic number within a shared time budget.

**Returns** `(clique_result, independent_result, coloring_result)`, using the
result fields above. `coloring_result` is `None` when the graph has a loop.
Directed edges are treated as undirected and parallel edges as one.
The input is unchanged. Requires OR-Tools.

## Low-level actions

These receive the internal document directly. Unlike `@button`, they do not
supply missing drawing attributes or normalize results. Use `@button` for
ordinary NetworkX functions.

### ContextAction

`ContextAction(function, shortcut=None, available=lambda context: True,
name=None, group='custom')` wraps `function(context)` as an `Action`.

**Parameters** `context` exposes `graph`, `selection` (`nodes`, `edges`,
`regions`), `box.write(message)`, `interaction` (the editor window), and
`pointer_position`. `context.replace_graph(graph)` replaces the document.
`available(context)` controls whether the action can run. `name` defaults to
the function name. `shortcut` and `group` control placement and access.

**Returns** An `Action`. The callback may edit in place, return a graph, or
replace `context.graph`.

```python
count = ContextAction(
    lambda context: context.box.write(f'{len(context.graph)} vertices'),
    name='Vertex count',
)
main(actions=[count])
```

### GraphAction

`GraphAction(function, shortcut=None, name=None, group='custom')` calls
`function(graph)` with the internal document. Always available.

### VertexAction

`VertexAction(function, shortcut=None, name=None, group='custom')` calls
`function(graph, vertex)`. Requires exactly one selected vertex and no edges
or regions.

### VertexGroupAction

`VertexGroupAction(function, shortcut=None, name=None, group='custom')` calls
`function(graph, vertices)` with selected vertex IDs. Requires a nonempty
vertex selection. Selected edges do not add their endpoints.

### EdgeAction

`EdgeAction(function, shortcut=None, name=None, group='custom')` calls
`function(graph, edge)` with `(u, v)` or `(u, v, key)`. Requires one edge and
no selected vertices.

These four factories return `Action` objects. Their callbacks may modify the
document in place or return a replacement graph.

### Action

Construct a low-level editor command directly.

```python
Action(id, name, shortcut, handler, available, library=False, group='custom',
       checked=None, pair_label=None, pair_id=None, description=None,
       selection_types=())
```

**Parameters**

- `id`: unique command identifier.
- `name`: caption string or `name(context)` callback.
- `shortcut`: shortcut string or `None`.
- `handler`: `handler(context)`, editing the internal document or returning one.
- `available`: `available(context)` predicate.
- `description`: tooltip text.
- `checked`: optional `checked(context)` predicate for toggle state.
- `selection_types`: ordered input kinds for successive selections. Empty means no selection input.
- `library`, `group`, `pair_label`, `pair_id`: built-in placement and paired-control
  metadata. Extension authors normally use `ExtensionMenu` instead.

**Returns** A command declaration. `is_available(context)` evaluates its
availability and `display_name(context)` resolves its caption.

## Examples

- [Basic launcher](../examples/example_basic.py)
- [Signed graphs](../examples/example_signed_graphs.py): switching, double switching,
  balance, and negative girth.
- [Extension showcase](../examples/example_extension.py): controls, successive
  selections, solver access, and custom graph families.
