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

## Actions

Decorate an ordinary NetworkX function before calling `main()`:

```python
import networkx as nx
from graph_builder import button, main

@button
def graph_coloring(graph):
    colors = nx.coloring.greedy_color(graph.to_undirected())
    nx.set_node_attributes(graph, colors, 'style')

main()
```

This appears as **Custom → Graph coloring**. The function may change its graph in place and return `None`, or return a replacement graph. It remains callable as a normal Python function. Type annotations are optional documentation, not runtime requirements. Helper functions without a decorator are ignored.

You can add a title, shortcut, and selected-object argument:

```python
@button('Grow a leaf', shortcut='G', selection='vertex')
def grow(graph, vertex):
    graph.add_edge(vertex, 'new vertex')
```

`selection='vertex'` requires one selected vertex.
`selection='edge'` requires one selected edge and passes a `(source, target)` pair, or `(source, target, key)` in a multigraph.
`selection='vertices'` passes the selected vertex IDs as a set.
No selection option passes only the graph. The decorated function always receives an ordinary `nx.Graph`, `nx.DiGraph`, `nx.MultiGraph`, or `nx.MultiDiGraph` according to the document settings.

New vertices receive positions near their neighbors, style 0, and a visible label based on their key. Existing vertices retain their drawing attributes when omitted from a returned graph. Style indices can grow as needed. Graph settings cannot be silently changed by a custom function. Enable Directed, Multiedges, or Loops in Structure first if needed. One successful action is one undo step. A Python exception propagates to your debugger and does not commit a partially changed document.

Use strings, numbers, or booleans for custom GraphML attributes. Encode structured values as JSON strings. Labels are also sent to TikZ export.

## Parameters

`@parameter` creates an entry in **Properties → Custom**. That fourth property view is shown only when at least one parameter exists. A quick function receives the graph and returns a printable value. The panel's **Whole graph / Selection** switch also applies to custom parameters.

```python
from graph_builder import parameter

@parameter('Negative edges')
def negative_edges(graph):
    return sum(data.get('style', 0) == 1 for *_, data in graph.edges(data=True))
```

Optionally attach a deeper computation and a Show action:

```python
@negative_edges.compute
def exact_negative_edges(graph):
    return negative_edges(graph)

@negative_edges.show
def highlight_negative_edges(graph, value):
    for vertex in graph:
        graph.nodes[vertex]['style'] = 1 if graph.degree(vertex) else 0
```

The **Compute** button replaces the quick value with the text it returns. If
Compute also finds a solution to draw, give it a second argument named `result`
and assign `result.data` to the solution. Show can receive that same result as a
third argument while still receiving the displayed text as its second:

```python
@negative_edges.compute
def find_negative_edges(graph, result):
    result.data = [(u, v) for u, v, data in graph.edges(data=True)
                   if data.get('style', 0) == 1]
    return f'{len(result.data)} negative edges'

@negative_edges.show
def show_negative_edges(graph, value, result):
    for u, v in result.data:
        graph[u][v]['style'] = 1
```

The stored data belongs to the current window and graph, not the saved file.
Show changes a copy of the drawing as one undoable action and then becomes
**Revert**. Revert restores the drawing as another undoable action. Other graph
edits reset the button to Show. Showing or reverting an appearance change keeps
the displayed result and its stored data available. Show is available after Compute, or immediately
if the quick function supplied `result.data` itself.

To honor the panel's Selection scope, Show may also declare an argument named
`selection`. It receives selected vertex IDs, or `None` for the whole graph.
The quick and compute functions run synchronously in the UI, so keep them
responsive. Unhandled errors propagate to Python as they do for `@button`.

You can also use `@parameter('Name', compute=slow_function, show=draw_function)` when those functions are already defined. Pass `parameters=[...]` to `main()` or `edit_graph()` to choose parameters explicitly.

# Graph data for Python functions

Graph Builder passes an ordinary NetworkX graph to `@button`, `@parameter`, and
`edit_graph()`. It is an `nx.Graph`, `nx.DiGraph`, `nx.MultiGraph`, or
`nx.MultiDiGraph` according to the document's Directed and Multiedges switches.
You can use normal NetworkX methods such as `graph.add_node()` and
`graph.add_edge()`.

```python
graph.add_node(7, label='new', style=2, position=(100, 50))
graph.add_edge(7, 8, label='weight', style=1)
```

Vertex keys are internal IDs, not displayed names. The graph returned by
`edit_graph()` has integer keys. Custom callbacks currently receive the
editor's string keys, such as `'0'`, and should treat them as opaque IDs. A
callback may add a vertex under any NetworkX key, which the editor converts
to a new internal ID when it accepts the graph. Its visible `label` can be
any string and need not be unique. An edge's default label is empty.

| Attribute | On | Meaning |
| --- | --- | --- |
| `position=(x, y)` | vertex | Canvas coordinates, with positive y downward. The editor supplies a position near neighbors for new vertices that omit it. |
| `style=0` | vertex or edge | Nonnegative index of a shared basic style. Index 0 is the default. Changing the index changes the inherited appearance. |
| `label='text'` | vertex or edge | Visible text, also used in TikZ export. |
| `style_overrides` | vertex or edge | JSON object of individual appearance overrides. Prefer the Properties dialog to edit this. |
| `curve_offsets` | edge | JSON list of control-point offsets from the endpoints' midpoint. Prefer the canvas curve-point tools to edit this. |

`style` is an index, not a literal color. Shared vertex and edge style
definitions are kept in the graph-level `vertex_styles` and `edge_styles`
attributes as JSON. An object's effective appearance is its built-in style,
then the shared style for its index, then any individual overrides. The
`num_vertex_styles` and `num_edge_styles` set the number of style choices
available in the UI.
Exact colors, line widths, shapes, and TikZ options are normally set through
the Properties dialog. Custom functions may leave these fields out.

An undirected graph appears as one edge per pair to Python functions. The
editor stores it internally as two opposite arcs with matching attributes so
the same drawing code also works for directed graphs. This is an
implementation detail, not something a custom function needs to reproduce.
With Multiedges enabled, use NetworkX's usual edge keys to distinguish
parallel edges. A directed document has one arc per direction, so two
opposite arcs may have different labels, styles, and curves. Loops and
parallel edges require their switches to be enabled in Structure before a
custom function can add them.

Regions are not NetworkX nodes or edges. Their definitions live as JSON in
`graph.graph['regions']`, with boundary, style, and padding information.
Create and edit them in the canvas unless you need to work with their internal
format. Other graph-level settings include `graph_type`, `loops`,
`multiedges`, and `show_labels`. Custom functions should not silently change
the document's graph model.

GraphML stores the same style and label attributes. Positions become
`position_x` and `position_y` in the file, then return to `position` tuples
when loaded. Older GraphML drawings and Python callbacks using the former
`col` attribute still load or run. New saves write `style` instead. New
Python functions should use `style`.


## Advanced actions

`ContextAction`, `GraphAction`, `VertexAction`, `VertexGroupAction`, `EdgeAction`, and `Action` are available for editor-aware code. These receive the internal document representation rather than the public NetworkX copy. For example:

```python
from graph_builder import ContextAction

degree_button = ContextAction(
    lambda context: context.box.write(f'{len(context.graph)} vertices'),
    name='Vertex count',
)
```

`main(actions=[degree_button])` bypasses automatic action discovery. The public import surface is `graph_builder.py`. The implementation lives under `graph_builder_core/`. Scripts in the ignored `local/` directory stay personal.

For a full new menu rather than individual functions, see [Extensions](EXTENSIONS.md).

## Signed-graph example

[The signed-graph example](../examples/example_signed_graphs.py) treats edge style 0 as positive and style 1 as negative. **Switch** changes signs across a selected vertex cut. **Double switch graph** makes two copies and reverses cross-copy signs. **Balanced** appears under Properties → Custom. The example assumes a simple undirected document with edge styles 0 and 1.
