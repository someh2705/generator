import networkx as nx
import numpy as np
import math
import itertools
import random
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from dataclasses import dataclass
from typing import Tuple


@dataclass
class PhysicsConfig:
    speed_of_light_fiber: float = 200.0
    router_overhead_ms: int = 1

    bw_backbone: int = 10000
    bw_transit: int = 1000
    bw_access: int = 100


@dataclass
class StructureConfig:
    num_tier1: int = 4

    radius_tier1_global: float = 8000.0
    radius_tier1_local: float = 1500.0
    radius_tier2_local: float = 300.0

    tier1_nodes: Tuple[int, int] = (25, 35)
    tier2_nodes: Tuple[int, int] = (30, 100)
    sub_regions_range: Tuple[int, int] = (3, 5)
    tier2_per_region_range: Tuple[int, int] = (3, 5)

    core_router_percentile: int = 8
    relay_probability: float = 0.3
    ixp_connection_count: int = 2

    transit_candidate_pool_size: int = 5


@dataclass
class VisualConfig:
    compression_global: float = 0.0005
    compression_local: float = 0.002
    edge_transparency: float = 0.25


PHYSICS = PhysicsConfig()
STRUCT = StructureConfig()
VISUAL = VisualConfig()


def get_geo_dist(pos1, pos2):
    return math.sqrt((pos1[0] - pos2[0]) ** 2 + (pos1[1] - pos2[1]) ** 2)


def calculate_latency(pos1, pos2, base_overhead: int = 0) -> int:
    dist_km = get_geo_dist(pos1, pos2)
    prop_delay = dist_km / PHYSICS.speed_of_light_fiber
    jitter = random.uniform(0.9, 1.1)
    total_latency = int(prop_delay * jitter) + PHYSICS.router_overhead_ms + base_overhead
    return max(1, total_latency)


def calculate_centrality_roles(G):
    if len(G) == 0:
        return

    centrality = nx.betweenness_centrality(G, k=None)
    sorted_nodes = sorted(centrality.items(), key=lambda item: item[1], reverse=True)

    cutoff_index = max(int(len(G) * (STRUCT.core_router_percentile / 100)), 3)
    core_routers = [node for node, score in sorted_nodes[:cutoff_index]]

    for n in G.nodes():
        if n in core_routers:
            G.nodes[n]["node_role"] = "core_router"
        else:
            G.nodes[n]["node_role"] = "edge_node"


def create_tier1_isp(as_id, global_center_pos):
    num_nodes = random.randint(*STRUCT.tier1_nodes)
    G = nx.waxman_graph(n=num_nodes, alpha=0.4, beta=0.2)

    raw_pos = nx.get_node_attributes(G, "pos")
    km_pos = {}
    for n, p in raw_pos.items():
        x = (p[0] - 0.5) * 2 * STRUCT.radius_tier1_local + global_center_pos[0]
        y = (p[1] - 0.5) * 2 * STRUCT.radius_tier1_local + global_center_pos[1]
        km_pos[n] = (x, y)
    nx.set_node_attributes(G, km_pos, "pos")

    if not nx.is_connected(G):
        components = sorted(nx.connected_components(G), key=len, reverse=True)
        main = list(components[0])
        for cc in components[1:]:
            iso = list(cc)[0]
            target = min(main, key=lambda x: get_geo_dist(km_pos[iso], km_pos[x]))
            G.add_edge(iso, target, type="internal")

    nodes = sorted(G.degree, key=lambda x: x[1], reverse=True)
    top = [n for n, d in nodes[: max(2, int(len(G) * 0.08))]]
    for i in range(len(top)):
        u, v = top[i], top[(i + 1) % len(top)]
        if not G.has_edge(u, v):
            G.add_edge(u, v, type="internal")

    mapping = {n: f"{as_id}_{n}" for n in G.nodes()}
    G = nx.relabel_nodes(G, mapping)
    nx.set_node_attributes(G, "tier1", "layer")
    nx.set_node_attributes(G, as_id, "asn")

    pos = nx.get_node_attributes(G, "pos")
    for u, v in G.edges():
        lat = calculate_latency(pos[u], pos[v], base_overhead=2)
        G.edges[u, v].update({"type": "internal", "latency": lat, "bandwidth": PHYSICS.bw_backbone})

    return G


def create_tier2_isp(as_id, sub_region_id, region_center_pos):
    num_nodes = random.randint(*STRUCT.tier2_nodes)
    G = nx.powerlaw_cluster_graph(n=num_nodes, m=2, p=0.4)

    raw_pos = nx.spring_layout(G)
    km_pos = {}
    for n, p in raw_pos.items():
        x = p[0] * STRUCT.radius_tier2_local + region_center_pos[0]
        y = p[1] * STRUCT.radius_tier2_local + region_center_pos[1]
        km_pos[n] = (x, y)
    nx.set_node_attributes(G, km_pos, "pos")

    mapping = {n: f"{as_id}_{n}" for n in G.nodes()}
    G = nx.relabel_nodes(G, mapping)

    nx.set_node_attributes(G, "tier2", "layer")
    nx.set_node_attributes(G, as_id, "asn")
    nx.set_node_attributes(G, sub_region_id, "sub_region")

    pos = nx.get_node_attributes(G, "pos")
    for u, v in G.edges():
        lat = calculate_latency(pos[u], pos[v], base_overhead=1)
        G.edges[u, v].update({"type": "internal", "latency": lat, "bandwidth": PHYSICS.bw_access, "multicast": True})

    calculate_centrality_roles(G)
    return G


def connect_global_layers(G):
    pos = nx.get_node_attributes(G, "pos")
    t1_nodes = [n for n, d in G.nodes(data=True) if d.get("layer") == "tier1"]
    t1_asns = list(set(G.nodes[n]["asn"] for n in t1_nodes))

    for as1, as2 in itertools.combinations(t1_asns, 2):
        nodes1 = [n for n in t1_nodes if G.nodes[n]["asn"] == as1]
        nodes2 = [n for n in t1_nodes if G.nodes[n]["asn"] == as2]

        candidates1 = [n for n in nodes1 if G.degree[n] >= 5]
        candidates2 = [n for n in nodes2 if G.degree[n] >= 5]
        if not candidates1:
            candidates1 = nodes1
        if not candidates2:
            candidates2 = nodes2

        best_pair = min(itertools.product(candidates1, candidates2), key=lambda p: get_geo_dist(pos[p[0]], pos[p[1]]))

        u, v = best_pair
        lat = calculate_latency(pos[u], pos[v], base_overhead=100)
        G.add_edge(u, v, type="peering", latency=lat, bandwidth=PHYSICS.bw_backbone)


def connect_ixp_transit(G, sub_region_groups):
    pos = nx.get_node_attributes(G, "pos")

    t1_nodes = [n for n, d in G.nodes(data=True) if d.get("layer") == "tier1"]

    for sub_r_id, t2_asns in sub_region_groups.items():
        if not t2_asns:
            continue

        region_nodes = [n for n, d in G.nodes(data=True) if d.get("sub_region") == sub_r_id]
        if not region_nodes:
            continue
        center_km = np.mean([pos[n] for n in region_nodes], axis=0)

        num_ixp_switches = max(3, int(len(t2_asns) * 0.8))
        ixp_nodes = []
        ixp_positions = {}
        fabric_radius_km = 10.0

        for i in range(num_ixp_switches):
            ixp_id = f"IXP_{sub_r_id}_SW{i}"
            angle = (2 * math.pi / num_ixp_switches) * i
            ixp_pos = (
                center_km[0] + fabric_radius_km * math.cos(angle),
                center_km[1] + fabric_radius_km * math.sin(angle),
            )

            G.add_node(ixp_id, pos=ixp_pos, layer="ixp", asn="Neutral", node_role="ixp_switch")
            ixp_nodes.append(ixp_id)
            ixp_positions[ixp_id] = ixp_pos

        for u, v in itertools.combinations(ixp_nodes, 2):
            lat = calculate_latency(ixp_positions[u], ixp_positions[v])
            G.add_edge(u, v, type="ixp_internal", latency=lat, bandwidth=PHYSICS.bw_backbone)

        for t2_asn in t2_asns:
            my_nodes = [n for n, d in G.nodes(data=True) if d.get("asn") == t2_asn]
            core_routers = sorted(
                [n for n in my_nodes if G.nodes[n].get("node_role") == "core_router"],
                key=lambda n: G.degree[n],
                reverse=True,
            )

            connect_count = min(len(core_routers), STRUCT.ixp_connection_count)
            if connect_count == 0 and core_routers:
                connect_count = 1

            target_routers = core_routers[:connect_count]
            if len(target_routers) < STRUCT.ixp_connection_count and core_routers:
                target_routers.extend([core_routers[0]] * (STRUCT.ixp_connection_count - len(target_routers)))

            available_ixp = list(ixp_nodes)
            random.shuffle(available_ixp)

            for i, router in enumerate(target_routers):
                if not router:
                    continue
                target_sw = available_ixp[i % len(available_ixp)]
                if not G.has_edge(router, target_sw):
                    lat = calculate_latency(pos[router], ixp_positions[target_sw])
                    G.add_edge(
                        router,
                        target_sw,
                        type="ixp_peering",
                        multicast=False,
                        latency=lat,
                        bandwidth=PHYSICS.bw_backbone,
                    )

    connect_transit_with_diversity(G, t1_nodes)


def connect_transit_with_diversity(G, t1_nodes):
    pos = nx.get_node_attributes(G, "pos")

    t2_nodes = [n for n, d in G.nodes(data=True) if d.get("layer") == "tier2"]
    t2_asns = list(set(G.nodes[n]["asn"] for n in t2_nodes))

    for asn in t2_asns:
        my_nodes = [n for n, d in G.nodes(data=True) if d.get("asn") == asn]
        gateways = [n for n in my_nodes if G.nodes[n].get("node_role") == "core_router"]

        gateways = sorted(gateways, key=lambda n: G.degree[n], reverse=True)
        if not gateways:
            continue

        gw_positions = [pos[n] for n in gateways]
        center_x = np.mean([p[0] for p in gw_positions])
        center_y = np.mean([p[1] for p in gw_positions])
        isp_center = (center_x, center_y)

        sorted_t1 = sorted(t1_nodes, key=lambda t1: get_geo_dist(isp_center, pos[t1]))

        pool_size = max(len(gateways), STRUCT.transit_candidate_pool_size)
        t1_candidates = sorted_t1[:pool_size]

        for i, gw in enumerate(gateways):
            target_t1 = t1_candidates[i % len(t1_candidates)]

            if not G.has_edge(gw, target_t1):
                lat = calculate_latency(pos[gw], pos[target_t1], base_overhead=20)
                G.add_edge(gw, target_t1, type="transit", multicast=False, latency=lat, bandwidth=PHYSICS.bw_transit)


def define_infrastructure(G):
    t2_nodes = [n for n, d in G.nodes(data=True) if d.get("layer") == "tier2"]
    t2_asns = list(set(G.nodes[n]["asn"] for n in t2_nodes))

    for asn in t2_asns:
        nodes = [n for n, d in G.nodes(data=True) if d.get("asn") == asn]
        routers = sorted(
            [n for n in nodes if G.nodes[n].get("node_role") == "core_router"], key=lambda n: G.degree[n], reverse=True
        )
        if not routers:
            continue

        G.nodes[routers[0]]["infrastructure_type"] = "relay"
        for r in routers[1:]:
            if random.random() < STRUCT.relay_probability:
                G.nodes[r]["infrastructure_type"] = "relay"


def generate_topology():
    G = nx.Graph()

    for i in range(STRUCT.num_tier1):
        as_id = f"T1_{i + 1}"
        angle = (2 * np.pi / STRUCT.num_tier1) * i
        center_km = (STRUCT.radius_tier1_global * np.cos(angle), STRUCT.radius_tier1_global * np.sin(angle))
        G = nx.compose(G, create_tier1_isp(as_id, center_km))

    connect_global_layers(G)

    t1_ids = [f"T1_{i + 1}" for i in range(STRUCT.num_tier1)]
    sub_region_groups = {}

    for i, t1_id in enumerate(t1_ids):
        angle = (2 * np.pi / STRUCT.num_tier1) * i
        t1_center_km = (STRUCT.radius_tier1_global * np.cos(angle), STRUCT.radius_tier1_global * np.sin(angle))

        num_sub_regions = random.randint(*STRUCT.sub_regions_range)
        for j in range(num_sub_regions):
            sub_r_id = f"{t1_id}_SubR_{j + 1}"
            sub_region_groups[sub_r_id] = []

            sub_angle = (2 * np.pi / num_sub_regions) * j + angle
            offset_km_x = 2000.0 * np.cos(sub_angle)
            offset_km_y = 2000.0 * np.sin(sub_angle)
            sub_center_km = (t1_center_km[0] + offset_km_x, t1_center_km[1] + offset_km_y)

            num_t2 = random.randint(*STRUCT.tier2_per_region_range)
            for k in range(num_t2):
                as_id = f"T2_{sub_r_id}_{k + 1}"
                sub_region_groups[sub_r_id].append(as_id)
                G = nx.compose(G, create_tier2_isp(as_id, sub_r_id, sub_center_km))

    connect_ixp_transit(G, sub_region_groups)
    define_infrastructure(G)

    return G


def get_visual_position(G):
    pos = nx.get_node_attributes(G, "pos")
    vis_pos = {}

    sub_regions = list(set(d.get("sub_region") for n, d in G.nodes(data=True) if "sub_region" in d))
    t1_layers = list(set(d.get("asn") for n, d in G.nodes(data=True) if d.get("layer") == "tier1"))
    clusters = sub_regions + t1_layers

    for cluster in clusters:
        if cluster in sub_regions:
            nodes = [n for n, d in G.nodes(data=True) if d.get("sub_region") == cluster]
        else:
            nodes = [n for n, d in G.nodes(data=True) if d.get("asn") == cluster]
        if not nodes:
            continue

        center_km = np.mean([pos[n] for n in nodes], axis=0)
        dist_to_origin = math.sqrt(center_km[0] ** 2 + center_km[1] ** 2)
        angle_to_origin = math.atan2(center_km[1], center_km[0])

        new_dist = dist_to_origin * VISUAL.compression_global
        new_center_x = new_dist * math.cos(angle_to_origin)
        new_center_y = new_dist * math.sin(angle_to_origin)

        for n in nodes:
            offset_x = pos[n][0] - center_km[0]
            offset_y = pos[n][1] - center_km[1]
            vis_x = new_center_x + (offset_x * VISUAL.compression_local)
            vis_y = new_center_y + (offset_y * VISUAL.compression_local)
            vis_pos[n] = (vis_x, vis_y)

    for n, d in G.nodes(data=True):
        if n not in vis_pos:
            neighbors = list(G.neighbors(n))
            valid_nbrs = [vis_pos[nbr] for nbr in neighbors if nbr in vis_pos]
            if valid_nbrs:
                vx = np.mean([p[0] for p in valid_nbrs])
                vy = np.mean([p[1] for p in valid_nbrs])
                vis_pos[n] = (vx, vy)
            else:
                vis_pos[n] = (0, 0)
    return vis_pos


def draw_topology_final(G):
    vis_pos = get_visual_position(G)
    plt.figure(figsize=(20, 16))

    sub_regions = sorted(list(set(d["sub_region"] for n, d in G.nodes(data=True) if "sub_region" in d)))
    base_cmaps = [matplotlib.colormaps[c] for c in ["Blues", "Reds", "Greens", "Purples", "Oranges", "GnBu"]]

    node_colors = {}
    for i, sub_r in enumerate(sub_regions):
        isps = sorted(list(set(d["asn"] for n, d in G.nodes(data=True) if d.get("sub_region") == sub_r)))
        cmap = base_cmaps[i % len(base_cmaps)]
        for j, asn in enumerate(isps):
            color_val = 0.4 + (0.6 * (j / max(len(isps), 1)))
            node_colors[asn] = cmap(color_val)

    t1_asns = sorted(list(set(d["asn"] for n, d in G.nodes(data=True) if d.get("layer") == "tier1")))
    for asn in t1_asns:
        node_colors[asn] = "lightgray"

    internal = [(u, v) for u, v, d in G.edges(data=True) if d.get("type") == "internal"]
    nx.draw_networkx_edges(
        G, vis_pos, edgelist=internal, alpha=VISUAL.edge_transparency, edge_color="#999999", width=0.6
    )

    transit = [(u, v) for u, v, d in G.edges(data=True) if d.get("type") == "transit"]
    peering = [(u, v) for u, v, d in G.edges(data=True) if d.get("type") == "peering"]
    ixp_link = [(u, v) for u, v, d in G.edges(data=True) if d.get("type") in ["ixp_peering", "ixp_internal"]]

    nx.draw_networkx_edges(G, vis_pos, edgelist=ixp_link, alpha=0.5, edge_color="silver", width=1.5)
    nx.draw_networkx_edges(G, vis_pos, edgelist=transit, alpha=0.7, edge_color="#2ca02c", width=1.5)
    nx.draw_networkx_edges(G, vis_pos, edgelist=peering, alpha=0.8, edge_color="purple", style="dashed", width=2.5)

    for n, d in G.nodes(data=True):
        asn = d.get("asn")
        color = node_colors.get(asn, "gray")

        if d.get("layer") == "ixp":
            nx.draw_networkx_nodes(
                G, vis_pos, nodelist=[n], node_color="silver", node_size=80, node_shape="h", alpha=0.9
            )
        elif d.get("infrastructure_type") == "relay":
            nx.draw_networkx_nodes(
                G,
                vis_pos,
                nodelist=[n],
                node_color=[color],
                node_size=150,
                node_shape="s",
                edgecolors="orange",
                linewidths=2.5,
                alpha=1.0,
            )
        elif d.get("node_role") == "core_router":
            nx.draw_networkx_nodes(
                G,
                vis_pos,
                nodelist=[n],
                node_color=[color],
                node_size=120,
                node_shape="s",
                edgecolors="black",
                linewidths=0.8,
                alpha=0.9,
            )
        else:
            nx.draw_networkx_nodes(G, vis_pos, nodelist=[n], node_color=[color], node_size=25, alpha=0.7)

    legend_elements = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#4287f5", label="Region A ISP", markersize=10),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#f54242", label="Region B ISP", markersize=10),
        Line2D(
            [0],
            [0],
            marker="s",
            color="w",
            markerfacecolor="gray",
            markeredgecolor="orange",
            markeredgewidth=2,
            label="AMT Relay Infra",
            markersize=12,
        ),
        Line2D([0], [0], color="purple", linestyle="dashed", linewidth=2, label="Tier 1 Peering"),
        Line2D([0], [0], color="#2ca02c", linewidth=2, label="Transit (Diversity Fix)"),
    ]
    plt.legend(handles=legend_elements, loc="upper right")
    plt.title("Final RFC 7450 Topology: No SPOF, Physics-View Decoupled", fontsize=16)
    plt.axis("off")
    plt.tight_layout()
    plt.show()


def verify_physical_properties(G):
    print("\n=== NETWORK INTEGRITY CHECK ===")
    edge_types = ["peering", "transit", "internal", "ixp_peering"]
    stats = {t: {"lat": [], "bw": []} for t in edge_types}

    for u, v, d in G.edges(data=True):
        t = d.get("type")
        if t in stats:
            stats[t]["lat"].append(d.get("latency", 0))
            stats[t]["bw"].append(d.get("bandwidth", 0))

    for t, data in stats.items():
        if not data["lat"]:
            continue
        avg_lat = sum(data["lat"]) / len(data["lat"])
        print(f"[{t.upper()}] Latency: {min(data['lat'])} ~ {max(data['lat'])} ms (Avg {avg_lat:.1f})")
    print("===============================\n")


if __name__ == "__main__":
    G_final = generate_topology()
    verify_physical_properties(G_final)
    draw_topology_final(G_final)
