import networkx as nx
from typing import List
from icecream import ic
from application import HostApp, SinkApp, RelayApp, GatewayApp, AppType, create_gateway, create_relay
from timeline import Timeline, TimelineState, TimelineAction
from scheduler import ScenarioScheduler


class ScenarioBuilder:
    def __init__(self, generator):
        self.graph = generator.graph
        self.mgraph = generator.mgraph
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

        if True:
            self._single_amt_routing(snapshot, sink)

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

    def _find_amt_gateway(self, snapshot: TimelineState, sink: SinkApp) -> GatewayApp:
        gateway_node = min(
            [
                node
                for node in self.mgraph.nodes()
                if str.startswith(node, "gateway") and nx.has_path(self.mgraph, node, sink.node)
            ],
            key=lambda node: nx.shortest_path_length(self.mgraph, node, sink.node),
        )
        return snapshot.spawn_gateway(gateway_node)

    # ================================
    #
    #  RFC 7450 AMT Version
    #
    # ===============================
    def _single_amt_routing(self, snapshot: TimelineState, sink: SinkApp):
        host = self._find_host(snapshot, sink)
        gateway = self._find_amt_gateway(snapshot, sink)
        relay = self._single_amt_relay_discovery(snapshot, host, sink)

        snapshot.connect(host.id, gateway.id, relay.id, sink.id)

    def _single_amt_relay_discovery(self, snapshot: TimelineState, host: HostApp, sink: SinkApp):
        relay_node = min(
            [
                node
                for node in self.mgraph.nodes()
                if str.startswith(node, "relay") and nx.has_path(self.mgraph, host.node, node)
            ],
            key=lambda node: (
                2 * nx.shortest_path_length(self.graph, node, sink.node)
                - nx.shortest_path_length(self.mgraph, host.node, node)
            ),
        )
        return snapshot.spawn_relay(relay_node)

    # ================================
    #
    #  Multi-Hop AMT Version
    #
    # ===============================
    def _multihop_amt_routing(self, snapshot: TimelineState, sink: SinkApp):
        host = self._find_host(snapshot, sink)
        gateway = self._find_amt_gateway(snapshot, sink)
        relay = self._multihop_amt_relay_discovery(snapshot, host, sink)

    def _multihop_amt_relay_discovery(self, snapshot: TimelineState, host: HostApp, sink: SinkApp):
        pass


def _nearest_node(graph, apps: List[AppType], target) -> AppType:
    return min(apps, key=lambda app: nx.shortest_path_length(graph, app.node, target.node))
