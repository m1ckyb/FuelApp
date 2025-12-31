"""Data handling for NSW Fuel Station App."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
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


class InfluxDBWriter:
    """Writes fuel price data to InfluxDB."""

    def __init__(
        self,
        url: str,
        token: str,
        org: str,
        bucket: str
    ):
        """Initialize the InfluxDB writer."""
        self.url = url
        self.token = token
        self.org = org
        self.bucket = bucket
        self.client: Optional[InfluxDBClient] = None
        self.write_api = None
        
        _LOGGER.info(
            "InfluxDB writer initialized for %s/%s",
            url, bucket
        )

    def connect(self) -> bool:
        """Connect to InfluxDB."""
        try:
            self.client = InfluxDBClient(
                url=self.url,
                token=self.token,
                org=self.org
            )
            self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
            
            # Test the connection
            health = self.client.health()
            if health.status == "pass":
                _LOGGER.info("Successfully connected to InfluxDB")
                return True
            else:
                _LOGGER.error("InfluxDB health check failed: %s", health.message)
                return False
                
        except Exception as exc:
            _LOGGER.error("Failed to connect to InfluxDB: %s", exc)
            return False

    def write_fuel_prices(
        self,
        data: StationPriceData,
        station_ids: list[int],
        fuel_types_by_station: dict[int, list[str]]
    ) -> bool:
        """
        Write fuel price data to InfluxDB.
        
        Args:
            data: StationPriceData containing all prices and stations
            station_ids: List of station IDs to write
            fuel_types_by_station: Dict mapping station_id to list of fuel types
            
        Returns:
            True if successful, False otherwise
        """
        if not self.client or not self.write_api:
            _LOGGER.error("InfluxDB client not connected")
            return False

        try:
            points = []
            timestamp = datetime.now(timezone.utc)
            
            for station_id in station_ids:
                station = data.stations.get(station_id)
                if not station:
                    _LOGGER.warning("Station %d not found in data", station_id)
                    continue
                
                fuel_types = fuel_types_by_station.get(station_id, [])
                
                for fuel_type in fuel_types:
                    price = data.prices.get((station_id, fuel_type))
                    
                    if price is None:
                        _LOGGER.debug(
                            "Price not available for station %d, fuel type %s",
                            station_id,
                            fuel_type
                        )
                        continue
                    
                    # Create InfluxDB point
                    point = (
                        Point("fuel_price")
                        .tag("station_id", str(station_id))
                        .tag("station_name", station.name)
                        .tag("station_address", station.address)
                        .tag("fuel_type", fuel_type)
                        .field("price", float(price))
                        .time(timestamp)
                    )
                    points.append(point)
                    
                    _LOGGER.debug(
                        "Prepared point: station=%s, fuel=%s, price=%.1f",
                        station.name,
                        fuel_type,
                        price
                    )
            
            if not points:
                _LOGGER.warning("No valid price points to write")
                return False
            
            # Write all points to InfluxDB
            self.write_api.write(bucket=self.bucket, record=points)
            _LOGGER.info("Successfully wrote %d price points to InfluxDB", len(points))
            return True
            
        except Exception as exc:
            _LOGGER.error("Failed to write data to InfluxDB: %s", exc)
            return False

    def close(self):
        """Close the InfluxDB connection."""
        if self.client:
            self.client.close()
            _LOGGER.info("InfluxDB connection closed")
