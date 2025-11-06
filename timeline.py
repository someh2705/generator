import copy
from generator import Node
from application import AppId, HostApp, SinkApp, RelayApp, GatewayApp, Tunnel, create_gateway, create_relay
from icecream import ic
from typing import Dict, List
from dataclasses import dataclass, field, replace


def _safe_assign(d, k, v):
    assert d.get(k, None) is None and v is not None, "safe assign error"
    d[k] = v


def _safe_delete(d, k):
    assert d.get(k, None) is not None, "safe delete error"
    del d[k]


def _safe_append(s, v):
    assert v not in s, "safe append error"
    s.append(v)


def _safe_remove(s, v):
    assert v in s, "safe remove error"
    s.remove(v)


def _safe_replace(d, k, v):
    assert d.get(k, None) is not None and v is not None, "safe replace error"
    d[k] = v


@dataclass
class TimelineState:
    running_hosts: Dict[AppId, HostApp] = field(default_factory=dict)
    running_sinks: Dict[AppId, SinkApp] = field(default_factory=dict)
    running_relays: Dict[AppId, RelayApp] = field(default_factory=dict)
    running_gateways: Dict[AppId, GatewayApp] = field(default_factory=dict)
    running_tunnels: List[Tunnel] = field(default_factory=list)

    multicast_routes: List = field(default_factory=list)

    def schedule(self, app):
        if isinstance(app, HostApp):
            _safe_assign(self.running_hosts, app.id, app)
        if isinstance(app, SinkApp):
            _safe_assign(self.running_sinks, app.id, app)
        if isinstance(app, GatewayApp):
            _safe_assign(self.running_gateways, app.id, app)

    def shutdown(self, app):
        if isinstance(app, HostApp):
            _safe_delete(self.running_hosts, app.id)
        if isinstance(app, SinkApp):
            _safe_delete(self.running_sinks, app.id)

    def join(self, host_id: AppId, sink_id: AppId):
        host = self.running_hosts[host_id]
        sinks = copy.deepcopy(host.sinks)
        _safe_append(sinks, sink_id)
        host = replace(host, sinks=sinks)
        _safe_replace(self.running_hosts, host_id, host)

    def leave(self, host_id: AppId, sink_id: AppId):
        host = self.running_hosts[host_id]
        sinks = copy.deepcopy(host.sinks)
        _safe_remove(sinks, sink_id)
        host = replace(host, sinks=sinks)
        _safe_replace(self.running_hosts, host_id, host)

    def bind(self, gateway_id: AppId, sink_id: AppId):
        gateway = self.running_gateways[gateway_id]
        sinks = copy.deepcopy(gateway.sinks)
        _safe_append(sinks, sink_id)
        gateway = replace(gateway, sinks=sinks)
        _safe_replace(self.running_gateways, gateway.id, gateway)

    def unbind(self, gateway_id: AppId, sink_id: AppId):
        gateway = self.running_gateways[gateway_id]
        sinks = copy.deepcopy(gateway.sinks)
        _safe_remove(sinks, sink_id)
        gateway = replace(gateway, sinks=sinks)
        if not sinks:
            tunnel = self._find_tunnel(gateway_id=gateway_id)
            relay_id = tunnel.relay_id
            _safe_delete(self.running_gateways, gateway.id)
            _safe_delete(self.running_relays, relay_id)
            _safe_remove(self.running_tunnels, tunnel)
        else:
            _safe_replace(self.running_gateways, gateway.id, gateway)

    def spawn_gateway(self, gateway_node: None) -> GatewayApp:
        gateway = create_gateway(gateway_node)
        _safe_assign(self.running_gateways, gateway.id, gateway)
        return gateway

    def spawn_relay(self, relay_node: Node) -> RelayApp:
        relay = create_relay(relay_node)
        _safe_assign(self.running_relays, relay.id, relay)
        return relay

    def connect(self, host_id: AppId, gateway_id: AppId, relay_id: AppId, sink_id: AppId):
        gateway = self.running_gateways[gateway_id]
        sinks = copy.deepcopy(gateway.sinks)
        _safe_append(sinks, sink_id)
        gateway = replace(gateway, sinks=sinks)

        _safe_replace(self.running_gateways, gateway_id, gateway)
        _safe_append(self.running_tunnels, Tunnel(host_id, relay_id, gateway_id))

    def _find_tunnel(self, relay_id: AppId | None = None, gateway_id: AppId | None = None) -> Tunnel:
        for tunnel in self.running_tunnels:
            if tunnel.gateway_id == gateway_id or tunnel.relay_id == relay_id:
                return tunnel
        else:
            raise KeyError()


@dataclass
class TimelineAction:
    schedule_hosts: Dict[AppId, HostApp] = field(default_factory=dict)
    schedule_sinks: Dict[AppId, SinkApp] = field(default_factory=dict)
    shutdown_hosts: Dict[AppId, HostApp] = field(default_factory=dict)
    shutdown_sinks: Dict[AppId, SinkApp] = field(default_factory=dict)

    def schedule(self, app):
        if isinstance(app, HostApp):
            _safe_assign(self.schedule_hosts, app.id, app)
        elif isinstance(app, SinkApp):
            _safe_assign(self.schedule_sinks, app.id, app)
        else:
            raise TypeError()

    def shutdown(self, app):
        if isinstance(app, HostApp):
            _safe_assign(self.shutdown_hosts, app.id, app)
        elif isinstance(app, SinkApp):
            _safe_assign(self.shutdown_sinks, app.id, app)
        else:
            raise TypeError()


@dataclass
class Timeline:
    time: float = -1.0
    action: TimelineAction = field(default_factory=TimelineAction)
    snapshot: TimelineState = field(default_factory=TimelineState)

    def schedule(self, app):
        self.action.schedule(app)

    def shutdown(self, app):
        self.action.shutdown(app)
