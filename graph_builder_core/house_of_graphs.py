"""Open an exact graph6 search on House of Graphs."""
from __future__ import annotations

import base64
import json
import zlib

import networkx as nx


def search_url(graph):
    """Create House of Graphs' compressed graph6 search URL.

    House of Graphs accepts simple undirected graphs. Reject other types
    instead of silently checking a different underlying graph.
    """
    if graph.is_directed() or graph.is_multigraph() or nx.number_of_selfloops(graph):
        raise ValueError('House of Graphs requires a simple undirected graph without loops.')
    if graph.number_of_nodes() > 500:
        raise ValueError('House of Graphs search is limited to 500 vertices here.')
    simple = nx.convert_node_labels_to_integers(graph, ordering='default')
    graph6 = nx.to_graph6_bytes(simple, header=False).decode('ascii').strip()
    query = json.dumps({'v': 1, 'cf': graph6}, separators=(',', ':')).encode('utf-8')
    compressor = zlib.compressobj(level=9, wbits=-15)
    encoded = base64.urlsafe_b64encode(compressor.compress(query) + compressor.flush())
    return 'https://houseofgraphs.org/result-graphs?q=' + encoded.decode('ascii').rstrip('=')
