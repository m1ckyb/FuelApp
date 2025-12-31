"""InfluxDB client for storing fuel price data."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from influxdb_client import InfluxDBClient, Point, WriteOptions
from influxdb_client.client.write_api import SYNCHRONOUS

from fuel_data import StationPriceData

_LOGGER = logging.getLogger(__name__)


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
            timestamp = datetime.utcnow()
            
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
