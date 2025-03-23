#!/usr/bin/env python3
"""
arxml_hierarchy_bfs_detailed.py

Parse an AUTOSAR ARXML file and build a directed graph of *all* elements,
including data types, compu methods, application errors, I-Signals, I-PDUs,
code descriptors, resource consumption, vendor IDs, etc.

We also create separate nodes for references (e.g., <TYPE-TREF>) so that
you can see them in the final diagram.

Finally, we perform a BFS-based layout (top-down) for clarity.

Installs needed:
    pip install networkx matplotlib

Usage:
    python arxml_hierarchy_bfs_detailed.py
    Enter path to ARXML file at the prompt.

Outputs:
    arxml_hierarchy.png
"""

import sys
import xml.etree.ElementTree as ET
import networkx as nx
import matplotlib.pyplot as plt
from collections import deque, defaultdict

def make_node_id(parent_id, tag, short_name):
    """
    Create a unique string to identify this node in the graph.
    We combine parent_id + tag + short_name to avoid collisions
    when short_name is reused in multiple contexts.
    """
    if short_name:
        return f"{parent_id}/{tag}:{short_name}"
    else:
        return f"{parent_id}/{tag}"

def build_detailed_graph(element, graph, parent_id="", visited=None):
    """
    Recursively parse *all* child elements to build a directed graph
    that includes data types, compu methods, application errors,
    signals, PDU definitions, code descriptors, resource usage, etc.

    We also create separate nodes for references (*-REF).
    """
    if visited is None:
        visited = set()

    tag = element.tag.split('}')[-1]
    short_name_elem = element.find("./{*}SHORT-NAME")
    short_name = short_name_elem.text if short_name_elem is not None else None

    # If there's no parent, this is the top-level
    # For the top-level, set parent_id = "ROOT" or something similar
    if not parent_id:
        parent_id = "ROOT"

    # Create a unique ID for this element in the graph
    node_id = make_node_id(parent_id, tag, short_name)

    # If we already visited this exact node path, skip to avoid cycles
    if node_id in visited:
        return
    visited.add(node_id)

    # Build a more readable label for the node
    if short_name:
        label = f"{tag}: {short_name}"
    else:
        label = tag  # fallback if there's no SHORT-NAME

    # Add the node to the graph (store label as a node attribute)
    graph.add_node(node_id, label=label)

    # Add an edge from parent -> this node (except if parent is "ROOT" with no real node_id)
    if parent_id != "ROOT":
        graph.add_edge(parent_id, node_id)

    # --- Create separate nodes for references ---
    # e.g. <TYPE-TREF DEST="IMPLEMENTATION-DATA-TYPE">/Some/Path</TYPE-TREF>
    # This helps you see reference usage in the diagram.
    for ref in element.findall(".//{*}*-REF"):
        ref_text = ref.text.strip() if ref.text else "(empty-ref)"
        ref_tag = ref.tag.split('}')[-1]  # e.g. TYPE-TREF, PROVIDED-INTERFACE-TREF, etc.
        ref_node_id = make_node_id(node_id, ref_tag, ref_text)
        if ref_node_id not in visited:
            visited.add(ref_node_id)
            graph.add_node(ref_node_id, label=f"{ref_tag} => {ref_text}")
            graph.add_edge(node_id, ref_node_id)

    # Now recurse into all direct children (not searching subchildren with .//, but immediate)
    for child in element:
        # Skip if it's a reference node (already handled above).
        # We want to parse everything else though.
        child_tag = child.tag.split('}')[-1]
        if child_tag.endswith("-REF"):
            continue

        build_detailed_graph(child, graph, parent_id=node_id, visited=visited)

def bfs_hierarchy_positions(G, level_gap=1.5, base_sibling_gap=2.0):
    """
    Create a BFS-based top-down layout for the graph.

    Each BFS level is one 'row', siblings are spaced horizontally by base_sibling_gap.
    """
    # 1) Find roots (in_degree=0). If none, pick the first node as root.
    roots = [n for n in G.nodes if G.in_degree(n) == 0]
    if not roots:
        roots = [list(G.nodes)[0]]

    queue = deque()
    for r in roots:
        queue.append((r, 0))

    visited = set()
    level_map = defaultdict(list)

    while queue:
        node, depth = queue.popleft()
        if node in visited:
            continue
        visited.add(node)

        level_map[depth].append(node)

        for child in G.successors(node):
            if child not in visited:
                queue.append((child, depth+1))

    # 2) Horizontal spacing based on max label length
    max_label_length = 1
    for n in G.nodes:
        lbl = G.nodes[n].get("label", n)
        if len(lbl) > max_label_length:
            max_label_length = len(lbl)

    # each character ~0.2 units of space
    sibling_gap = base_sibling_gap + 0.2*max_label_length

    pos = {}
    max_depth = max(level_map.keys()) if level_map else 0

    for depth in range(max_depth+1):
        nodes_at_level = level_map[depth]
        count = len(nodes_at_level)
        if count == 0:
            continue

        total_width = (count-1)*sibling_gap
        leftmost = -total_width/2.0

        for i, node in enumerate(nodes_at_level):
            x = leftmost + i*sibling_gap
            y = -(depth*level_gap)
            pos[node] = (x, y)

    return pos

def main():
    arxml_file = input("Enter path to ARXML file: ").strip()
    if not arxml_file:
        print("[ERROR] No ARXML file provided.")
        sys.exit(1)

    # parse
    try:
        tree = ET.parse(arxml_file)
        root = tree.getroot()
    except Exception as e:
        print(f"[ERROR] Could not parse ARXML: {e}")
        sys.exit(1)

    # Build graph
    G = nx.DiGraph()

    # If the top-level is <AUTOSAR>, we might have <AR-PACKAGES> as children
    # but let's just pass 'root' to the function so it picks up everything
    build_detailed_graph(root, G)

    # BFS Layout
    pos = bfs_hierarchy_positions(G, level_gap=2.0, base_sibling_gap=2.0)

    # Dynamically size figure
    ys = set(p[1] for p in pos.values())
    level_count = len(ys) or 1
    siblings_per_level = defaultdict(int)
    for (x, y) in pos.values():
        siblings_per_level[y] += 1
    max_siblings = max(siblings_per_level.values()) if siblings_per_level else 1

    fig_width = max(12, max_siblings * 2.2)
    fig_height = max(8, level_count * 1.8)

    plt.figure(figsize=(fig_width, fig_height))

    # Draw with custom node labels from the "label" attribute
    labels = {n: G.nodes[n].get("label", n) for n in G.nodes}
    nx.draw(
        G, pos,
        labels=labels,
        with_labels=True,
        node_size=1500,
        node_color="skyblue",
        arrows=False,
        font_size=8
    )

    plt.title("ARXML Detailed Hierarchy (Including Data Types, Errors, Signals, etc.)")
    plt.axis("off")
    out_name = "arxml_hierarchy.png"
    plt.savefig(out_name, dpi=150)
    print(f"Diagram saved as {out_name}")
    plt.show()

if __name__ == "__main__":
    main()
