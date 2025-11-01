#!/usr/bin/env python3

import argparse
import tomllib
import re
import addict
import networkx as nx
from collections import defaultdict
from typing import List, Dict
from icecream import ic
from dataclasses import dataclass

is_multihop = None
OnOff = "OnOff"
PacketSink = "PacketSink"


@dataclass
class Policy:
    relay_max_sessions: int


@dataclass
class Application:
    id: str
    type: str
    node: str
    address: str
    start: float
    stop: float


@dataclass
class OnOffApp:
    id: str
    node: str
    address: str


@dataclass
class PacketSinkApp:
    id: str
    node: str
    address: str


@dataclass
class RelayApp:
    id: str
    node: str
    address: str


@dataclass
class GatewayApp:
    id: str
    node: str
    address: str
    relay: RelayApp
    sinks: List[str]


@dataclass
class Tunnel:
    id: str
    relay_id: str
    gateway_id: str


@dataclass
class Timeline:
    time: float
    booting_sinks: List[PacketSinkApp]
    booting_hosts: List[OnOffApp]

    shutdown_hosts: List[OnOffApp]
    shutdown_sinks: List[PacketSinkApp]


class ScenarioGenerator:
    def __init__(self, meta):
        with open(meta, "rb") as f:
            config = addict.Dict(tomllib.load(f))
            self.graph, self.mgraph = self._parse_topology(config)
            self.policy = self._parse_policy(config)
            self.application = self._parse_application(config)

        self.nodes = sorted([n for n in self.graph.nodes()])
        self.relays = [n for n in self.nodes if n.startswith("relay")]
        self.gateways = [n for n in self.nodes if n.startswith("gateway")]

    def _parse_topology(self, config):
        G = nx.Graph()

        for j, paths in enumerate(config.topology.values()):
            for path in paths:
                node_and_links = re.split("( -- | - )", path)

                for i in range(0, len(node_and_links) - 2, 2):
                    u = node_and_links[i]
                    v = node_and_links[i + 2]
                    e = node_and_links[i + 1]

                    G.add_edge(u, v, is_multicast_enabled=e == " - ", subnet=f"10.{j}.{i}.0")

        def is_multicast_enabled(u, v):
            return self.graph[u][v]["is_multicast_enabled"]

        return G, nx.subgraph_view(G, filter_edge=is_multicast_enabled)

    def _parse_policy(self, config):
        return Policy(config.relay_max_sessions)

    def _parse_application(self, config):
        return [
            Application(f"{app.node}#{i}", app.type, app.node, app.address, app.start, app.stop)
            for i, app in enumerate(config.application)
        ]

    def generate(self):
        return self._schedule_scenario()

    def _schedule_scenario(self):
        builder = ScenarioBuilder(self)
        builder.schedule()
        return builder.scenarios


class ScenarioBuilder:
    def __init__(self, generator: ScenarioGenerator):
        self.graph = generator.graph
        self.mgraph = generator.mgraph
        self.policy = generator.policy
        self.nodes = generator.nodes
        self.relays = generator.relays
        self.gateways = generator.gateways
        self.application = generator.application

        self.counter = defaultdict(int)

    def schedule(self):
        self.scenarios = []

        self._running_hosts: Dict[str, OnOffApp] = {}
        self._running_sinks: Dict[str, PacketSinkApp] = {}
        self._running_relays: Dict[str, RelayApp] = {}
        self._running_gateways: Dict[str, GatewayApp] = {}
        self._running_tunnels: Dict[str, Tunnel] = {}

        self._timeline = self._schedule_timeline()

        for time, timeline in sorted(self._timeline.items(), key=lambda t: t[0]):
            self._process_schedule(time, timeline)

    def _schedule_timeline(self):
        timeline: Dict[float, Timeline] = defaultdict(lambda: Timeline(-1.0, [], [], [], []))

        for app in self.application:
            if app.type == OnOff:
                host_id = self._unique_id("host")
                host = OnOffApp(host_id, app.node, app.address)
                timeline[app.start].booting_hosts.append(host)
                timeline[app.stop].shutdown_hosts.append(host)
            if app.type == PacketSink:
                sink_id = self._unique_id("sink")
                sink = PacketSinkApp(sink_id, app.node, app.address)
                timeline[app.start].booting_sinks.append(sink)
                timeline[app.stop].shutdown_sinks.append(sink)

        return timeline

    def _process_schedule(self, time, timeline: Timeline):
        self._routing_multicast(time, timeline)
        self._release_application(time, timeline)

    def _release_application(self, time, timeline):
        commands = set()

        for app in timeline.shutdown_hosts:
            self._safe_assign(self._running_hosts, app.id, None)

        # TODO: shutdown hosts
        for app in timeline.shutdown_sinks:
            for tunnel in self._running_tunnels.values():
                gateway = self._running_gateways[tunnel.gateway_id]
                if app.id in gateway.sinks:
                    commands.add((tunnel.id, gateway.id, app.id))

        for tunnel_id, gateway_id, app_id in commands:
            gateway = self._running_gateways[gateway_id]

            if len(gateway.sinks) > 1:
                gateway.sinks.remove(app_id)
                continue

            tunnel = self._running_tunnels[tunnel_id]
            relay = self._running_relays[tunnel.relay_id]
            self._safe_assign(self._running_sinks, app_id, None)
            self._safe_assign(self._running_tunnels, tunnel_id, None)
            self._safe_assign(self._running_gateways, gateway_id, None)
            self._safe_assign(self._running_relays, relay.id, None)

    def _routing_multicast(self, time, timeline):
        paths = []

        for app in timeline.booting_hosts:
            self._safe_assign(self._running_hosts, app.id, app)

        for app in timeline.booting_sinks:
            self._safe_assign(self._running_sinks, app.id, app)

            if tunnel := self._is_tunnel_available(app):
                self._register_sink(tunnel, app)
                continue

            hosts = [
                host
                for host in self._running_hosts.values()
                if host.address == app.address and nx.has_path(self.graph, host.node, app.node)
            ]
            host = min(hosts, key=lambda host: nx.shortest_path_length(self.graph, host.node, app.node))

            if nx.has_path(self.mgraph, host.node, app.node):
                paths.append(self._routing_reachable_multicast_network(host, app))
            else:
                paths.append(self._routing_unreachable_multicast_network(host, app))

        ic(paths)

    def _is_tunnel_available(self, app) -> Tunnel | None:
        tunnels = [
            t
            for t in self._running_tunnels.values()
            if nx.has_path(self.mgraph, self._running_gateways[t.gateway_id].node, app.node)
        ]

        if tunnels:
            return min(
                tunnels,
                key=lambda t: nx.shortest_path_length(self.mgraph, self._running_gateways[t.gateway_id].node, app.node),
            )

    def _routing_reachable_multicast_network(self, host, app):
        return nx.shortest_path(self.mgraph, host.node, app.node)

    def _routing_unreachable_multicast_network(self, host, sink):
        gateway = self._find_gateway(sink)
        relay = self._relay_discovery(host)

        relay_path = nx.shortest_path(self.mgraph, host.node, relay)
        gateway_path = nx.shortest_path(self.mgraph, gateway, sink.node)

        self._run_tunnel(relay, gateway, host, sink)

        return [relay_path, gateway_path]

    def _find_gateway(self, app):
        gateways = [g for g in self.gateways if nx.has_path(self.mgraph, g, app.node)]
        return min(gateways, key=lambda g: nx.shortest_path_length(self.mgraph, g, app.node))

    def _relay_discovery(self, host):
        if is_multihop:
            return self._multihop_relay_discovery(host)
        return self._singlehop_relay_discovery(host)

    def _singlehop_relay_discovery(self, host):
        relays = [r for r in self.relays if nx.has_path(self.mgraph, host.node, r)]
        return min(relays, key=lambda r: -nx.shortest_path_length(self.graph, host.node, r))

    def _multihop_relay_discovery(self, source):
        pass
        # relay = self._singlehop_relay_discovery(source)
        # tunnels = self._find_running_tunnel(source, relay)

        # if tunnel and len(tunnel.relay.gateways) == self.policy.relay_max_sessions:
        #     return self._find_relay_nearby_running_gateway(source, tunnel)

        # return relay

    def _run_tunnel(self, relay, gateway, host, sink) -> Tunnel:
        relayId = self._unique_id("relay")
        gatewayId = self._unique_id("gateway")
        tunnelId = self._unique_id("tunnel")

        relayApp = RelayApp(relayId, relay, host.address)
        gatewayApp = GatewayApp(gatewayId, gateway, host.address, relayApp, [])
        tunnel = Tunnel(tunnelId, relayId, gatewayId)

        self._running_relays[relayId] = relayApp
        self._running_gateways[gatewayId] = gatewayApp
        self._running_tunnels[tunnelId] = tunnel
        self._register_sink(tunnel, sink)

        return tunnel

    def _register_sink(self, tunnel, app):
        gatewayApp = self._running_gateways[tunnel.gateway_id]
        gatewayApp.sinks.append(app.node)

    def _find_running_tunnel(self, source, relay):
        pass

    def _find_relay_nearby_running_gateway(self, source, tunnel):
        pass

    # === utils ===

    def _find_closest_node(self, graph, nodes, target):
        return min(nodes, key=lambda n: nx.shortest_path_length(graph, n, target))

    def _unique_id(self, prefix):
        id = self.counter[prefix]
        self.counter[prefix] += 1

        return f"{prefix}#{id}"

    def _safe_assign(self, d, k, v):
        assert d.get(k, None) is None or v is None, "safe assign error"
        if v is None:
            del d[k]
        else:
            d[k] = v


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("meta", help="Input TOML file")
    parser.add_argument("-o", "--out", help="Output JSON file")
    parser.add_argument("--multihop", default=False, action=argparse.BooleanOptionalAction)
    args = parser.parse_args()

    global is_multihop
    is_multihop = args.multihop
    is_multihop = True

    generator = ScenarioGenerator(args.meta)
    generator.generate()


if __name__ == "__main__":
    main()
