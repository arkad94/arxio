import os
import uuid
import json
import networkx as nx
import plotly.graph_objects as go
from parser import parse_arxml_to_broader_composition_graph

def generate_3d_diagram_html(xml_file_path):
    """
    Generate an interactive 3D diagram HTML string from an ARXML file.
    """
    G = parse_arxml_to_broader_composition_graph(xml_file_path)
    pos = nx.spring_layout(G, dim=3, k=5.0, seed=42)
    
    node_list = list(G.nodes())
    x_nodes, y_nodes, z_nodes = [], [], []
    node_text, node_colors, node_customdata = [], [], []
    node_types = nx.get_node_attributes(G, "type")
    base_size = 30
    highlight_size = 50

    for node in node_list:
        x, y, z = pos[node]
        x_nodes.append(x)
        y_nodes.append(y)
        z_nodes.append(z)
        label = G.nodes[node].get("label", node)
        node_text.append(label)
        ntype = node_types.get(node, "Unknown")
        node_colors.append({
            "SWC": "skyblue",
            "Service": "lightgreen",
            "Interface": "orange",
            "Composition": "purple",
            "Port": "white",
            "Runnable": "#ffd1dc",
            "Event": "#ffebcc"
        }.get(ntype, "lightgray"))
        neighbors = set(G.neighbors(node)) | set(G.predecessors(node))
        neighbor_indices = [node_list.index(n) for n in neighbors if n in node_list]
        node_customdata.append(neighbor_indices)

    edge_indices = []
    for u, v, d in G.edges(data=True):
        try:
            i_u = node_list.index(u)
            i_v = node_list.index(v)
            edge_indices.append([i_u, i_v])
        except ValueError:
            continue

    edge_x, edge_y, edge_z = [], [], []
    for u, v, d in G.edges(data=True):
        x0, y0, z0 = pos[u]
        x1, y1, z1 = pos[v]
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])
        edge_z.extend([z0, z1, None])

    edge_trace = go.Scatter3d(
        x=edge_x, y=edge_y, z=edge_z,
        line=dict(width=2, color='rgba(0,0,0,0.2)'),
        mode='lines',
        hoverinfo='none'
    )

    highlight_edge_trace = go.Scatter3d(
        x=[], y=[], z=[],
        mode='lines',
        line=dict(width=4, color='red'),
        hoverinfo='none'
    )

    node_trace = go.Scatter3d(
        x=x_nodes, y=y_nodes, z=z_nodes,
        mode='markers+text',
        marker=dict(
            size=[base_size]*len(x_nodes),
            color=node_colors,
            opacity=0.8
        ),
        text=node_text,
        hoverinfo='text',
        customdata=node_customdata
    )

    legend_annotations = [
        dict(
            x=0.02,
            y=0.98,
            xref="paper",
            yref="paper",
            text="""
            <b>Legend:</b><br>
            SWC: skyblue<br>
            Service: lightgreen<br>
            Interface: orange<br>
            Composition: purple<br>
            Port: white<br>
            Runnable: pink (#ffd1dc)<br>
            Event: light orange (#ffebcc)
            """,
            showarrow=False,
            bordercolor="black",
            borderwidth=1,
            bgcolor="white",
            opacity=0.8
        )
    ]

    fig = go.Figure(data=[edge_trace, node_trace, highlight_edge_trace],
                    layout=go.Layout(
                        title='Interactive 3D Diagram',
                        showlegend=False,
                        dragmode='orbit',
                        scene=dict(
                            xaxis=dict(showgrid=False, zeroline=False),
                            yaxis=dict(showgrid=False, zeroline=False),
                            zaxis=dict(showgrid=False, zeroline=False)
                        ),
                        margin=dict(b=20, l=5, r=5, t=40),
                        annotations=legend_annotations,
                        hovermode='closest'
                    ))

    custom_js = f"""
<script>
const myPlot = document.getElementById('plot3d');
const edgeIndices = {json.dumps(edge_indices)};
let animationFrameRequested = false;
let lastHighlight = new Set();

myPlot.on('plotly_hover', function (data) {{
    if (!data.points || data.points.length === 0) return;

    const pointNumber = data.points[0].pointNumber;
    const neighborIndices = data.points[0].data.customdata[pointNumber];
    const highlighted = new Set([pointNumber, ...neighborIndices]);

    if (JSON.stringify([...highlighted]) === JSON.stringify([...lastHighlight])) return;

    lastHighlight = highlighted;

    if (!animationFrameRequested) {{
        animationFrameRequested = true;
        requestAnimationFrame(() => {{
            updateHighlight(highlighted);
            animationFrameRequested = false;
        }});
    }}
}});

function updateHighlight(highlighted) {{
    const totalPoints = myPlot.data[1].x.length;
    const newSizes = new Array(totalPoints).fill(30);
    const newOpacities = new Array(totalPoints).fill(0.2);

    highlighted.forEach(idx => {{
        newSizes[idx] = 50;
        newOpacities[idx] = 1.0;
    }});

    Plotly.restyle(myPlot, {{
        'marker.size': [newSizes],
        'marker.opacity': [newOpacities]
    }}, [1]);
}}
</script>
    """

    fig_html = fig.to_html(full_html=True, include_plotlyjs='cdn', div_id='plot3d')
    html_str = fig_html + custom_js
    return html_str