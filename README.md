# Graph Builder

Graph Builder is a Python graph editor built with Qt and NetworkX. It edits
directed or undirected coloured graphs, supports curved edges, labels, grids,
selection, undo and redo, custom graph actions, GraphML files and TikZ export.

## First launch: download the app

Download the archive for your computer from [Releases](https://github.com/CyrilPujol/graph-builder/releases), then extract it. These downloads include Python and the editor's dependencies. You do not need a terminal or a Python installation.

- **macOS:** open `Graph Builder.app`. You can move it to Applications. There are separate Apple Silicon and Intel downloads.
- **Windows:** open the extracted `Graph Builder` folder and double-click `Graph Builder.exe`. Keep the entire folder together.
- **Linux:** extract the archive and launch the `Graph Builder` executable inside its folder. If your file manager will not launch it, run `./Graph\ Builder/Graph\ Builder` from the extracted directory.

These builds are currently unsigned. Your operating system may ask you to confirm that you trust the downloaded app. On macOS, use **Open** from the app's context menu if a normal double-click is blocked. On Windows, use **More info → Run anyway** only if the publisher and download are the ones you expected. On its first launch, the app offers a skippable, action-driven tour that starts with an almost-complete M₂(C₅) graph. Later launches start with a new untitled graph. The tour can be replayed from the **?** guide. Replaying asks before replacing a nonempty graph.

The release archives are made on their own operating systems. [Build instructions](BUILDING.md) explain how to reproduce them.

## Use it as a Python library

Python 3.10 or newer is required. Open a terminal and use the commands below.

On macOS or Linux:

```sh
cd "/path/to/graph_builder"
python3 -m pip install --user -e .
python3 graph_builder.py
```

On Windows (PowerShell):

```powershell
cd "C:\path\to\graph_builder"
py -3 -m pip install --user -e .
py -3 graph_builder.py
```

Replace the path in the `cd` command with the location where you extracted or cloned the source. This installs Graph Builder for your normal Python user account, so scripts run with that Python can import `graph_builder` from any folder. If your Python installation refuses direct installs, use a virtual environment instead. Installing the downloadable app does not install the Python library.

The project stays in place, so editing its Python files changes the app. Add
`--graph path/to/drawing.graphml` to the launch command to open a specific file.
Running `graph_builder.py` directly starts a clean, untitled editor without personal custom buttons. It asks where to save when you first save the drawing. Calling `main()` from your own script retains the original `graph.graphml` default in that script's working directory, unless you pass `graph_file` or `untitled=True`. An unsaved graph made with **File → New** asks before closing. File dialogs are
supplied by Qt on macOS, Windows and Linux.

To use the editor as one step in a Python program, call `edit_graph` instead of
`main`:

```python
import networkx as nx
from graph_builder import edit_graph

graph = edit_graph(nx.path_graph(4))  # Draw or edit, then close the window.
print(graph.number_of_edges())       # Continue with the edited graph.
```

`edit_graph()` also starts with an empty graph. It accepts an `nx.Graph` or
`nx.DiGraph`, leaves the input untouched, and returns the currently open graph
when its window closes. Returned vertex keys are integers. Input integer keys
are preserved, while other keys are assigned fresh integers and kept as
visible labels if no label was set. Vertices added in the editor also receive
integer keys. Saving a file is optional. `main()` remains the simple
launcher for a standalone editor and returns an application exit code rather
than a graph. Both calls discover `@button` functions in the calling module.

`graph_builder.py` is the stable import surface, not a place for personal changes. The implementation lives in `graph_builder_core/`. Copy [`examples/custom_buttons.py`](examples/custom_buttons.py) into your own project and run that copy for your own Custom buttons. If you keep personal scripts or drawings in this checkout, put them in `local/`, which Git ignores. Put drawings you intend to share under `examples/`.

## Editing

The top menu row (File, Edition, Structure, Layout, Appearances, Metrics,
Standard graphs, Custom) shows one compact
row of controls for the chosen menu. Click the active menu again to collapse the
controls completely. The small **?** button opens a quick controls guide inside
the editor. The canvas uses a single interaction mode:

- Left-click a vertex or edge to select it. Left-click empty space to create a vertex. Drag a vertex to move it; drag empty space for a vertex-only rectangle selection.
- Right-drag (or Ctrl-left-drag) from a vertex to another vertex to toggle an edge. Starting from a selected vertex applies this to every selected vertex. Right-clicking a vertex without dragging deletes that vertex, even when other vertices are selected.
- Hold Shift during a right-drag to make a path. Each vertex you pass through immediately receives an edge from the previous vertex and becomes the next starting point. You can press or release Shift partway through the drag. Releasing over a final vertex completes the last edge. The whole path is one undo step. On a trackpad, Ctrl+Shift-left-drag does the same, while a Ctrl+Shift-left-click still removes a vertex from the selection.
- Right-drag empty space for a lasso selection. A click on empty space clears an existing selection. Option/Alt-drag or middle-drag pans. Two-finger trackpad scrolling pans in both directions, and pinching zooms around the gesture. A mouse wheel still zooms around the pointer, while a horizontal wheel pans.
- Hold Shift while clicking, rectangle-selecting or lasso-selecting to add; Ctrl+Shift removes instead.
- Double-click a vertex or edge to open **Properties** for its label and appearance. A double-click inside a selection of the same kind edits the whole group without touching labels. **Appearances → Rename** remains a quick single-label action. Internal vertex IDs stay stable and labels may repeat. **Delete** (or the Del key) removes the selection.
- Select an edge and choose **Curve point** to add a point on its current path. Drag an orange curve handle to reshape the edge; secondary-click a handle (or select it and press Del) to remove it. Drag directly on a selected edge to create a new curve point at the press position and move it in one gesture.
- **Edition** contains Undo, Redo, Copy, Paste, Select all, Select colors, Delete, and transformations. With nothing selected, transformations act on the whole graph. Grow and Shrink scale vertex positions and internal curve points without changing the view zoom.
- **Structure** controls Directed, Multiedges, and Loops. It also has Cut, Contract, Fuse, Complement, Twin, Pendant, Full join, Make region, and graph products. Pendant keeps the original selection so repeated presses can grow a tree. Fuse (F) identifies vertices with nearly the same position.
- **Layout** offers Fit graph, Manual, Automatic, Axes, and square, radial or triangular guides. Automatic shows arrangement controls without a drawing grid. Grid spacing changes by factors of two without moving untouched vertices. Axes is the startup guide, with Auto-snap enabled. During a drag, a blue line shows an alignment that will snap. Auto-snap aligns moved vertices with other visible vertices, an axis, or the origin.
- **Appearances** controls labels, basic styles, curves, and style copy and paste. The Properties dialog shows label and style first, then expands for detailed appearance and raw TikZ options. Changes preview directly on the canvas. Cancel restores the original appearance. Basic styles can be edited and reset to their built-in look. Vertex style 0 is white with a black outline. Raw TikZ options appear last in the export and can override generated options. They may not render on the canvas and can cause LaTeX errors.
- **File** contains New, Open, Save, Save As, Export to TikZ, and Export picture. **Custom** shows functions registered by a personal Python launcher. In the standalone app, it explains how to use a Python script instead.
- Built-in vertex styles begin with white, red, blue, green, orange, and purple. Further colors use perceptual spacing with extra contrast between consecutive styles. Vertex and edge style counts can grow beyond 12 without a fixed limit.
- **Structure → Full join** (J) connects two vertex sets. Select the first set and click Full join, then select the second set and click it again. The first set keeps an amber ring while the second is chosen. Esc cancels. Shared vertices can gain loops when Loops is enabled. In directed graphs, arcs go from the first set to the second. With Multiedges enabled, each pair gains one more edge. The completed join is one undoable action.
- **Structure → Product** offers tensor, Cartesian, and lexicographic products. Select the first factor, choose the product, select the second factor, then click the highlighted button or press Enter. The result is added near the center of the current view and can be undone in one step. Enter also confirms other two-step operations.
- **Metrics → Morphism** searches for a graph homomorphism from the first selected induced subgraph G to the second H. Select G, click Morphism, select H, then click again. The optional OR-Tools solver runs for at most one minute and can be stopped. A witness lifts H's vertex and edge appearances to G using inherited basic styles, without changing labels, positions, or curves. If H is uniform, its vertices first receive distinct numbered styles. The result is one undoable action.
- **Metrics → Minor** uses the same two-step workflow to test whether the first selected graph contains the second as an undirected minor. It ignores arrow directions, loops, and parallel copies. A witness colors the connected branch sets with inherited styles from the second graph. A timeout does not mean the minor is absent.
- **Structure → Make region** fills a selected edge cycle, following curved edges, or the convex hull of selected vertices. Without a suitable selection, click vertices and adjacent edges to trace a closed boundary. Regions sit behind edges and vertices, can be selected, deleted, and edited by double-clicking. Alt-click inside a region to add a vertex there. Their styles can be copied and pasted. Regions are included in GraphML and TikZ export. **Edition → Select colors** selects every vertex with the same style indices as the selected vertices, even if some have custom looks. **Appearances → Remove coloring** resets vertices, edges, and regions to their default looks.
- **Structure → Directed / Multiedges / Loops** controls the graph model. Multiedges and loops are off by default. With multiedges enabled, an edge drag always adds an edge. Its path uses the nearest available straight or bent route, checking existing paths and intervening vertices. To create a compact loop, secondary-drag outside a vertex and back to it. Disabling loops removes them. Disabling multiedges keeps one edge per pair. Both changes can be undone.
- When directed arcs overlap, clicking near an arrowhead selects that arc. Parallel edges retain their individual labels, styles, and curve points when saved or exported.
- **Layout → Automatic → Arrange** applies a force-directed placement immediately. With selected vertices, only those vertices move. With no selection, all unpinned vertices move. A full-graph arrangement stays centered in the current view and fits comfortably within it. It also works without the optional NumPy package, using a pure-Python fallback. Undo restores the previous drawing in one step. Pin and Unpin selection mark vertices as layout anchors, but pinned vertices can still be moved by hand. Pins survive saving and loading. **Relax while dragging** is optional and initially off. While a vertex is held with the mouse, even without pointer movement, it adjusts only unpinned vertices directly adjacent to the held or dragged vertices. Every other vertex stays fixed. Vertices at distance two still act as fixed anchors in the force calculation.
- **Metrics** opens a closable, copyable results panel for the whole graph or selected vertices. Overview shows degree statistics, girth, and distances. Structure checks bipartiteness, planarity, perfectness, tree and forest status, and Eulerian status. Distances are **∞** when the graph is disconnected. Bounds covers clique and independence numbers, vertex and edge chromatic numbers, minimum vertex and edge covers, maximum matching, domination number, domatic number, and tree-width. Exact quick results appear as single values. Otherwise, **Compute** searches for tighter bounds or an exact result for up to one minute and becomes **Stop** during the search. **Show** colors a solution with inherited styles in one undoable edit. For tree-width, Show adds translucent regions for decomposition bags without moving or relabeling vertices. The **House of Graphs** button opens a graph6 search in your browser for a simple undirected graph without loops. Matching and edge cover are computed exactly without the optional solver. Other difficult computations use OR-Tools, which Python-library users can install with `python -m pip install --user -e '.[solver]'` from the project folder. Changes to positions or styles keep metrics current. Changes to graph structure or the relevant selection mark them outdated, with a ⟳ button to refresh.

Python scripts can call `from graph_builder import optimize_graph` and then `clique, independent, coloring = optimize_graph(graph, seconds=5)`. Each result has `lower`, `upper`, `witness`, and `optimal` fields. This also requires the optional solver install.
- **Standard graphs** offers Petersen, cliques, complete bipartite graphs, paths, cycles, regular trees, rectangular grids, hypercubes, dodecahedra, icosahedra, Kneser, Schrijver and Paley graphs, and random graphs. Choose a family, set its parameters, then click **Add graph**. The menu shows its vertex and edge counts or a validation message. The new component appears in the center of the visible canvas and is selected for immediate dragging. Existing graph content and drawing-grid settings are preserved. A regular tree has the chosen degree at each internal vertex and the chosen depth from root to leaves. Paley vertices appear in numeric clockwise order; Kneser and Schrijver layouts follow cyclic-shift orbits, with `KG(5,2)` drawn as a Petersen graph. Schrijver `SG(n,k)` keeps only the cyclically nonadjacent `k`-subsets and requires `n ≥ 2k`.
- Keyboard shortcuts include Space for Fit graph, S and Shift+S for next and previous style, C for Cut, L for labels, P for Pendant, W for twin, O for contract, Esc to deselect, ⌘A to select all vertices, and the usual platform shortcuts for save, copy, paste and undo/redo. Button tooltips show the shortcut when one is available. Custom buttons also show the first line of their function's docstring.

**File → Export to TikZ** writes the visible vertex and edge labels to a `.tex`
file. **File → Export picture** renders that TikZ as PDF, SVG, or a transparent
300-dpi PNG. This needs a local LaTeX installation with TikZ and `standalone`.
For PNG and SVG, install Poppler's `pdftocairo` too. SVG can alternatively use
`dvisvgm` if its PDF support is available. These tools are not bundled in the
downloadable app. GraphML save/load keeps positions, colors, labels and edge
curves.

Vertex and edge labels are always interpreted as LaTeX by TikZ export. Write
`\\#` for a literal `#` and use normal LaTeX syntax for other special
characters. The editor canvas displays the source text without typesetting it.

## Custom Python functions

The smallest user script is:

```python
from graph_builder import *
main()
```

Add a button by decorating an ordinary NetworkX function **before** calling
`main()`. Only decorated functions (and explicitly declared `Action` objects)
are discovered; helper functions are not turned into buttons.

```python
import networkx as nx
from graph_builder import *

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
are not enforced. Simple undirected documents provide `nx.Graph` and simple
directed documents provide `nx.DiGraph`. With Multiedges enabled, functions
receive the corresponding `nx.MultiGraph` or `nx.MultiDiGraph`.

For more control, add a name, shortcut, or selection argument:

```python
@button('Grow a leaf', shortcut='G', selection='vertex')
def grow(graph, vertex):
    graph.add_edge(vertex, unused_label(graph))
```

`selection='vertex'` enables the button only when exactly one vertex and no
edges are selected. `'edge'` passes a `(source, target)` pair for one selected
simple edge, or `(source, target, key)` when Multiedges is enabled. `'vertices'` passes a set of selected vertices, including
endpoints of selected edges; it can be empty, so the function can decide whether
that means “do nothing” or “use the whole graph”. No selection option means
only the graph is passed. Choose shortcuts that do not conflict with existing
editor commands. An already-defined function can be registered with
`my_button = button('My function')(my_function)`.

Missing drawing attributes are supplied automatically:

- Existing vertices keep their positions and colors when a returned graph omits those attributes. New vertices are placed near their neighbors, or around the visible viewport center, without moving existing vertices.
- New vertices use basic style 0 (`col=0`), which is white by default. Visible labels default to their NetworkX node names, and edge labels to the empty string.
- Arbitrary hashable NetworkX node names receive collision-free integer IDs. Labels are separate from IDs and need not be unique. Existing integer keys are preserved.
- Numeric strings for positions and color indices are accepted. Color indices must be nonnegative integers; the palette grows if necessary.
- Document settings are preserved. A custom function cannot silently change directedness. Enable Directed, Multiedges or Loops in Structure before a function needs them.

Each successful change is one undoable action. Newly added vertices become the
selection. Invalid return values, positions, colors, loops or parallel edges
while their controls are disabled, and exceptions propagate normally, with their traceback available to a
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
`nx.DiGraph` or `nx.MultiDiGraph`, with two arcs per undirected edge. They are responsible for valid
editor attributes. `main(actions=[my_button, degree_button])` can be used instead
of automatic discovery, including when embedding the editor in another program.
`--graph FILE` remains supported by `main()`.

The supplied [`examples/custom_buttons.py`](examples/custom_buttons.py) shows a working custom function you can copy and edit. The desktop app itself does not load personal scripts or custom buttons.

The public entry point is `graph_builder.py`. Its model, editor, exporters,
layout tools and styling code live in `graph_builder_core/`. The root-level
`graph_builder_lib.py` and `tikz_export.py` are compatibility imports for
older scripts. `scripts/` contains the standalone app entry point and build
tools. The downloaded app does not read files from `local/`.
