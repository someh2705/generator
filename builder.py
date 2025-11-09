import networkx as nx
from typing import List, Tuple
from icecream import ic
from application import AppId, HostApp, SinkApp, RelayApp, GatewayApp, AppType, create_gateway, create_relay
from generator import Node, ScenarioGenerator
from itertools import product
from timeline import TimelineState, TimelineAction
from scheduler import ScenarioScheduler


class ScenarioBuilder:
    def __init__(self, generator: ScenarioGenerator):
        self.graph = generator.graph
        self.mgraph = generator.mgraph
        self.policy = generator.policy
        self.application = generator.application

    def build(self):
        scheduler = ScenarioScheduler(self.application)
        return scheduler.process(self._process_timeline)

    def _process_timeline(self, snapshot: TimelineState, action: TimelineAction):
        self._running_application(snapshot, action)
        self._release_application(snapshot, action)
        return snapshot

    def _release_application(self, snapshot: TimelineState, action):
        for host_id, host in action.shutdown_hosts.items():
            assert not host.sinks, "host must empty"
            snapshot.shutdown(host)

        commands = []

        for sink_id, sink in action.shutdown_sinks.items():
            for host in snapshot.running_hosts.values():
                if sink_id in host.sinks:
                    snapshot.leave(host.id, sink_id)

            for gateway in snapshot.running_gateways.values():
                if sink_id in gateway.sinks:
                    commands.append((gateway, sink))
            snapshot.shutdown(sink)

        for gateway, sink in commands:
            snapshot.unbind(gateway.id, sink.id)

    def _running_application(self, snapshot: TimelineState, action):
        for host_id, host in action.schedule_hosts.items():
            snapshot.schedule(host)

        for sink_id, sink in action.schedule_sinks.items():
            self._running_sink(snapshot, sink)

    def _running_sink(self, snapshot: TimelineState, sink: SinkApp):
        snapshot.schedule(sink)

        if self._has_path_to_gateway(snapshot, sink):
            return

        if self._is_reachable_host(snapshot, sink):
            return

        if False:
            self._single_amt_routing(snapshot, sink)
        else:
            self._multihop_amt_routing(snapshot, sink)

    def _has_path_to_gateway(self, snapshot: TimelineState, sink) -> bool:
        for gateway in snapshot.running_gateways.values():
            if nx.has_path(self.mgraph, gateway.node, sink.node):
                snapshot.bind(gateway.id, sink.id)
                return True

        return False

    def _is_reachable_host(self, snapshot: TimelineState, sink: SinkApp) -> bool:
        for host in snapshot.running_hosts.values():
            if nx.has_path(self.mgraph, host.node, sink.node):
                snapshot.join(host.id, sink.id)
                return True

        return False

    def _find_host(self, snapshot: TimelineState, sink: SinkApp) -> HostApp:
        return min(
            [host for host in snapshot.running_hosts.values()],
            key=lambda host: nx.shortest_path_length(self.graph, host.node, sink.node),
        )

    def _find_amt_gateway(self, snapshot: TimelineState, sink: SinkApp, relay: RelayApp) -> GatewayApp:
        gateway_node = min(
            [
                node
                for node in self.mgraph.nodes()
                if str.startswith(node, "gateway") and nx.has_path(self.mgraph, node, sink.node)
            ],
            key=lambda node: nx.shortest_path_length(self.mgraph, node, sink.node),
        )
        return snapshot.spawn_gateway(gateway_node, relay.id)

    def _relay_length(self, node: Node, sink_node: Node, host_node: Node) -> float:
        return 2 * nx.shortest_path_length(self.graph, node, sink_node) - nx.shortest_path_length(
            self.mgraph, host_node, node
        )

    # ================================
    #
    #  RFC 7450 AMT Version
    #
    # ===============================
    def _single_amt_routing(self, snapshot: TimelineState, sink: SinkApp):
        host = self._find_host(snapshot, sink)
        relay = self._single_amt_relay_discovery(snapshot, host, sink)
        gateway = self._find_amt_gateway(snapshot, sink, relay)

        snapshot.connect(host.id, gateway.id, relay.id, sink.id)

    def _single_amt_relay_discovery(self, snapshot: TimelineState, host: HostApp, sink: SinkApp) -> RelayApp:
        relay_node = min(
            [
                node
                for node in self.mgraph.nodes()
                if str.startswith(node, "relay") and nx.has_path(self.mgraph, host.node, node)
            ],
            key=lambda node: self._relay_length(node, sink.node, host.node),
        )
        return snapshot.spawn_relay(relay_node, host.id)

    # ================================
    #
    #  Multi-Hop AMT Version
    #
    # ===============================
    def _multihop_amt_routing(self, snapshot: TimelineState, sink: SinkApp):
        host = self._find_host(snapshot, sink)
        source, relay = self._multihop_amt_relay_discovery(snapshot, host, sink)
        gateway = self._find_amt_gateway(snapshot, sink, relay)

        snapshot.connect(source.id, gateway.id, relay.id, sink.id)

    def _multihop_amt_relay_discovery(
        self, snapshot: TimelineState, host: HostApp, sink: SinkApp
    ) -> Tuple[HostApp | GatewayApp, RelayApp]:
        available_multicast_relay_nodes = sorted(
            [
                node
                for node in self.mgraph.nodes()
                if str.startswith(node, "relay") and nx.has_path(self.mgraph, host.node, node)
            ],
            key=lambda node: self._relay_length(node, sink.node, host.node),
        )

        error_relay_node = min(available_multicast_relay_nodes, key=lambda node: self._connected_counts(snapshot, node))

        for relay_node in available_multicast_relay_nodes:
            if self._is_available_policy(snapshot, relay_node):
                return host, snapshot.spawn_relay(relay_node, host.id)

        gateways = [
            gateway
            for gateway in snapshot.running_gateways.values()
            if self._resolve_host(snapshot, gateway.id).address == sink.address
        ]

        source, available_relay_node = min(
            [
                (gateway, relay_node)
                for gateway, relay_node in product(
                    gateways,
                    [
                        node
                        for node in self.graph.nodes()
                        if str.startswith(node, "relay") and node not in available_multicast_relay_nodes
                    ],
                )
                if nx.has_path(self.mgraph, gateway.node, relay_node)
                and self._is_available_policy(snapshot, relay_node)
            ],
            key=lambda t: self._relay_length(t[1], sink.node, t[0].node),
            default=(host, error_relay_node),
        )

        ic(source.node, available_relay_node)
        return source, snapshot.spawn_relay(available_relay_node, source.id)

    # TODO: traffic 기반으로 변경하는게 좋음.
    def _is_available_policy(self, snapshot, relay_node) -> bool:
        return self._connected_counts(snapshot, relay_node) < self.policy.relay_policy.max_connections

    def _connected_counts(self, snapshot, relay_node) -> int:
        running_relays = [relay for relay in snapshot.running_relays.values() if relay.node == relay_node]
        return len(running_relays)

    def _resolve_host(self, snapshot: TimelineState, gateway_id: AppId) -> HostApp:
        tunnel = snapshot._find_tunnel(gateway_id=gateway_id)
        relay = snapshot.running_relays[tunnel.relay_id]
        source = snapshot.resolve(relay.source_id)

        if isinstance(source, HostApp):
            return source

        if isinstance(source, GatewayApp):
            return self._resolve_host(snapshot, source.id)

        raise Exception()


def _nearest_node(graph, apps: List[AppType], target) -> AppType:
    return min(apps, key=lambda app: nx.shortest_path_length(graph, app.node, target.node))
