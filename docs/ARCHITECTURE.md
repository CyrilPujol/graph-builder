# Code organization

`graph_builder.py` is the public Python interface. Keep user scripts and personal
functions outside the library. `scripts/app_main.py` starts the downloadable app.

`graph_builder_core` groups code by responsibility:

| Location | Responsibility |
| --- | --- |
| `api.py` | `main()` and `edit_graph()`, with Qt imported only when needed |
| `actions.py` | Command definitions and built-in actions |
| `extensions.py` | User-defined buttons and conversion of external NetworkX graphs |
| `model/` | Document defaults, edges, regions, styles, selection and graph edits |
| `geometry/` | Curves, guides, layouts and polygon offsets |
| `algorithms/` | Generators, products, graph measures and solver models |
| `io/` | GraphML, compact graph formats, TikZ, pictures and graph lookup |
| `ui/` | Qt presentation and interactions |

Within `ui/`, `items.py` draws graph objects, `scene.py` handles object gestures
and overlays, and `view.py` handles pan, zoom and area selection. `window.py`
owns the document, selection and shared UI state. The files in `controllers/`
group its methods for menus, documents, appearance, regions, metrics and
operations that use two selections. They share one history. `workers.py`
provides the common process setup for background computations.

Place reusable graph behavior below the UI layer. For example, the canvas and
TikZ export use the same curve and polygon geometry. Group related code while
it has one responsibility, then split at a clear dependency boundary.

Import from the owning module inside the implementation. Application and
library users should import `graph_builder`. Internal paths may change.

Local regression tests live in the Git-ignored `local/tests/` directory. Run
them with `QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s local/tests -q`.
Builds include all `graph_builder_core` subpackages and exclude `local/`.
