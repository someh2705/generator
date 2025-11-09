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
class HostPolicy:
    size: int
    byte: int
    rate: str
    on: float
    off: float


@dataclass
class RelayPolicy:
    max_connections: int
    mode: str
    max: int


@dataclass
class LinkPolicy:
    rate: str
    delay: str


@dataclass
class ScenarioPolicy:
    host_policy: HostPolicy
    relay_policy: RelayPolicy
    link_policy: Dict[Tuple[str, str], LinkPolicy]


class ScenarioGenerator:
    def __init__(self, meta):
        with open(meta, "rb") as f:
            config = addict.Dict(tomllib.load(f))
            self.policy = self._parse_policy(config)
            self.graph, self.mgraph = self._parse_topology(config)
            self.application = self._parse_application(config)

    def _parse_topology(self, config) -> Tuple[nx.Graph, nx.Graph]:
        G = nx.Graph()

        for j, paths in enumerate(config.topology.values()):
            for k, path in enumerate(paths):
                node_and_links = re.split("( -- | - )", path)

                for i, index in enumerate(range(0, len(node_and_links) - 2, 2)):
                    u = node_and_links[index]
                    v = node_and_links[index + 2]
                    e = node_and_links[index + 1]

                    policy = self.policy.link_policy[(self._node_type(u), self._node_type(v))]
                    d = {
                        "is_multicast_enabled": e == " - ",
                        "subnet": f"{10 + k}.{10 + j}.{i + 1}.0",
                        "rate": policy.rate,
                        "delay": policy.delay,
                    }

                    G.add_edge(u, v, **d)

        def is_multicast_enabled(u, v):
            return G[u][v]["is_multicast_enabled"]

        return G, nx.subgraph_view(G, filter_edge=is_multicast_enabled)

    def _parse_application(self, config) -> List[AppConfig]:
        return [
            AppConfig(app.type, Node(app.node), Address(app.address), app.start, app.stop) for app in config.application
        ]

    def _node_type(self, node) -> str:
        if str.startswith(node, "host"):
            return "host"
        elif str.startswith(node, "sink"):
            return "sink"
        elif str.startswith(node, "relay"):
            return "relay"
        elif str.startswith(node, "gateway"):
            return "gateway"
        else:
            return "router"

    def _parse_policy(self, config) -> ScenarioPolicy:
        policy = config.policy
        host = policy.host
        relay = policy.relay
        link = policy.link
        host_policy = HostPolicy(host.size, host.byte, host.rate, host.on, host.off)
        relay_policy = RelayPolicy(relay.max_connections, relay.mode, relay.max)
        link_policy = {}
        for key, data in link.items():
            u, v = key.split("-")
            _policy = LinkPolicy(data.rate, data.delay)
            link_policy[(u, v)] = _policy
            link_policy[(v, u)] = _policy

        return ScenarioPolicy(host_policy, relay_policy, link_policy)
