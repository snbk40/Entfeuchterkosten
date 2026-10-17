"""Entfeuchterkosten: the electricity costs of a dehumidifier in Home Assistant."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_POWER_ENTITY, CONF_PRICE, CONF_SOLAR_ENTITY
from .tracker import EntfeuchterkostenConfigEntry, PowerTracker

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(
    hass: HomeAssistant, entry: EntfeuchterkostenConfigEntry
) -> bool:
    """Set up the integration from a config entry."""
    settings = {**entry.data, **entry.options}
    tracker = PowerTracker(
        hass,
        settings[CONF_POWER_ENTITY],
        float(settings[CONF_PRICE]),
        settings.get(CONF_SOLAR_ENTITY) or None,
    )
    entry.runtime_data = tracker

    # The sensors first restore their values, then counting begins.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    tracker.async_start()
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: EntfeuchterkostenConfigEntry
) -> bool:
    """Unload a config entry, keeping everything counted up to now."""
    entry.runtime_data.async_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(
    hass: HomeAssistant, entry: EntfeuchterkostenConfigEntry
) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)
