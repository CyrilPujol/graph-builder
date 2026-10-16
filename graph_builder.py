"""Example graph-editor application with a few graph transformations."""

from __future__ import annotations

import argparse

import networkx as nx
import numpy as np

from graph_builder_lib import (
    ContextAction,
    GraphAction,
    VertexAction,
    dist,
    main,
    unused_label,
)

def twin(graph,vertex):
    #make a twin of the selected vertex
    if vertex is None:
        return graph
    new_node = unused_label(graph)
    graph.add_node(new_node)
    graph.nodes[new_node]['position'] = (graph.nodes[vertex]['position'][0]+20,graph.nodes[vertex]['position'][1]+20)
    graph.nodes[new_node]['col'] = graph.nodes[vertex]['col']
    for u,v in graph.edges(vertex):
        attrs = graph.edges[u,v]
        graph.add_edge(new_node,v,**attrs)
        if graph.graph['graph_type'] == 'graph':
            graph.add_edge(v,new_node,**attrs)
    return graph

def merge(graph,vertex,box):
    ### merge all vertices that touch the selected vertex (distance smaller than vertex_radius).
    if vertex is None:
        return graph
    pos_v = graph.nodes[vertex]['position']
    to_merge = []
    for u in graph.nodes:
        if u != vertex:
            pos_u = graph.nodes[u]['position']
            if dist(pos_v,pos_u) < box.vertex_radius:
                to_merge.append(u)
    for u in to_merge:
        for _,v in graph.edges(u):
            if v != vertex:
                attrs = graph.edges[u,v]
                graph.add_edge(vertex,v,**attrs)
                if graph.graph['graph_type'] == 'graph':
                    graph.add_edge(v,vertex,**attrs)
        graph.remove_node(u)
    return graph

def full_join(graph):
    ### create the full join of all connected components of the graph
    components = list(nx.weakly_connected_components(graph))
    for i in range(len(components)):
        for j in range(i+1,len(components)):
            for u in components[i]:
                for v in components[j]:
                    attrs = {'col' : 0}
                    graph.add_edge(u,v,**attrs)
                    if graph.graph['graph_type'] == 'graph':
                        graph.add_edge(v,u,**attrs)

def snap_grid(graph):
    k = 30
    for u in graph.nodes:
        (x,y) = graph.nodes[u]['position']
        graph.nodes[u]['position'] = int(x/k+.5)*k,int(y/k+.5)*k
    return graph

def tensor_product(graph):
    if nx.number_weakly_connected_components(graph) >= 2:
        VG, VH = list(nx.weakly_connected_components(graph))[:2]
        G, H = graph.subgraph(VG), graph.subgraph(VH)
        K = nx.tensor_product(G, H)
        for (u, v) in K.nodes:
            pos = (G.nodes[u]['position'][0], H.nodes[v]['position'][1])
            K.nodes[(u, v)]['position'] = pos
            for key in G.nodes[u].keys():
                if key != 'position':
                    K.nodes[(u, v)][key] = G.nodes[u][key]
                    #print(f"K.nodes[(u, v)][key] : {K.nodes[(u, v)][key]}")
        for e in K.edges():
            ((u,v),(u_,v_)) = e
            for key,value in G.edges[u,u_].items():
                K.edges[e][key] = value
        graph = nx.disjoint_union_all([G, H, K])
        graph = nx.convert_node_labels_to_integers(graph)
        graph = nx.relabel_nodes(graph, lambda x: str(x))
        return graph
    else:
        print("Not the right number of CC")
        return graph

def switch(graph,vertex):
    if vertex is None:
        return graph
    
    for edge in graph.edges(vertex):
        (u,v) = edge #normally u == vertex
        graph.edges[edge]['col'] = (graph.edges[edge]['col']+1)%graph.graph['num_edge_colors']
        graph.edges[v,u]['col'] = (graph.edges[v,u]['col']+1)%graph.graph['num_edge_colors'] # must switch also the reverse arc
    return graph


def degree(graph):
    degrees = dict(nx.degree(graph))
    l_deg = [ x//2 for (k,x) in degrees.items()]
    print( f"min deg, avg deg, max deg = ,{min(l_deg), np.mean(l_deg), max(l_deg)}")
    print( f"n ={len(graph.nodes)} e ={len(graph.edges)}")
    return graph

def midpos(pos1,pos2):
    x,y = pos1
    x_,y_ = pos2
    return ((x+x_)/2,(y+y_)/2 )

def subdivide(graph,vertex):
    # If vertex is not None, subdivide all edges incident to vertex
    # Otherwise subdivide all edges
    
    new_graph = graph.copy()
    edges_to_add = []
    edges_to_remove = []
    new_nodes = {}
    
    for u, v, attrs in graph.edges(data=True):
        if vertex is not None and (u != vertex and v != vertex):
            continue
        if (u,v) in edges_to_remove :
            continue
        new_node = unused_label(new_graph)
        new_graph.add_node(new_node)
        new_nodes[new_node] = (u, v)
        if graph.graph["graph_type"] == "graph":
            edges_to_remove+=[(u, v),(v,u)]
        else:
            edges_to_remove.append((u, v))
        
        # Save edges to add later
        edges_to_add.append((u, new_node, attrs))
        edges_to_add.append((new_node, v, attrs))
    
    # Remove old edges
    new_graph.remove_edges_from(edges_to_remove)
    
    # Add new nodes and edges
    for new_node, (u, v) in new_nodes.items():
        new_graph.nodes[new_node]['position'] = midpos(new_graph.nodes[u]['position'],new_graph.nodes[v]['position'])
        new_graph.nodes[new_node]['col'] = new_graph.nodes[u]['col']
    for u, v, attrs in edges_to_add:
        new_graph.add_edge(u, v, **attrs)
    
    return new_graph

def rotate(graph,vertex):
    # rotate the graph around the selected vertex by 10 degrees
    if vertex is None:
        return graph
    # Implementation for rotating the graph around the selected vertex by 10 degrees
    angle = np.radians(10)
    cos_angle = np.cos(angle)
    sin_angle = np.sin(angle)
    pos_v = graph.nodes[vertex]['position']
    for u in graph.nodes:       
        if u != vertex:
            pos_u = graph.nodes[u]['position']
            # Translate to origin
            translated_x = pos_u[0] - pos_v[0]
            translated_y = pos_u[1] - pos_v[1]
            # Rotate
            rotated_x = translated_x * cos_angle - translated_y * sin_angle
            rotated_y = translated_x * sin_angle + translated_y * cos_angle
            # Translate back
            new_pos = (rotated_x + pos_v[0], rotated_y + pos_v[1])
            graph.nodes[u]['position'] = new_pos
    return graph

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Interactive graph editor')
    parser.add_argument(
        '--graph',
        metavar='FILE',
        help='GraphML file to open and save (default: graph.graphml in the current directory)',
    )
    args = parser.parse_args()

    actions = [
        GraphAction(degree, 'd'),
        VertexAction(twin, 'w'),
        VertexAction(switch, 's'),
        ContextAction(
            lambda context: merge(
                context.graph, context.selection.single_node(), context.box
            ),
            'm',
            available=lambda context: context.selection.single_node() is not None,
            name='merge',
        ),
        GraphAction(full_join, 'j'),
        GraphAction(tensor_product, 'p'),
        VertexAction(rotate, 'r'),
    ]
    main(
        actions=actions,
        graph_file=args.graph,
        graph_type='graph',
        num_edge_colors=2,
        num_vertex_colors=4,
    )
