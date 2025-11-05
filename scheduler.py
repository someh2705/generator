from icecream import ic
import copy
from typing import Dict, Callable
from timeline import Timeline, TimelineState, TimelineAction
from dataclasses import replace
from collections import defaultdict
from application import create_host, create_sink


class ScenarioScheduler:
    def __init__(self, application):
        self.application = application

    def process(self, func: Callable[[TimelineState, TimelineAction], TimelineState]) -> Dict[float, Timeline]:
        history: Dict[float, Timeline] = {}
        state = TimelineState()

        for event in self._schedule():
            state = func(copy.deepcopy(state), event.action)
            history[event.time] = replace(event, snapshot=state)

        return history

    def _schedule(self):
        timeline: Dict[float, Timeline] = defaultdict(Timeline)

        for config in self.application:
            if config.type == "OnOff":
                app = create_host(config)

            elif config.type == "PacketSink":
                app = create_sink(config)

            else:
                raise NameError()

            timeline[config.start].time = config.start
            timeline[config.start].schedule(app)
            timeline[config.stop].time = config.stop
            timeline[config.stop].shutdown(app)

        return sorted(timeline.values(), key=lambda t: t.time)
