# Graph Builder

Graph Builder is a Python graph editor built with Qt and NetworkX. It edits
directed or undirected coloured graphs, supports curved edges, labels, grids,
selection, undo and redo, custom graph actions, GraphML files and TikZ export.

## First launch: download the app

Download the archive for your computer from [Releases](https://github.com/CyrilPujol/graph-builder/releases), then extract it. These downloads include Python and the editor's dependencies. You do not need a terminal or a Python installation.

- **macOS:** open `Graph Builder.app`. You can move it to Applications. There are separate Apple Silicon and Intel downloads.
- **Windows:** open the extracted `Graph Builder` folder and double-click `Graph Builder.exe`. Keep the entire folder together.
- **Linux:** extract the archive and launch the `Graph Builder` executable inside its folder. If your file manager will not launch it, run `./Graph\ Builder/Graph\ Builder` from the extracted directory.

To open a `.graphml` file by double-clicking it, choose Graph Builder as its default app once:

- **macOS:** move `Graph Builder.app` to Applications, then use a GraphML file's **Get Info → Open with → Graph Builder → Change All**. The app also accepts **Open With** and files dropped on its Dock icon, including while it is already running.
- **Windows:** right-click `Install desktop integration.ps1` in the extracted app folder and choose **Run with PowerShell** to register the document icon. Then right-click a GraphML file and choose **Open with → Choose another app → Graph Builder → Always**. Alternatively, browse directly to `Graph Builder.exe`. Keep its whole folder in place afterward.
- **Linux:** from the extracted folder, run `sh "Graph Builder/Install desktop integration.sh"`. This copies the app into your user account, adds it to the applications list, and makes it the GraphML opener without administrator access.

GraphML is also used by other programs, so Graph Builder never silently takes over the file type when you merely extract the download.

The app supplies a static GraphML document-type icon through macOS bundle registration or the optional Windows/Linux desktop integration. Your file manager may retain a generic icon even when opening works correctly. Saving never attaches custom icons or extra metadata to individual files. These icons are not previews of each graph.

**File → Open** also imports graph6, sparse6, and digraph6 files (`.g6`, `.s6`, `.d6` and their long extensions), including loops and parallel edges where supported by the format. For files containing several graphs, choose the graph to open. Imported graphs receive an initial drawing and save as new GraphML documents, preserving the source file.

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

`graph_builder.py` is the stable import surface, not a place for personal changes. The implementation lives in `graph_builder_core/`. See [Custom Python functions and graph data](docs/PYTHON_LIB.md), the [basic example](examples/example_basic.py), and the [signed-graph example](examples/example_signed_graphs.py). If you keep personal scripts or drawings in this checkout, put them in `local/`, which Git ignores. Put drawings you intend to share under `examples/`.

To build a menu of your own, see the [extension guide](docs/EXTENSIONS.md) and
[UI showcase](examples/example_extension.py).

## Editing

The top menu row (File, Edition, Structure, Layout, Appearances, Properties,
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
- **Structure** controls Directed, Multiedges, and Loops. It also has Cut, Contract, Fuse, Complement, Twin, Pendant, Full join, and graph products. Pendant keeps the original selection so repeated presses can grow a tree. Fuse (F) identifies vertices with nearly the same position.
- **Layout** offers Fit graph, Manual, Automatic, Axes, and square, radial or triangular guides. Automatic shows arrangement controls without a drawing grid. Grid spacing changes by factors of two without moving untouched vertices. Axes is the startup guide, with Auto-snap enabled. During a drag, a blue line shows an alignment that will snap. Auto-snap aligns moved vertices with other visible vertices, an axis, or the origin.
- **Appearances** controls labels, basic styles, curves, and style copy and paste. The Properties dialog shows label and style first, then expands for detailed appearance and raw TikZ options. Changes preview directly on the canvas. Cancel restores the original appearance. Basic styles can be edited and reset to their built-in look. Vertex style 0 is white with a black outline. Raw TikZ options appear last in the export and can override generated options. They may not render on the canvas and can cause LaTeX errors.
- **File** contains New, Open, Save, Save As, Export to TikZ, and Export picture. **Custom** shows functions registered by a personal Python launcher. In the standalone app, it explains how to use a Python script instead.
- Built-in vertex styles begin with white, red, blue, green, orange, and purple. Further colors use perceptual spacing with extra contrast between consecutive styles. Vertex and edge style counts can grow beyond 12 without a fixed limit.
- **Structure → Full join** (J) connects two vertex sets. Select the first set and click Full join, then select the second set and click it again. The first set keeps an amber ring while the second is chosen. Esc cancels. Shared vertices can gain loops when Loops is enabled. In directed graphs, arcs go from the first set to the second. With Multiedges enabled, each pair gains one more edge. The completed join is one undoable action.
- **Structure → Product** offers tensor, Cartesian, and lexicographic products. Select the first factor, choose the product, select the second factor, then click the highlighted button or press Enter. The result is added near the center of the current view and can be undone in one step. Enter also confirms other two-step operations.
- **Properties → Subgraph / Induced subgraph** searches for a copy of the second selected graph inside the first. Subgraph permits extra edges in the copy, while Induced subgraph requires exactly the same adjacencies. Select the host, click the action, select the pattern, then click again or press Enter. A found copy inherits the pattern's basic styles in one undoable edit. If the pattern is uncolored, Subgraph highlights its vertices and edges with one style, while Induced subgraph highlights only its vertices. Already styled edges are always lifted.
- **Properties → Morphism** searches for a graph homomorphism from the first selected induced subgraph G to the second H. Select G, click Morphism, select H, then click again. The optional OR-Tools solver runs for at most one minute and can be stopped. A witness lifts H's vertex and edge appearances to G using inherited basic styles, without changing labels, positions, or curves. If H is uniform, its vertices first receive distinct numbered styles. The result is one undoable action.
- **Properties → Minor** uses the same two-step workflow to test whether the first selected graph contains the second as an undirected minor. It ignores arrow directions, loops, and parallel copies. A witness colors the connected branch sets with inherited styles from the second graph. A timeout does not mean the minor is absent.
- **Appearances → Make region** fills a selected edge cycle, following curved edges, or the convex hull of selected vertices. Without a suitable selection, click vertices, adjacent edges, or empty space to trace a boundary. The filled preview follows the pointer. Press Enter or click the starting point to close it, and Esc to cancel. Points placed in empty space belong only to the region and do not create graph vertices. Drag their teal handles while the region is selected to reshape it. Regions sit behind edges and vertices, can be selected, deleted, and edited by double-clicking. Alt-click inside a region to add a graph vertex there. Their styles can be copied and pasted. Regions are included in GraphML and TikZ export. **Edition → Select colors** selects every vertex with the same style indices as the selected vertices, even if some have custom looks. **Appearances → Remove coloring** resets vertices, edges, and regions to their default looks.
- **Structure → Directed / Multiedges / Loops** controls the graph model. Multiedges and loops are off by default. With multiedges enabled, an edge drag always adds an edge. Its path uses the nearest available straight or bent route, checking existing paths and intervening vertices. To create a compact loop, secondary-drag outside a vertex and back to it. Disabling loops removes them. Disabling multiedges keeps one edge per pair. Both changes can be undone.
- When directed arcs overlap, clicking near an arrowhead selects that arc. Parallel edges retain their individual labels, styles, and curve points when saved or exported.
- **Layout → Automatic → Arrange** applies a force-directed placement immediately. With selected vertices, only those vertices move. With no selection, all unpinned vertices move. A full-graph arrangement stays centered in the current view and fits comfortably within it. It also works without the optional NumPy package, using a pure-Python fallback. Undo restores the previous drawing in one step. Pin and Unpin selection mark vertices as layout anchors, but pinned vertices can still be moved by hand. Pins survive saving and loading. **Relax while dragging** is optional and initially off. While a vertex is held with the mouse, even without pointer movement, it adjusts only unpinned vertices directly adjacent to the held or dragged vertices. Every other vertex stays fixed. Vertices at distance two still act as fixed anchors in the force calculation.
- **Properties** opens a closable results panel. Its top switch shows the whole graph or the current selection and refreshes the displayed result. Select text in the panel to copy it, or hover over an item for a definition. Metrics shows counts, degrees, girth, diameter, and radius. Classes checks digon-freeness and acyclicity for directed graphs, along with bipartiteness, Eulerian status, planarity, forest and chordal status, and perfectness. For larger graphs, **Compute perfect graph** starts a cancellable one-minute check. Distances are **∞** when the graph is disconnected. Bounds covers clique and independence numbers, vertex and edge chromatic numbers, minimum vertex and edge covers, maximum matching, domination number, domatic number, and tree-width. In directed graphs, a chosen vertex dominates itself and its outgoing neighbors. Exact quick results appear as single values. Otherwise, **Compute** searches for tighter bounds or an exact result for up to one minute and becomes **Stop** during the search. **Show** displays a solution in one undoable edit and then becomes **Revert** until another edit or undo/redo. For tree-width, Show adds unlabeled translucent regions for decomposition bags without moving vertices. The **House of Graphs** button opens a graph6 search in your browser for a simple undirected graph without loops. Matching and edge cover are computed exactly without the optional solver. Other difficult computations use OR-Tools, which Python-library users can install with `python -m pip install --user -e '.[solver]'` from the project folder. Changes to positions or styles keep results current. Changes to graph structure or the relevant selection mark them outdated, with a ⟳ button to refresh.

Python scripts can call `from graph_builder import optimize_graph` and then `clique, independent, coloring = optimize_graph(graph, seconds=5)`. Each result has `lower`, `upper`, `witness`, and `optimal` fields. This also requires the optional solver install.
- **Standard graphs** offers Petersen, cliques, complete bipartite graphs, paths, cycles, regular trees, rectangular grids, hypercubes, dodecahedra, icosahedra, Kneser, Schrijver and Paley graphs, and random graphs. Choose a family, set its parameters, then click **Add graph**. The menu shows its vertex and edge counts or a validation message. The new component appears in the center of the visible canvas and is selected for immediate dragging. Existing graph content and drawing-grid settings are preserved. A regular tree has the chosen degree at each internal vertex and the chosen depth from root to leaves. Paley vertices appear in numeric clockwise order; Kneser and Schrijver layouts follow cyclic-shift orbits, with `KG(5,2)` drawn as a Petersen graph. Schrijver `SG(n,k)` keeps only the cyclically nonadjacent `k`-subsets and requires `n ≥ 2k`.
- Keyboard shortcuts include Space for Fit graph, Ctrl+Plus/Minus for zoom, S and Shift+S for next and previous style, C for Cut, L for labels, P for Pendant, W for twin, O for contract, Esc to deselect, ⌘A to select all vertices, and the usual platform shortcuts for save, copy, paste and undo/redo. Button tooltips show the shortcut when one is available. Custom buttons also show the first line of their function's docstring.
- The ⚙ button before File opens Preferences. Search actions to assign or clear keyboard shortcuts, or choose System, Light, or Dark theme. Conflicting shortcuts appear in red and can be fixed manually or automatically when saving. These choices are saved for your user account and shared by the desktop app and Python-library launches. They do not change graph files.

**File → Export to TikZ** writes the visible vertex and edge labels to a `.tex`
file. Coordinates use ordinary centimetre-scale TikZ units and compact decimals.
Curves are exported as editable Bézier paths. Directed edge styles can specify
the arrowhead shape, length, and width in the edge Properties dialog.
**File → Export picture** renders that TikZ as PDF, SVG, or a transparent
300-dpi PNG. This needs a local LaTeX installation with TikZ and `standalone`.
The fourth format, **PDF (Ipe compatible)**, adds editable Ipe data using
`pdftoipe` from ipe-tools and `ipetoipe` from Ipe. Install both tools and make
them available on PATH. PDF-to-Ipe conversion may approximate unsupported
effects or text, so check the result in Ipe before further editing.
For PNG and SVG, install Poppler's `pdftocairo` too. SVG can alternatively use
`dvisvgm` if its PDF support is available. These tools are not bundled in the
downloadable app. GraphML save/load keeps positions, colors, labels and edge
curves.

Vertex and edge labels are always interpreted as LaTeX by TikZ export. Write
`\\#` for a literal `#` and use normal LaTeX syntax for other special
characters. The editor canvas displays the source text without typesetting it.

For custom functions, parameters, and research-area menus, see the
[Custom Python guide](docs/PYTHON_LIB.md) and
[extension author guide](docs/EXTENSIONS.md).
