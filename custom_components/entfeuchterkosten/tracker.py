"""Follows the power sensor and feeds its readings into the cost meter."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .const import LOGGER, UPDATE_INTERVAL
from .cost import POWER_UNITS, CostMeter, to_watts

type EntfeuchterkostenConfigEntry = ConfigEntry[PowerTracker]


class PowerTracker:
    """Counts the energy and costs of one dehumidifier while it is set up."""

    def __init__(
        self,
        hass: HomeAssistant,
        power_entity: str,
        price: float,
        solar_entity: str | None = None,
    ) -> None:
        """Initialise the tracker; counting begins with async_start."""
        self.hass = hass
        self.power_entity = power_entity
        self.solar_entity = solar_entity
        self.meter = CostMeter(price=price, now=dt_util.now())
        self._listeners: list[CALLBACK_TYPE] = []
        self._unsubscribe: list[CALLBACK_TYPE] = []
        self._warned_units: dict[str, str] = {}

    @callback
    def async_add_listener(self, update: CALLBACK_TYPE) -> Callable[[], None]:
        """Call `update` whenever the values change; return a remover."""
        self._listeners.append(update)
        return lambda: self._listeners.remove(update)

    @callback
    def async_start(self) -> None:
        """Begin with the current readings and follow every change."""
        entities = [self.power_entity]
        if self.solar_entity is not None:
            entities.append(self.solar_entity)
        self._unsubscribe = [
            async_track_state_change_event(
                self.hass, entities, self._async_state_changed
            ),
            async_track_time_interval(self.hass, self._async_tick, UPDATE_INTERVAL),
            # A new day starts exactly at midnight, not up to a minute later.
            async_track_time_change(
                self.hass, self._async_tick, hour=0, minute=0, second=0
            ),
        ]
        now = dt_util.now()
        if self.solar_entity is not None:
            self.meter.set_solar_power(
                self._watts(self.solar_entity, self.hass.states.get(self.solar_entity)),
                now,
            )
        self.meter.set_power(
            self._watts(self.power_entity, self.hass.states.get(self.power_entity)),
            now,
        )
        self._notify()

    @callback
    def async_stop(self) -> None:
        """Count up to now and stop following the power sensors."""
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe = []
        self.meter.advance(dt_util.now())
        self._notify()

    @callback
    def _async_state_changed(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        watts = self._watts(entity_id, event.data["new_state"])
        if entity_id == self.solar_entity:
            self.meter.set_solar_power(watts, dt_util.now())
        else:
            self.meter.set_power(watts, dt_util.now())
        self._notify()

    @callback
    def _async_tick(self, _now: datetime) -> None:
        self.meter.advance(dt_util.now())
        self._notify()

    def _watts(self, entity_id: str, state: State | None) -> float | None:
        """Return the reading of a power sensor in watts, if it can be used."""
        if state is None:
            return None
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        if (
            unit is not None
            and unit not in POWER_UNITS
            and self._warned_units.get(entity_id) != unit
        ):
            LOGGER.warning(
                "%s has the unit %s, but only %s are supported",
                entity_id,
                unit,
                ", ".join(POWER_UNITS),
            )
            self._warned_units[entity_id] = unit
        return to_watts(state.state, unit)

    def _notify(self) -> None:
        for update in list(self._listeners):
            update()
