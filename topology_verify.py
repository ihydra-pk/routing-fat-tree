#!/usr/bin/env python3

import argparse
import sys
import topo
import networkx as nx
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches


def run_sanity_check(k):
    print(f"Running sanity check for k={k}...")

    ft = topo.Fattree(k)

    # Expected counts based on fat-tree formulas
    expected_hosts    = (k ** 3) // 4
    expected_core     = (k // 2) ** 2
    expected_agg      = k * (k // 2)
    expected_edge     = k * (k // 2)
    expected_switches = expected_core + expected_agg + expected_edge
    expected_links    = 3 * (k ** 3) // 4

    assert len(ft.servers)  == expected_hosts
    assert len(ft.switches) == expected_switches

    core_count = sum(1 for s in ft.switches if "core"        in s.type)
    agg_count  = sum(1 for s in ft.switches if "aggregation" in s.type)
    edge_count = sum(1 for s in ft.switches if "edge"        in s.type)

    assert core_count == expected_core
    assert agg_count  == expected_agg
    assert edge_count == expected_edge
    print(f"Verified Switches: {expected_switches}, Hosts: {expected_hosts}")

    # Degree checks
    for host in ft.servers:
        assert len(host.edges) == 1
    for switch in ft.switches:
        assert len(switch.edges) == k
    print(f"Verified Degrees: hosts=1, switches={k}")

    # count unique links across all nodes
    unique_links = set()
    for node in ft.servers + ft.switches:
        for edge in node.edges:
            unique_links.add(tuple(sorted([edge.lnode.id, edge.rnode.id])))

    assert len(unique_links) == expected_links
    print(f"Verified Links: {expected_links} unique undirected links")
    print(f"Sanity check passed for k={k}.\n")


def plot_topology(k):
    print(f"Plotting topology for k={k}...")

    ft = topo.Fattree(k)
    G  = nx.Graph()

    # sort nodes for consistent layout
    sorted_core  = sorted([s for s in ft.switches if "core"        in s.type], key=lambda s: s.id)
    sorted_agg   = sorted([s for s in ft.switches if "aggregation" in s.type], key=lambda s: s.id)
    sorted_edge  = sorted([s for s in ft.switches if "edge"        in s.type], key=lambda s: s.id)
    sorted_hosts = sorted(ft.servers, key=lambda h: int(h.id[1:]))

    for s in sorted_core:  G.add_node(s.id, color='red')
    for s in sorted_agg:   G.add_node(s.id, color='orange')
    for s in sorted_edge:  G.add_node(s.id, color='blue')
    for h in sorted_hosts: G.add_node(h.id, color='green')

    # Add edges
    for node in ft.switches + ft.servers:
        for edge in node.edges:
            G.add_edge(edge.lnode.id, edge.rnode.id)

    # assign (x, y) positions per layer
    pos    = {}
    half_k = k // 2

    for i, h in enumerate(sorted_hosts):
        pod = i // (half_k ** 2)
        pos[h.id] = (i + pod * 0.8, 0)

    for i, s in enumerate(sorted_edge):
        pod        = i // half_k
        start_x    = pod * (half_k ** 2) + pod * 0.8
        center_x   = (start_x + start_x + (half_k ** 2) - 1) / 2
        idx_in_pod = i % half_k
        pos[s.id]  = (center_x + (idx_in_pod - (half_k - 1) / 2) * 1.0, 1)

    for i, s in enumerate(sorted_agg):
        pod        = i // half_k
        start_x    = pod * (half_k ** 2) + pod * 0.8
        center_x   = (start_x + start_x + (half_k ** 2) - 1) / 2
        idx_in_pod = i % half_k
        pos[s.id]  = (center_x + (idx_in_pod - (half_k - 1) / 2) * 1.0, 2)

    total_width  = (k - 1) * (half_k ** 2) + (k - 1) * 0.8 + (half_k ** 2) - 1
    graph_center = total_width / 2
    for i, s in enumerate(sorted_core):
        pos[s.id] = (graph_center + (i - (len(sorted_core) - 1) / 2) * 1.5, 3)

    colors = [data['color'] for _, data in G.nodes(data=True)]

    # Draw the graph
    plt.figure(figsize=(12, 10))
    nx.draw(G, pos, with_labels=False, node_color=colors, node_size=100, edge_color="gray", width=0.5)
    plt.legend(handles=[
        mpatches.Patch(color='red',    label='Core'),
        mpatches.Patch(color='orange', label='Aggregation'),
        mpatches.Patch(color='blue',   label='Edge'),
        mpatches.Patch(color='green',  label='Hosts'),
    ], loc='upper right')
    plt.title(f"Fat-Tree Topology (k={k})")

    # Save the image
    filename = f"fat_tree_k{k}_plot.png"
    plt.savefig(filename, dpi=300)
    print(f"Saved as '{filename}'.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('-k', type=int, default=4)
    parser.add_argument('--sanity-check', action='store_true')
    parser.add_argument('--plot', action='store_true')
    args = parser.parse_args()

    # If no specific action is given, just show help
    if not args.sanity_check and not args.plot:
        parser.print_help()
        sys.exit(0)

    if args.sanity_check:
        run_sanity_check(args.k)
    if args.plot:
        plot_topology(args.k)