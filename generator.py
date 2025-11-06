import addict
import re
import tomllib
import networkx as nx
from typing import List, Dict, Tuple, NewType
from dataclasses import dataclass
from icecream import ic

Node = NewType("Node", str)
Address = NewType("Address", str)


@dataclass
class AppConfig:
    type: str
    node: Node
    address: Address
    start: float
    stop: float


@dataclass
class ScenarioPolicy:
    max_connection: int


class ScenarioGenerator:
    def __init__(self, meta):
        with open(meta, "rb") as f:
            config = addict.Dict(tomllib.load(f))
            self.graph, self.mgraph = self._parse_topology(config)
            self.policy = self._parse_policy(config)
            self.application = self._parse_application(config)

            ic(self.policy)

    def _parse_topology(self, config) -> Tuple[nx.Graph, nx.Graph]:
        G = nx.Graph()

        for j, paths in enumerate(config.topology.values()):
            for k, path in enumerate(paths):
                node_and_links = re.split("( -- | - )", path)

                for i, index in enumerate(range(0, len(node_and_links) - 2, 2)):
                    u = node_and_links[index]
                    v = node_and_links[index + 2]
                    e = node_and_links[index + 1]

                    G.add_edge(u, v, is_multicast_enabled=e == " - ", subnet=f"{10 + k}.{10 + j}.{i + 1}.0")

        def is_multicast_enabled(u, v):
            return G[u][v]["is_multicast_enabled"]

        return G, nx.subgraph_view(G, filter_edge=is_multicast_enabled)

    def _parse_application(self, config) -> List[AppConfig]:
        return [
            AppConfig(app.type, Node(app.node), Address(app.address), app.start, app.stop) for app in config.application
        ]

    def _parse_policy(self, config):
        return ScenarioPolicy(config["policy"]["relay"]["max_connection"])
