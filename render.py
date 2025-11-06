import yaml
import networkx as nx
from generator import ScenarioGenerator
from icecream import ic
from typing import List, Dict
from timeline import Timeline


class ScenarioRender:
    def __init__(self, generator: ScenarioGenerator, scenarios: Dict[float, Timeline]):
        self.graph = generator.graph
        self.mgraph = generator.mgraph
        self.scenarios = scenarios

        self.render()

    def render(self):
        simulator_spec = {}
        simulator_spec["nodes"] = self._nodes()
        simulator_spec["links"] = self._links()
        simulator_spec["scenarios"] = self._scenarios()

        spec = yaml.dump(simulator_spec, default_flow_style=False, sort_keys=False, indent=2)

    def _nodes(self) -> List[str]:
        return sorted([node for node in self.graph.nodes()])

    def _links(self) -> List[Dict]:
        links = []
        for edge in self.graph.edges():
            spec = {}
            spec["name"] = self._subnet_with_node(edge)
            spec["subnet"] = self._subnet(edge)
            spec["nodes"] = self._nodes_in_edge(edge)
            links.append(spec)

        return sorted(links, key=lambda link: link["subnet"])

    def _scenarios(self) -> List[Dict]:
        scenarios = []
        for time, scenario in self.scenarios.items():
            spec = {}
            spec["time"] = time
            spec["multicast_routes"] = self._multicast_routes(scenario)

    def _subnet(self, edge) -> str:
        return self.graph[edge[0]][edge[1]]["subnet"]

    def _nodes_in_edge(self, edge) -> List[str]:
        return [edge[0], edge[1]]

    def _subnet_with_node(self, edge) -> str:
        return f"{self._subnet(edge)}-{edge[0]}-{edge[1]}"

    def _multicast_routes(self, scenario: Timeline):
        spec = {}

        paths = []
        for host in scenario.snapshot.running_hosts.values():
            for sink_id in host.sinks:
                sink = scenario.snapshot.running_sinks[sink_id]
                paths.append(nx.shortest_path(self.mgraph, host.node, sink.node))

        for tunnel in scenario.snapshot.running_tunnels:
            host = scenario.snapshot.running_hosts[tunnel.host_id]
            relay = scenario.snapshot.running_relays[tunnel.relay_id]
            gateway = scenario.snapshot.running_gateways[tunnel.gateway_id]

            paths.append(nx.shortest_path(self.mgraph, host.node, relay.node))

            for sink_id in gateway.sinks:
                sink = scenario.snapshot.running_sinks[sink_id]
                paths.append(nx.shortest_path(self.mgraph, gateway.node, sink.node))

        ic(scenario.time, paths)
