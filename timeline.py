import copy
from generator import Node
from application import AppId, HostApp, SinkApp, RelayApp, GatewayApp, Tunnel, create_gateway, create_relay
from icecream import ic
from typing import Dict, List
from dataclasses import dataclass, field, replace


@dataclass
class TimelineState:
    mapping_ids: Dict[AppId, Dict] = field(default_factory=dict)
    running_hosts: Dict[AppId, HostApp] = field(default_factory=dict)
    running_sinks: Dict[AppId, SinkApp] = field(default_factory=dict)
    running_relays: Dict[AppId, RelayApp] = field(default_factory=dict)
    running_gateways: Dict[AppId, GatewayApp] = field(default_factory=dict)
    running_tunnels: List[Tunnel] = field(default_factory=list)

    multicast_routes: List = field(default_factory=list)

    def resolve(self, id: AppId):
        return self.mapping_ids[id][id]

    def schedule(self, app):
        if isinstance(app, HostApp):
            self._safe_assign(self.running_hosts, app.id, app)
        if isinstance(app, SinkApp):
            self._safe_assign(self.running_sinks, app.id, app)
        if isinstance(app, GatewayApp):
            self._safe_assign(self.running_gateways, app.id, app)

    def shutdown(self, app):
        if isinstance(app, HostApp):
            self._safe_delete(self.running_hosts, app.id)
        if isinstance(app, SinkApp):
            self._safe_delete(self.running_sinks, app.id)

    def join(self, host_id: AppId, sink_id: AppId):
        host = self.running_hosts[host_id]
        sinks = copy.deepcopy(host.sinks)
        self._safe_append(sinks, sink_id)
        host = replace(host, sinks=sinks)
        self._safe_replace(self.running_hosts, host_id, host)

    def leave(self, host_id: AppId, sink_id: AppId):
        host = self.running_hosts[host_id]
        sinks = copy.deepcopy(host.sinks)
        self._safe_remove(sinks, sink_id)
        host = replace(host, sinks=sinks)
        self._safe_replace(self.running_hosts, host_id, host)

    def bind(self, gateway_id: AppId, sink_id: AppId):
        gateway = self.running_gateways[gateway_id]
        sinks = copy.deepcopy(gateway.sinks)
        self._safe_append(sinks, sink_id)
        gateway = replace(gateway, sinks=sinks)
        self._safe_replace(self.running_gateways, gateway.id, gateway)

    def unbind(self, gateway_id: AppId, sink_id: AppId):
        gateway = self.running_gateways[gateway_id]
        sinks = copy.deepcopy(gateway.sinks)
        self._safe_remove(sinks, sink_id)
        gateway = replace(gateway, sinks=sinks)
        if not sinks:
            tunnel = self._find_tunnel(gateway_id=gateway_id)
            relay_id = tunnel.relay_id
            self._safe_delete(self.running_gateways, gateway.id)
            self._safe_delete(self.running_relays, relay_id)
            self._safe_remove(self.running_tunnels, tunnel)
        else:
            self._safe_replace(self.running_gateways, gateway.id, gateway)

    def spawn_gateway(self, gateway_node: Node, relay_id: AppId) -> GatewayApp:
        gateway = create_gateway(gateway_node, relay_id)
        self._safe_assign(self.running_gateways, gateway.id, gateway)
        return gateway

    def spawn_relay(self, relay_node: Node, source_id: AppId) -> RelayApp:
        relay = create_relay(relay_node, source_id)
        self._safe_assign(self.running_relays, relay.id, relay)
        return relay

    def connect(self, source_id: AppId, gateway_id: AppId, relay_id: AppId, sink_id: AppId):
        gateway = self.running_gateways[gateway_id]
        sinks = copy.deepcopy(gateway.sinks)
        self._safe_append(sinks, sink_id)
        gateway = replace(gateway, sinks=sinks)

        self._safe_replace(self.running_gateways, gateway_id, gateway)
        self._safe_append(self.running_tunnels, Tunnel(source_id, relay_id, gateway_id))

    def _find_tunnel(self, relay_id: AppId | None = None, gateway_id: AppId | None = None) -> Tunnel:
        for tunnel in self.running_tunnels:
            if tunnel.gateway_id == gateway_id or tunnel.relay_id == relay_id:
                return tunnel
        else:
            raise KeyError()

    def _safe_assign(self, d, k, v):
        assert d.get(k, None) is None and v is not None, "safe assign error"
        self.mapping_ids[k] = d
        d[k] = v

    def _safe_delete(self, d, k):
        assert d.get(k, None) is not None, "safe delete error"
        del self.mapping_ids[k]
        del d[k]

    def _safe_append(self, s, v):
        assert v not in s, "safe append error"
        s.append(v)

    def _safe_remove(self, s, v):
        assert v in s, "safe remove error"
        s.remove(v)

    def _safe_replace(self, d, k, v):
        assert d.get(k, None) is not None and v is not None, "safe replace error"
        self.mapping_ids[k] = d
        d[k] = v


@dataclass
class TimelineAction:
    schedule_hosts: Dict[AppId, HostApp] = field(default_factory=dict)
    schedule_sinks: Dict[AppId, SinkApp] = field(default_factory=dict)
    shutdown_hosts: Dict[AppId, HostApp] = field(default_factory=dict)
    shutdown_sinks: Dict[AppId, SinkApp] = field(default_factory=dict)

    def schedule(self, app):
        if isinstance(app, HostApp):
            self._safe_assign(self.schedule_hosts, app.id, app)
        elif isinstance(app, SinkApp):
            self._safe_assign(self.schedule_sinks, app.id, app)
        else:
            raise TypeError()

    def shutdown(self, app):
        if isinstance(app, HostApp):
            self._safe_assign(self.shutdown_hosts, app.id, app)
        elif isinstance(app, SinkApp):
            self._safe_assign(self.shutdown_sinks, app.id, app)
        else:
            raise TypeError()

    def _safe_assign(self, d, k, v):
        assert d.get(k, None) is None and v is not None, "safe assign error"
        d[k] = v


@dataclass
class Timeline:
    time: float = -1.0
    action: TimelineAction = field(default_factory=TimelineAction)
    snapshot: TimelineState = field(default_factory=TimelineState)

    def schedule(self, app):
        self.action.schedule(app)

    def shutdown(self, app):
        self.action.shutdown(app)
