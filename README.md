# Graph Builder

Graph Builder is a small, interactive graph editor built with Pygame and
NetworkX. It supports directed and undirected coloured graphs, selection,
copy/paste, curved edges, undo/redo, custom actions, GraphML persistence, and
TikZ export.

## Install

Graph Builder supports Python 3.10 or later. In a terminal, create and
activate a virtual environment, then install the project:

```sh
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -e .
```

## Run

Start a new editor session (the drawing is saved as `graph.graphml` in the
directory from which you run the command):

```sh
python graph_builder.py
```

To edit a particular GraphML file instead:

```sh
python graph_builder.py --graph path/to/drawing.graphml
```

You can also run the module directly with `python graph_builder.py`. The
`examples/` directory contains a sample graph and an example TikZ export.

The **Save TikZ** toolbar action asks where to save the file. It uses the macOS
native dialog on Mac and a native Tk dialog on Windows and Linux. If a dialog
cannot open, it writes a `.tex` file next to the selected GraphML file.

## Controls

- Left-click empty space: add a vertex.
- Left-click a vertex: select or drag it.
- Right-click and drag: add or remove an edge.
- Right-click and release on a vertex: delete it.
- Mouse wheel: zoom.
- `C`: cycle colour.
- `Ctrl/Cmd+C`, `Ctrl/Cmd+V`: copy and paste.
- `Ctrl/Cmd+Z`, `Shift+Ctrl/Cmd+Z`: undo and redo.
- `T`: cut edges from the selection to the remaining vertices.
- `Delete`, `Esc`, and Space: delete, deselect, and reset.

The example application in `graph_builder.py` also supplies transformations
such as twin, merge, full join, tensor product, and rotate. Add your own by
constructing `GraphAction`, `VertexAction`, or `ContextAction` values and
passing them to `graph_builder_lib.main`.

## Development

Run the non-interactive tests with:

```sh
python -m pytest
```

Only `networkx`, `numpy`, and `pygame` are runtime dependencies. TikZ export
produces source only; compiling it is optional and requires a local LaTeX
installation.
