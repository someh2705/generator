from dataclasses import dataclass
from generator import AppConfig, Node, Address
from typing import NewType, List, TypeVar

AppId = NewType("AppId", str)


@dataclass
class HostApp:
    id: AppId
    node: Node
    address: Address
    sinks: List[AppId]


@dataclass
class SinkApp:
    id: AppId
    node: Node
    address: Address


@dataclass
class RelayApp:
    id: AppId
    node: Node
    source_id: AppId


@dataclass
class GatewayApp:
    id: AppId
    node: Node
    relay_id: AppId
    sinks: List[AppId]


@dataclass
class Tunnel:
    source_id: AppId
    relay_id: AppId
    gateway_id: AppId


counter = 0


def _create_id(prefix: str) -> AppId:
    global counter
    counter += 1
    return AppId(f"{prefix}#{counter}")


def create_host(app: AppConfig) -> HostApp:
    id = _create_id("host")
    return HostApp(id, app.node, app.address, [])


def create_sink(app: AppConfig) -> SinkApp:
    id = _create_id("sink")
    return SinkApp(id, app.node, app.address)


def create_relay(node: Node, source_id: AppId) -> RelayApp:
    id = _create_id("relay")
    return RelayApp(id, node, source_id)


def create_gateway(node: Node, relay_id: AppId) -> GatewayApp:
    id = _create_id("gateway")
    return GatewayApp(id, node, relay_id, [])


def create_tunnel(source_id: AppId, relay_id: AppId, gateway_id: AppId) -> Tunnel:
    return Tunnel(source_id, relay_id, gateway_id)


AppType = TypeVar("AppType", HostApp, SinkApp, RelayApp, GatewayApp)
