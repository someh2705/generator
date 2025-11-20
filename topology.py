import networkx as nx

core_topology = nx.barabasi_albert_graph(n=100, m=2)

nx.set_node_attributes(core_topology, False, "mcast_enabled")
nx.set_edge_attributes(core_topology, "unicast_core", "type")


def create_mcast_group(group_id, n_nodes=20):
    group = nx.watts_strogatz_graph(n=n_nodes, k=4, p=0.1)

    nx.set_node_attributes(group, True, "mcast_enabled")
    nx.set_node_attributes(group, f"group_{group_id}", "group_id")
    return group


mcast_groups = [create_mcast_group(i) for i in range(50)]

global_topology = core_topology.copy()

import random

core_nodes = list(core_topology.nodes())

for i, group in enumerate(mcast_groups):
    mapping = {node: f"g{i}_n{node}" for node in group.nodes()}
    group_relabeled = nx.relabel_nodes(group, mapping)
    global_topology = nx.union(global_topology, group_relabeled)

    gateway_node = random.choice(list(group_relabeled.nodes()))
    core_access_node = random.choice(core_nodes)

    global_topology.add_edge(gateway_node, core_access_node, type="uplink", mcast_enabled=False)

print(global_topology.nodes())
