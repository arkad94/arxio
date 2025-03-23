import os
import uuid
import networkx as nx
import matplotlib
matplotlib.use("Agg")  # Forces non-GUI backend
import matplotlib.pyplot as plt

from parser import parse_arxml_to_broader_composition_graph

def generate_2d_diagram(xml_file_path, diagram_folder):
    """
    Generate a 2D composition diagram from an ARXML file.
    """
    # Parse the ARXML file to build the graph.
    G = parse_arxml_to_broader_composition_graph(xml_file_path)
    
    try:
        pos = nx.nx_agraph.graphviz_layout(G, prog="dot")
    except Exception as e:
        pos = nx.spring_layout(G, k=5.0, iterations=200, seed=42)
    
    plt.figure(figsize=(16, 12))
    plt.axis('off')
    labels = nx.get_node_attributes(G, "label")
    node_types = nx.get_node_attributes(G, "type")
    node_colors = []
    for node in G.nodes():
        ntype = node_types.get(node, "Unknown")
        if ntype == "SWC":
            node_colors.append("skyblue")
        elif ntype == "Service":
            node_colors.append("lightgreen")
        elif ntype == "Interface":
            node_colors.append("orange")
        elif ntype == "Composition":
            node_colors.append("purple")
        elif ntype == "Port":
            node_colors.append("white")
        elif ntype == "Runnable":
            node_colors.append("#ffd1dc")
        elif ntype == "Event":
            node_colors.append("#ffebcc")
        else:
            node_colors.append("lightgray")
    nx.draw_networkx_nodes(G, pos, node_size=2500, node_color=node_colors)
    nx.draw_networkx_labels(G, pos, labels=labels, font_size=10, font_weight='bold')
    nx.draw_networkx_edges(G, pos, arrows=True, arrowstyle="-|>", arrowsize=12)
    edge_labels = {(u, v): d["relation"] for u, v, d in G.edges(data=True) if "relation" in d}
    nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_size=9)
    plt.tight_layout()
    plt.margins(0.2)
    
    diagram_filename = str(uuid.uuid4()) + ".png"
    diagram_path = os.path.join(diagram_folder, diagram_filename)
    os.makedirs(diagram_folder, exist_ok=True)
    plt.savefig(diagram_path, dpi=150, bbox_inches='tight')
    plt.close()
    return diagram_filename
