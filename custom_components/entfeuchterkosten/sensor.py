"""The energy, cost and chargeable power sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import ATTR_LAST_RESET, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN, MODEL
from .cost import CostMeter, Period
from .tracker import EntfeuchterkostenConfigEntry, PowerTracker


@dataclass(frozen=True, kw_only=True)
class EntfeuchterkostenSensorDescription(SensorEntityDescription):
    """Describes a sensor that shows a running total of the cost meter."""

    value_fn: Callable[[CostMeter], float]
    # Adds a value kept from before a restart; the periods use their last reset.
    restore_fn: Callable[[CostMeter, float], None] | None = None
    period: Period | None = None  # the total starts again at zero after it


def _cost(key: str, **kwargs: Any) -> dict[str, Any]:
    return {
        "key": key,
        "translation_key": key,
        "device_class": SensorDeviceClass.MONETARY,
        "state_class": SensorStateClass.TOTAL,
        "suggested_display_precision": 2,
        **kwargs,
    }


def _add_total_cost(meter: CostMeter, value: float) -> None:
    meter.total_cost += value


def _add_total_kwh(meter: CostMeter, value: float) -> None:
    meter.total_kwh += value


SENSORS: tuple[EntfeuchterkostenSensorDescription, ...] = (
    EntfeuchterkostenSensorDescription(
        **_cost("cost_today", period=Period.DAY),
        value_fn=lambda meter: meter.periods[Period.DAY].cost,
    ),
    EntfeuchterkostenSensorDescription(
        **_cost("cost_month", period=Period.MONTH),
        value_fn=lambda meter: meter.periods[Period.MONTH].cost,
    ),
    EntfeuchterkostenSensorDescription(
        **_cost("cost_year", period=Period.YEAR),
        value_fn=lambda meter: meter.periods[Period.YEAR].cost,
    ),
    EntfeuchterkostenSensorDescription(
        **_cost("cost_total"),
        value_fn=lambda meter: meter.total_cost,
        restore_fn=_add_total_cost,
    ),
    EntfeuchterkostenSensorDescription(
        key="energy_total",
        translation_key="energy_total",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=3,
        value_fn=lambda meter: meter.total_kwh,
        restore_fn=_add_total_kwh,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EntfeuchterkostenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the sensors of a config entry."""
    async_add_entities(
        [
            *(EntfeuchterkostenSensor(entry, description) for description in SENSORS),
            ChargeablePowerSensor(entry),
        ]
    )


def _device_info(entry: EntfeuchterkostenConfigEntry) -> DeviceInfo:
    """Return the device all sensors of a config entry belong to."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        model=MODEL,
        entry_type=DeviceEntryType.SERVICE,
    )


class ChargeablePowerSensor(SensorEntity):
    """The power of the dehumidifier that is not covered by solar power."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "chargeable_power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_suggested_display_precision = 0

    def __init__(self, entry: EntfeuchterkostenConfigEntry) -> None:
        """Initialise the sensor."""
        self._tracker: PowerTracker = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_chargeable_power"
        self._attr_device_info = _device_info(entry)

    async def async_added_to_hass(self) -> None:
        """Update with every change of the power sensors."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._tracker.async_add_listener(self.async_write_ha_state)
        )

    @property
    def native_value(self) -> float | None:
        """Return the chargeable power, or None while the power is unknown."""
        watts = self._tracker.meter.chargeable_watts
        return None if watts is None else round(watts, 1)


class EntfeuchterkostenSensor(RestoreSensor):
    """A running total, kept across restarts of Home Assistant."""

    entity_description: EntfeuchterkostenSensorDescription

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        entry: EntfeuchterkostenConfigEntry,
        description: EntfeuchterkostenSensorDescription,
    ) -> None:
        """Initialise the sensor."""
        self.entity_description = description
        self._tracker: PowerTracker = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = _device_info(entry)
        if description.device_class is SensorDeviceClass.MONETARY:
            self._attr_native_unit_of_measurement = (
                entry.runtime_data.hass.config.currency
            )

    async def async_added_to_hass(self) -> None:
        """Continue from the value before the last restart or reload."""
        await super().async_added_to_hass()
        last = await self.async_get_last_sensor_data()
        if last is not None and isinstance(last.native_value, int | float | Decimal):
            value = float(last.native_value)
            restore_fn = self.entity_description.restore_fn
            if self.entity_description.period is not None:
                await self._restore_period(value)
            elif restore_fn is not None:
                restore_fn(self._tracker.meter, value)
        self.async_on_remove(
            self._tracker.async_add_listener(self.async_write_ha_state)
        )

    async def _restore_period(self, value: float) -> None:
        """Keep the value only if its day, month or year is still running."""
        assert self.entity_description.period is not None
        last_state = await self.async_get_last_state()
        if last_state is None:
            return
        last_reset = dt_util.parse_datetime(
            str(last_state.attributes.get(ATTR_LAST_RESET, ""))
        )
        if last_reset is not None:
            self._tracker.meter.restore_period(
                self.entity_description.period, value, last_reset
            )

    @property
    def native_value(self) -> float:
        """Return the current total."""
        return round(self.entity_description.value_fn(self._tracker.meter), 6)

    @property
    def last_reset(self) -> datetime | None:
        """Return when the current day, month or year began."""
        period = self.entity_description.period
        if period is None:
            return None
        return self._tracker.meter.periods[period].start
