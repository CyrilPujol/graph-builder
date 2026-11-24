"""Readers for the graph6 family defined by nauty's formats.txt.

NetworkX handles graph6 and sparse6. Digraph6 uses a row-major adjacency
matrix, including diagonal entries. Incremental sparse6 toggles edges of
the preceding graph. Files may contain more than one graph.
"""
from pathlib import Path

import networkx as nx
from networkx.readwrite.graph6 import data_to_n, n_to_data


COMPACT_SUFFIXES = {'.g6', '.graph6', '.s6', '.sparse6', '.d6', '.digraph6'}
MAX_VERTICES = 10000


def _order(payload):
    if not payload or any(c < 63 or c > 126 for c in payload):
        raise ValueError('Invalid graph6-family encoding.')
    needed = 1 if payload[0] != 126 else (8 if payload[1:2] == b'~' else 4)
    if len(payload) < needed:
        raise ValueError('Truncated graph order.')
    n, rest = data_to_n([c - 63 for c in payload])
    if n > MAX_VERTICES:
        raise ValueError(f'This graph has {n} vertices. The import limit is {MAX_VERTICES}.')
    return n, rest


def read_compact_graphs(path):
    """Read all graphs, retaining directedness, loops, and parallel edges."""
    graphs = []
    with Path(path).open('rb') as source:
        for number, line in enumerate(source, 1):
            line = line.strip()
            for header in (b'>>graph6<<', b'>>sparse6<<', b'>>digraph6<<'):
                if line.startswith(header):
                    line = line[len(header):]
                    break
            if not line:
                continue
            try:
                if line.startswith(b';'):
                    if not graphs or graphs[-1].is_directed() or graphs[-1].is_multigraph():
                        raise ValueError('Incremental sparse6 needs a preceding simple undirected graph.')
                    n = len(graphs[-1])
                    changes = nx.from_sparse6_bytes(b':' + bytes(v + 63 for v in n_to_data(n)) + line[1:])
                    graph = graphs[-1].copy()
                    for u, v in changes.edges():
                        if graph.has_edge(u, v):
                            graph.remove_edge(u, v)
                        else:
                            graph.add_edge(u, v)
                else:
                    marker = line[:1]
                    n, data = _order(line[1:] if marker in (b':', b'&') else line)
                    if marker == b'&':
                        if len(data) != (n * n + 5) // 6:
                            raise ValueError('Incorrect digraph6 adjacency matrix length.')
                        graph = nx.DiGraph()
                        graph.add_nodes_from(range(n))
                        for index in range(n * n):
                            if data[index // 6] & (1 << (5 - index % 6)):
                                graph.add_edge(index // n, index % n)
                    elif marker == b':':
                        graph = nx.from_sparse6_bytes(line)
                    else:
                        graph = nx.from_graph6_bytes(line)
                graphs.append(graph)
            except (ValueError, IndexError, nx.NetworkXException) as error:
                raise ValueError(f'Invalid compact graph on line {number}: {error}') from error
    if not graphs:
        raise ValueError('This file contains no graphs.')
    return graphs


def editor_graph(source, options):
    """Supply labels, styles and a bounded drawing to a compact graph."""
    from graph_builder_core.extensions import normalize_graph
    from graph_builder_core.model.document import empty_graph

    options = dict(options, graph_type='digraph' if source.is_directed() else 'graph',
                   multiedges=source.is_multigraph(), loops=bool(nx.number_of_selfloops(source)))
    initial = empty_graph(**options)
    # Deterministic and bounded, including disconnected and edgeless graphs.
    positions = nx.circular_layout(source, scale=max(100, min(600, 15 * len(source))))
    for node, point in positions.items():
        source.nodes[node].update(position=tuple(map(float, point)), label=str(node))
    graph, _ = normalize_graph(source, initial)
    return graph
