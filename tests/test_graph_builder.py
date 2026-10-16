import networkx as nx

from graph_builder_lib import convert_from_file, convert_position, empty_graph
import tikz_export
from tikz_export import graph_to_tikz, write_tikz


def test_graphml_round_trip_preserves_positions_and_colours(tmp_path):
    graph = empty_graph(graph_type='graph', num_edge_colors=3, num_vertex_colors=4)
    graph.add_node('a', position=(1.5, 2.5), col=2)
    graph.add_node('b', position=(3.0, 4.0), col=1)
    graph.add_edge('a', 'b', col=2)
    graph.add_edge('b', 'a', col=2)

    path = tmp_path / 'drawing.graphml'
    nx.write_graphml(convert_position(graph), path)
    loaded = convert_from_file(path, dict(graph.graph))

    assert loaded.nodes['a']['position'] == (1.5, 2.5)
    assert loaded.nodes['a']['col'] == 2
    assert loaded.edges['a', 'b']['col'] == 2


def test_tikz_export_writes_a_portable_file(tmp_path):
    graph = empty_graph(graph_type='digraph')
    graph.add_node('a', position=(0, 0), col=0)
    graph.add_node('b', position=(10, 10), col=1)
    graph.add_edge('a', 'b', col=2)

    tikz = graph_to_tikz(graph)
    output = write_tikz(graph, tmp_path / 'nested' / 'drawing.tex')

    assert r'\begin{tikzpicture}' in tikz
    assert '->' in tikz
    assert output.read_text(encoding='utf-8') == tikz


def test_tikz_dialog_falls_back_when_no_dialog_is_available(tmp_path, monkeypatch):
    graph = empty_graph(graph_type='digraph')
    graph.add_node('a', position=(0, 0), col=0)
    monkeypatch.setattr(tikz_export.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(tikz_export, '_portable_save_path', lambda _: (_ for _ in ()).throw(RuntimeError))

    output = tikz_export.save_tikz_dialog(graph, tmp_path / 'fallback.tex')

    assert output == tmp_path / 'fallback.tex'
    assert output.exists()
