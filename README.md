# Graph Builder

Graph Builder is a Python graph editor built with Qt and NetworkX. It edits
directed or undirected coloured graphs, supports curved edges, labels, grids,
selection, undo and redo, custom graph actions, GraphML files and TikZ export.

## Install and run

Python 3.10 or newer is required. In the project folder:

```sh
python -m venv .venv
```

On macOS or Linux:

```sh
.venv/bin/python -m pip install -e .
.venv/bin/python graph_builder.py
```

On Windows (PowerShell):

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe graph_builder.py
```

The project stays in place, so editing its Python files changes the app. Add
`--graph path/to/drawing.graphml` to the launch command to open a specific file.
By default, the editor opens `graph.graphml` in the current working directory,
or creates that file when the graph is first saved. Named graphs save on close;
an unsaved graph made with **File → New** asks before closing. File dialogs are
supplied by Qt on macOS, Windows and Linux.

`graph_builder.py` is the file to edit for personal buttons. The editor and
reusable graph code live in the other Python modules. The default
`graph.graphml` and `graph.tex` are ignored by Git so a local drawing or export
is not accidentally included in a source push. Put any drawings you intend to
share under `examples/`.

## Editing

The top menu row (File, Basic, Edition, Grid, Graph properties, Layout, Info,
Standard graphs, Custom) shows one compact
row of controls for the chosen menu. Click the active menu again to collapse the
controls completely. The canvas uses a single interaction mode:

- Left-click a vertex or edge to select it. Left-click empty space to create a
  vertex. Drag a vertex to move it; drag empty space for a vertex-only rectangle
  selection.
- Right-drag (or Ctrl-left-drag) from a vertex to another vertex to toggle an
  edge. Starting from a selected vertex applies this to every selected vertex.
  With no selection, right-clicking a vertex without dragging deletes it.
- Hold Shift during a right-drag to make a path. Each vertex you pass through
  immediately receives an edge from the previous vertex and becomes the next
  starting point. You can press or release Shift partway through the drag.
  Releasing over a final vertex completes the last edge. The whole path is
  one undo step. On a trackpad, Ctrl+Shift-left-drag does the same, while a
  Ctrl+Shift-left-click still removes a vertex from the selection.
- Right-drag empty space for a lasso selection. A click on empty space clears an
  existing selection. Option/Alt-drag or middle-drag pans, and the wheel zooms
  around the pointer.
- Hold Shift while clicking, rectangle-selecting or lasso-selecting to add;
  Ctrl+Shift removes instead.
- Double-click a vertex or edge to open **Properties** for its label and
  appearance. A double-click inside a selection of the same kind edits the
  whole group without touching labels. **Basic → Rename** remains a quick
  single-label action. Internal vertex IDs stay stable and labels may repeat.
  **Delete** (or the Del key) removes the selection.
- Select an edge and choose **Curve point** to add a point on its current path.
  Drag an orange curve handle to reshape the edge; secondary-click a handle
  (or select it and press Del) to remove it. Drag directly on a selected edge
  to create a new curve point at the press position and move it in one gesture.
- **Basic** contains Undo, Redo, Copy, Paste, Select all, Delete, Fit graph,
  Rename, and seven Transformation buttons. Grow and Shrink scale the selected
  vertices by 1.1 or 1/1.1 around their center, including internal edge curve
  points, without changing the view zoom. **Edition** contains Type −/+,
  Curve point, Vertex cut, Contract, Complement, and Pendant. Pendant adds
  one outward-growing leaf to each selected vertex and keeps the original
  selection, so repeated presses add more children. **File** contains New,
  Open, Save, Save As, and Export to TikZ.
  **Grid** offers square, radial or triangular grids and a radial count up to 99. Its fixed
  origin is `(0, 0)`, one coordinate unit is four vertex diameters, and the
  default precision is `1/4`. The + precision button halves grid spacing; −
  doubles it. Changes use exact factors of two without
  moving untouched vertices. In the radial grid, main rays are bold; rays from
  the one-unit precision pattern and one-unit circles are semi-bold.
  **Graph properties** controls labels, vertex/edge
  type counts and directedness. Its **Styles** menu opens Properties, shared
  type styles, named presets, and Copy/Paste style. Ctrl+Shift+C and
  Ctrl+Shift+V copy and paste an independent appearance snapshot. A style
  inherits from its type, then an optional named preset, then
  individual overrides. Removing a preset freezes its users' appearances.
  The Properties dialog shows the label and type first. Its expandable Advanced
  section has one whole-look choice, preview, LaTeX labels,
  and raw TikZ options. Raw options appear last in the export and can override
  generated options. They are not fully previewed and may fail to compile.
  **Custom** contains Graph coloring, Twin, Switch, Randomize, and Distance-2
  colors.
- **Layout → Arrange** applies a force-directed placement immediately. With selected
  vertices, only those vertices move. With no selection, all unpinned vertices
  move. Undo restores the previous drawing in one step. Pin and Unpin selection mark vertices as layout anchors, but
  pinned vertices can still be moved by hand. Pins survive saving and loading.
  **Relax while dragging** is optional and initially off. While a vertex is
  held with the mouse, even without pointer movement, it adjusts only
  unpinned vertices directly adjacent to the held or dragged vertices. Every
  other vertex stays fixed. Vertices at distance two still act as fixed
  anchors in the force calculation.
- **Info** opens a closable results panel. Choose Overview, Structure,
  Distances or Bounds, for the whole graph or the vertices in the current
  selection. Overview includes degree statistics; results can be copied.
  Directed graphs show in-degree, out-degree, weak and strong components.
  Structure shows component counts and largest sizes, and checks
  bipartiteness, planarity, tree/forest and Eulerian status,
  plus average clustering. Tests that ignore arrow directions say so.
  Distances are **∞** for a disconnected graph (or a directed graph that is not
  strongly connected). Small connected graphs receive exact distances; large
  ones receive a diameter lower bound and a sampled mean distance.
  Bounds shows a found clique and independent set as lower bounds and a greedy
  coloring as an upper bound on the chromatic number. `≥` and `≤` are guaranteed
  bounds; `≈` labels a sampled estimate. Longer calculations have a two-second
  limit and report when no result was computed. Results are marked outdated
  after the graph changes.
- **Standard graphs** offers Petersen, cliques, complete bipartite graphs,
  paths, cycles, regular trees, rectangular grids, hypercubes, dodecahedra,
  icosahedra, Kneser, Schrijver and Paley graphs, and random graphs. Choose a type, set
  its parameters, then click **Add graph**. The menu shows its vertex and edge
  counts or a validation message. The new component appears in the center of
  the visible canvas and is selected for immediate dragging. Existing graph
  content and drawing-grid settings are preserved. A regular tree has the
  chosen degree at each internal vertex and the chosen depth from root to
  leaves. Paley vertices appear in
  numeric clockwise order; Kneser and Schrijver layouts follow cyclic-shift
  orbits, with `KG(5,2)` drawn as a Petersen graph. Schrijver `SG(n,k)` keeps
  only the cyclically nonadjacent `k`-subsets and requires `n ≥ 2k`.
- Keyboard shortcuts include Space for Fit graph, A for a curve point, T and
  Shift+T for next and previous type, C for Vertex cut, L for labels, P for Pendant, W for twin, S for
  switch, O for contract,
  Esc to deselect, ⌘A to select all vertices, and the usual
  platform shortcuts for save, copy, paste and undo/redo. Button tooltips show
  the shortcut when one is available.

**File → Export to TikZ** writes the visible vertex and edge labels to a `.tex`
file. GraphML save/load keeps positions, colors, labels and edge curves.

## Custom Python functions

The smallest user script is:

```python
from graph_builder_lib import *
main()
```

Add a button by decorating an ordinary NetworkX function **before** calling
`main()`. Only decorated functions (and explicitly declared `Action` objects)
are discovered; helper functions are not turned into buttons.

```python
import networkx as nx
from graph_builder_lib import *

@button
def graph_coloring(graph):
    colors = nx.coloring.greedy_color(graph.to_undirected())
    nx.set_node_attributes(graph, colors, 'col')
    return graph

main()
```

This creates **Custom → Graph coloring**. Returning a graph and modifying it
in place without a return statement are both supported. Decorated functions
remain ordinary callable Python functions. Type annotations are optional and
are not enforced. Undirected documents provide an ordinary `nx.Graph` (each
edge occurs once); directed documents provide `nx.DiGraph`.

For more control, add a name, shortcut, or selection argument:

```python
@button('Grow a leaf', shortcut='G', selection='vertex')
def grow(graph, vertex):
    graph.add_edge(vertex, unused_label(graph))
```

`selection='vertex'` enables the button only when exactly one vertex and no
edges are selected. `'edge'` similarly passes a `(source, target)` pair for a
single selected edge. `'vertices'` passes a set of selected vertices, including
endpoints of selected edges; it can be empty, so the function can decide whether
that means “do nothing” or “use the whole graph”. No selection option means
only the graph is passed. Choose shortcuts that do not conflict with existing
editor commands. An already-defined function can be registered with
`my_button = button('My function')(my_function)`.

Missing drawing attributes are supplied automatically:

- Existing vertices keep their positions and colors when a returned graph
  omits those attributes. New vertices are placed near their neighbors, or
  around the visible viewport center, without moving existing vertices.
- New vertex colors default to black (`col=0`), visible labels to their
  NetworkX node names, and edge labels to the empty string.
- Arbitrary hashable NetworkX node names receive collision-free string IDs.
  Labels are separate from IDs and need not be unique.
- Numeric strings for positions and color indices are accepted. Color indices
  must be nonnegative integers; the palette grows if necessary.
- Document settings are preserved. A custom function cannot silently change
  directedness: choose it in Graph properties first.

Each successful change is one undoable action. Newly added vertices become the
selection. Invalid return values, positions, colors, unsupported loops/parallel
edges, and exceptions propagate normally, with their traceback available to a
debugger. A failed action does not commit its working copy. Custom attributes
must be strings, numbers, or booleans so GraphML saving remains possible
(encode structured data as JSON text). Labels are also used by TikZ export.

For full control, existing `ContextAction`, `GraphAction`, `VertexAction`,
`VertexGroupAction`, `EdgeAction`, and `Action` APIs remain available. For example:

```python
degree_button = ContextAction(
    lambda context: context.box.write(f'{len(context.graph)} vertices'),
    name='Vertex count',
)
```

These advanced actions retain the editor's internal graph representation:
`nx.DiGraph`, with two arcs per undirected edge. They are responsible for valid
editor attributes. `main(actions=[my_button, degree_button])` can be used instead
of automatic discovery, including when embedding the editor in another program.
`--graph FILE` remains supported by `main()`.

The supplied `graph_builder.py` shows working custom functions you can edit
or replace. The automated tests cover missing attributes, validation errors,
and rollback without adding test buttons to the application.

The reusable graph operations, built-in actions, and extension API are in
`graph_builder_lib.py`; the decorator, graph conversion and validation are in
`graph_builder_custom.py`. Qt canvas items
are in `graph_builder_qt_canvas.py`, standard graph generators and layouts are
in `standard_graphs.py`, automatic placement is in `graph_layout.py`, and
menus/files/history are in `graph_builder_qt.py`.

## Tests

```sh
.venv/bin/python -m unittest discover -s tests -v
```

On Windows, use `.\.venv\Scripts\python.exe` in place of `.venv/bin/python`.
