"""Constants for Entfeuchterkosten."""

from __future__ import annotations

from datetime import timedelta
import logging

DOMAIN = "entfeuchterkosten"
MODEL = "Entfeuchterkosten"

LOGGER = logging.getLogger(__package__)

CONF_NAME = "name"
CONF_POWER_ENTITY = "power_entity"
CONF_PRICE = "price"
CONF_SOLAR_ENTITY = "solar_entity"

DEFAULT_NAME = "Entfeuchter"
DEFAULT_PRICE = 0.30  # per kWh
MAX_PRICE = 10.0

# Counts on between state changes of the power sensor, so that a constant
# power still shows up in the costs.
UPDATE_INTERVAL = timedelta(minutes=1)
