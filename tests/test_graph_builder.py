import networkx as nx
import pytest

from graph_builder import complement, contract, degree_summary, randomize, rotate, switch, twin
from graph_builder_lib import (
    _edge_curve_points, _set_edge_curve_points, convert_from_file, convert_position,
    empty_graph, set_edge_label, vertex_label,
)
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


def test_display_labels_are_independent_from_ids_and_are_exported_to_tikz():
    graph = empty_graph(graph_type='graph')
    graph.add_node('internal-a', position=(0, 0), col=0, label='x_1')
    graph.add_node('internal-b', position=(10, 0), col=1, label='x_1')
    graph.add_edge('internal-a', 'internal-b', col=0)
    graph.add_edge('internal-b', 'internal-a', col=0)
    set_edge_label(graph, 'internal-a', 'internal-b', 'e_1')

    tikz = graph_to_tikz(graph)

    assert vertex_label(graph, 'internal-a') == vertex_label(graph, 'internal-b') == 'x_1'
    assert graph.has_node('internal-a') and graph.has_node('internal-b')
    assert graph.edges['internal-a', 'internal-b']['label'] == 'e_1'
    assert graph.edges['internal-b', 'internal-a']['label'] == 'e_1'
    assert r'{x\_1}' in tikz
    assert r'{e\_1}' in tikz


def test_tikz_dialog_falls_back_when_no_dialog_is_available(tmp_path, monkeypatch):
    graph = empty_graph(graph_type='digraph')
    graph.add_node('a', position=(0, 0), col=0)
    monkeypatch.setattr(tikz_export.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(tikz_export, '_portable_save_path', lambda _: (_ for _ in ()).throw(RuntimeError))

    output = tikz_export.save_tikz_dialog(graph, tmp_path / 'fallback.tex')

    assert output == tmp_path / 'fallback.tex'
    assert output.exists()


def test_selection_transformations_preserve_undirected_editor_graphs():
    graph = nx.DiGraph(graph_type='graph', num_edge_colors=3, num_vertex_colors=4)
    for node, position in [('0', (0, 0)), ('1', (20, 0)), ('2', (40, 0))]:
        graph.add_node(node, position=position, col=1)
    graph.add_edge('0', '1', col=0)
    graph.add_edge('1', '0', col=0)

    twin(graph, {'0', '1'})
    assert graph.number_of_nodes() == 5
    assert graph.has_edge('3', '1') and graph.has_edge('4', '0')

    switch(graph, {'0'})
    assert graph.edges['0', '1']['col'] == graph.edges['1', '0']['col'] == 1
    switch(graph, {'0', '1'})
    assert graph.edges['0', '1']['col'] == graph.edges['1', '0']['col'] == 1

    complement(graph, {'0', '2'})
    assert graph.has_edge('0', '2') and graph.has_edge('2', '0')

    contracted = contract(graph, {'0', '1'})
    assert contracted.number_of_nodes() == 4
    assert 'Degree' in degree_summary(contracted)


def test_rotate_moves_edge_curve_points_with_the_graph():
    graph = empty_graph(graph_type='graph', num_edge_colors=2, num_vertex_colors=2)
    graph.add_node('0', position=(0, 0), col=0)
    graph.add_node('1', position=(10, 0), col=0)
    graph.add_edge('0', '1', col=0)
    graph.add_edge('1', '0', col=0)
    _set_edge_curve_points(graph, '0', '1', [(5, 2)])

    rotate(graph, {'0'}, 90)

    assert graph.nodes['1']['position'] == pytest.approx((0, 10))
    assert _edge_curve_points(graph, '0', '1')[0] == pytest.approx((-2, 5))


def test_randomize_replaces_only_induced_edges():
    graph = empty_graph(graph_type='graph', num_edge_colors=2, num_vertex_colors=2)
    for node in ('0', '1', '2'):
        graph.add_node(node, position=(0, 0), col=0)
    graph.add_edge('0', '2', col=1)
    graph.add_edge('2', '0', col=1)

    randomize(graph, {'0', '1'}, random_source=lambda: 0.25)

    assert graph.has_edge('0', '1') and graph.has_edge('1', '0')
    assert graph.has_edge('0', '2') and graph.has_edge('2', '0')
