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

## Editing

The top menu row (File, Basic, Grid, Graph properties, Standard graphs, Custom) shows one compact
row of controls for the chosen menu. Click the active menu again to collapse the
controls completely. The canvas uses a single interaction mode:

- Left-click a vertex or edge to select it. Left-click empty space to create a
  vertex. Drag a vertex to move it; drag empty space for a vertex-only rectangle
  selection.
- Right-drag (or Ctrl-left-drag) from a vertex to another vertex to toggle an
  edge. Starting from a selected vertex applies this to every selected vertex.
  With no selection, right-clicking a vertex without dragging deletes it.
- Right-drag empty space for a lasso selection. A click on empty space clears an
  existing selection. Option/Alt-drag or middle-drag pans, and the wheel zooms
  around the pointer.
- Hold Shift while clicking, rectangle-selecting or lasso-selecting to add;
  Ctrl+Shift removes instead.
- Double-click a vertex or edge, or choose **Basic → Rename** with exactly one
  selected object, to change its visible label. Internal vertex IDs stay stable
  and labels may repeat. **Delete** (or the Del key) removes the selection.
- Select an edge and choose **Curve point** to add a point on its current path.
  Drag an orange curve handle to reshape the edge; secondary-click a handle
  (or select it and press Del) to remove it. Drag directly on a selected edge
  to create a new curve point at the press position and move it in one gesture.
- **Basic** also contains color, copy/paste, Cut selection, contract,
  complement and rotation. **File** contains undo/redo, Select all and Fit graph.
  **Grid** offers square, radial or triangular grids and a radial count up to 99. Its fixed
  origin is `(0, 0)`, one coordinate unit is four vertex diameters, and the
  default precision is `1/4`. The + precision button halves grid spacing; −
  doubles it. Changes use exact factors of two without
  moving untouched vertices. **Graph properties** controls labels, vertex/edge
  color counts and directedness. **Custom** contains Degree, Twin, Switch and
  Randomize.
- **Standard graphs** offers Petersen, cliques, complete bipartite graphs,
  paths, cycles, stars, rectangular grids, hypercubes, dodecahedra,
  icosahedra, Kneser and Paley graphs, and random graphs. Choose a type, set
  its parameters, then click **Add graph**. The menu shows its vertex and edge
  counts or a validation message. The new component appears in the center of
  the visible canvas and is selected for immediate dragging. Existing graph
  content and drawing-grid settings are preserved. Paley vertices appear in
  numeric clockwise order; Kneser layouts follow cyclic-shift orbits, with
  `KG(5,2)` drawn as a Petersen graph.
- Keyboard shortcuts include A for a curve point, C for color, L for labels, T
  for Cut selection, D for degree, W for twin, S for switch, O for contract,
  Esc to deselect, ⌘A to select all vertices, and the usual
  platform shortcuts for save, copy, paste and undo/redo. Button tooltips show
  the shortcut when one is available.

**File → Export to TikZ** writes the visible vertex and edge labels to a `.tex`
file. GraphML save/load keeps positions, colors, labels and edge curves.

## Custom Python functions

The UI is separate from graph operations. The actions in `graph_builder.py`
show how to add a Python function to the **Custom** or **Basic** menu with
`ContextAction` or `Action`. Such functions receive the
NetworkX graph and can inspect `context.selection`. A function may edit the
graph in place or return a new graph. No Qt code is needed for a graph
transformation.

The reusable data and action API is in `graph_builder_lib.py`; Qt canvas items
are in `graph_builder_qt_canvas.py`, standard graph generators and layouts are
in `standard_graphs.py`, and menus/files/history are in `graph_builder_qt.py`.

## Tests

```sh
.venv/bin/python -m unittest discover -s tests -v
```

On Windows, use `.\.venv\Scripts\python.exe` in place of `.venv/bin/python`.
