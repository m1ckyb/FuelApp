"""Data models and data fetching for NSW Fuel Station."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Optional

from nsw_fuel import FuelCheckClient, FuelCheckError, Station

_LOGGER = logging.getLogger(__name__)


@dataclass
class StationPriceData:
    """Data structure for O(1) price and name lookups."""

    stations: dict[int, Station]
    prices: dict[tuple[int, str], float]


class FuelDataFetcher:
    """Fetches fuel price data from NSW FuelCheck API."""

    def __init__(self):
        """Initialize the fuel data fetcher."""
        self.client = FuelCheckClient()
        _LOGGER.info("FuelDataFetcher initialized")

    def fetch_station_price_data(self) -> Optional[StationPriceData]:
        """Fetch fuel price and station data."""
        try:
            _LOGGER.info("Fetching fuel price data from NSW FuelCheck API")
            raw_price_data = self.client.get_fuel_prices()
            
            # Restructure prices and station details to be indexed by station code
            # for O(1) lookup
            station_data = StationPriceData(
                stations={s.code: s for s in raw_price_data.stations},
                prices={
                    (p.station_code, p.fuel_type): p.price 
                    for p in raw_price_data.prices
                },
            )
            
            _LOGGER.info(
                "Fetched data for %d stations with %d price points",
                len(station_data.stations),
                len(station_data.prices)
            )
            return station_data

        except FuelCheckError as exc:
            _LOGGER.error("Failed to fetch NSW Fuel station price data: %s", exc)
            return None
        except Exception as exc:
            _LOGGER.exception("Unexpected error fetching fuel data: %s", exc)
            return None

