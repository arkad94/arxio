import json
import matplotlib.pyplot as plt
import networkx as nx

# Load data from JSON files
def load_json(file_path):
    try:
        with open(file_path) as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[ERROR] File not found: {file_path}")
        exit(1)

# Prompt user for file paths
structure_file = input("Enter path to parsed_structure.json: ").strip()
element_file = input("Enter path to elements.json: ").strip()

structure = load_json(structure_file)
element_dict = load_json(element_file)["elements"]

# Initialize graph
graph = nx.DiGraph()

def build_graph(node, parent=None):
    for key, value in node.items():
        graph.add_node(key)
        if parent:
            graph.add_edge(parent, key)
        
        if "children" in value:
            build_graph(value["children"], key)

# Build the graph from parsed structure
build_graph(structure["AUTOSAR"]["children"])

# Visual elements for nodes
def get_node_style(node):
    element_type = node.split('-')[0]  # Extract key type
    if element_type in element_dict:
        return element_dict[element_type]["visual"], element_dict[element_type]["color"]
    return "Hexagon", "#808080"  # Default unknown element

# Node positions and styling
pos = nx.spring_layout(graph)
node_colors = []
node_shapes = {}

for node in graph.nodes():
    shape, color = get_node_style(node)
    node_colors.append(color)
    node_shapes[shape] = node_shapes.get(shape, []) + [node]

# Draw the graph
plt.figure(figsize=(12, 8))

# Draw each node shape separately for better visualization
for shape, nodes in node_shapes.items():
    nx.draw_networkx_nodes(graph, pos, nodelist=nodes, node_color=node_colors, node_shape='o' if shape == 'Circle' else 's')

nx.draw_networkx_edges(graph, pos)
nx.draw_networkx_labels(graph, pos, font_size=8)

plt.title("AUTOSAR Block Diagram")
plt.axis("off")
plt.savefig("arxml_block_diagram.png")
plt.show()
