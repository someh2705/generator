from dataclasses import dataclass
from generator import AppConfig, Node
from typing import NewType, List, TypeVar

AppId = NewType("AppId", str)


@dataclass
class HostApp:
    id: AppId
    node: Node


@dataclass
class SinkApp:
    id: AppId
    node: Node


@dataclass
class RelayApp:
    id: AppId
    node: Node


@dataclass
class GatewayApp:
    id: AppId
    node: Node
    sinks: List[AppId]


counter = 0


def _create_id(prefix: str) -> AppId:
    global counter
    counter += 1
    return f"{prefix}#{counter}"


def create_host(app: AppConfig) -> HostApp:
    id = _create_id("host")
    return HostApp(id, app.node)


def create_sink(app: AppConfig) -> SinkApp:
    id = _create_id("sink")
    return SinkApp(id, app.node)


def create_relay(node: Node) -> RelayApp:
    id = _create_id("relay")
    return RelayApp(id, node)


def create_gateway(node: Node) -> GatewayApp:
    id = _create_id("gateway")
    return GatewayApp(id, node, [])


AppType = TypeVar("AppType", HostApp, SinkApp, RelayApp, GatewayApp)
