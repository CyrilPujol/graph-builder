# Extension menus

For a runnable tour of the controls, run `python examples/example_extension.py`
from the project directory, using the Python environment where this checkout is
installed. Explore **Showcase**, **Properties → Custom**, and
**Standard graphs → Wheel**. Import its `showcase` object and pass
`main(extensions=[showcase])` to use it from another script.

An extension adds a top-level menu for a research area or another specialized workflow. An extension is Python code, not a drawing file. Install only packages you trust, since their code runs in the editor's Python process. The downloadable desktop app is self-contained and does not discover packages installed in a separate Python environment. Extensions are for library launches with `main()` or `edit_graph()`.

## One-file extension

```python
from graph_builder import ExtensionMenu, main

logic = ExtensionMenu('Logic')

@logic.button('Mark endpoints', selection='vertices')
def mark_endpoints(graph, vertices):
    for vertex in vertices:
        graph.nodes[vertex]['style'] = 1

main()
```

This creates a **Logic** menu with one button. The function has the same public NetworkX and undo behavior as `@button`. It does not also appear in the Custom action menu. `@logic.button` without a title uses the Python function name. Add `shortcut='M'` for a shortcut and `when=lambda graph: len(graph) > 0` for a conditional button. The predicate receives an ordinary NetworkX copy and should be fast.

Build richer menus without changing Graph Builder's UI source:

```python
logic.text('A short explanation')
logic.separator()
logic.choice('Method', ('Fast', 'Exact'), key='method')
logic.input('Formula', key='formula', placeholder='P(x)')
logic.toggle('Show witness', key='witness', default=True)
logic.slider('Search depth', 1, 20, key='depth', default=5)

def less(graph):
    graph.graph['level'] = max(0, graph.graph.get('level', 0) - 1)

def more(graph):
    graph.graph['level'] = graph.graph.get('level', 0) + 1

logic.step('Level', less, more)

@logic.button
def run_search(graph):
    method = logic.value('method')
    depth = logic.value('depth')
    show = logic.value('witness')
    # Apply the chosen calculation to the graph.
```

`text` also accepts a fast `text(graph)` callback, refreshed after graph edits. `step` accepts optional `can_decrease(graph)` and `can_increase(graph)` predicates. A submenu groups previously declared buttons:

```python
logic.submenu('More actions', [run_search, mark_endpoints])
```

## Successive selections and editor access

```python
@logic.button('Connect sets', selection=['vertices', 'vertices'])
def connect_sets(graph, first, second):
    graph.add_edges_from((u, v) for u in first for v in second if u != v)
```

The first click captures and highlights the selected vertices. Select the next
set and click again, or press Enter. Esc cancels. Sets may overlap. The function
runs only after all selections are captured, as one undoable graph change.
Use `selection=['vertex', 'edges', 'vertex']` to collect mixed inputs, passed
as `graph, start, edges, end`. Each entry can be `'vertex'`, `'vertices'`,
`'edge'`, `'edges'`, or `'any'`. Edges are NetworkX tuples, including keys for
multigraphs. `'any'` passes a snapshot with `nodes`, `edges`, and `regions` sets.
The iterable is consumed once. Each stage must be nonempty, and captured vertices
and edges stay marked in amber. This works with plain `@button` and inside a
submenu too.
A pending submenu can be clicked directly to continue.

For view and selection operations, add `context=True`. The last callback argument
is an editor context with `selected_vertices`, `select(vertices)`, `view_center`,
`center_on(x, y)`, `zoom(factor)`, `fit()`, and `message(text)`. Coordinates use the
same units as node `position`. View-only and selection-only operations do not add
undo entries. Graph mutations still use the normal undo pipeline.

`toggle(..., on_change=callback)` optionally invokes `callback(graph, checked)`
on each click, with undoable graph edits. Without it, a toggle only stores an
extension setting. Extension settings themselves are not document history.
Add `checked=lambda graph: ...` for a toggle that reflects the current document,
including undo and redo, as demonstrated by Names in the example.

## Parameters and graph families

Use `@logic.parameter('Name')` with the same `.compute` and `.show` decorators
as `@parameter`. Registering on the menu means the parameter travels with an
installed extension, without requiring the caller to import every function.
The quick function and Compute return the text shown in Properties → Custom.
Compute can also receive a `result` argument and set `result.data` to retain a
solution. Show receives the displayed value and, if it accepts a third
`result` argument, that stored solution. This data belongs to the current
window and current graph or selection. It is recalculated after a graph change.
Show becomes Revert after changing the drawing. Revert restores the appearance
as another undoable action. Showing or reverting an appearance change keeps the
displayed result and stored data. Another graph change restores the Show button.
When a parameter has Compute, Show is available after Compute or when the
quick function has supplied `result.data` itself.

```python
@logic.parameter('Found set')
def found_set(graph):
    return 'Click Compute'

@found_set.compute
def compute_found_set(graph, result):
    result.data = set(graph)  # Keep the witness separately from the text.
    return f'{len(result.data)} vertices found'

@found_set.show
def show_found_set(graph, value, result):
    for vertex in result.data:
        graph.nodes[vertex]['style'] = 1
```

`optimize_one(graph, 'independent', seconds=1, workers=4)` exposes the existing
solver for one problem. Its result contains `lower`, `upper`, `optimal`, and
`witness`. A timeout is not proof of optimality. Callbacks currently run on the
UI thread, so keep their time budget short. The example caps it at 1–5 seconds.

Use `@logic.standard_graph('Name', parameters=[...], estimate=..., layout=...)`
to add a family to the existing Standard graphs list, not another toolbar.
Each `GraphParameter(key, label, default, minimum, maximum)` creates a numeric
input. The decorated function receives a dictionary of parameter values and
returns a NetworkX graph. `estimate(values)` returns its vertex and edge counts
before generation, allowing the normal size limits to reject large requests.
`layout(graph, values)` returns node positions, or omit it for a circle.
The editor provides fresh IDs, viewport-centered placement, selection, and undo.
Registrations belong to the window, so they do not leak into other launches.

Dropdowns, text inputs, toggles, and sliders hold UI state. Their values are read by the extension's functions and are not saved in GraphML. Graph changes should happen inside a button or a parameter's Show function so they remain undoable. An extension can also export `@parameter` functions. Pass `extensions=[logic]` to `main()` or `edit_graph()` to select menus explicitly. Otherwise, menus defined in the calling module are discovered automatically.

## Distributing an extension

Publish a normal Python package. Its module can expose an `ExtensionMenu` object or a zero-argument function returning one. Register it in its `pyproject.toml`:

```toml
[project.entry-points."graph_builder.menus"]
logic = "your_package.logic:logic"
```

A Python-library user installs the extension into the same Python environment as Graph Builder. On the next launch, Graph Builder discovers that entry point and adds its menu. Importing an installed extension executes third-party Python code, so Graph Builder does not load arbitrary loose files or pull code from the internet. Menu names must be unique within a launch. Explicit `extensions=[...]` disables automatic entry-point discovery for that launch.

The API deliberately exposes standard controls without requiring imports from
the window implementation. Arbitrary canvas gestures and long-running cancellable
extension computations remain outside this API.
