"""Data handling for NSW Fuel Station App."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Any

import aiohttp
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from nsw_tas_fuel import NSWFuelApiClient, NSWFuelApiClientError, Station

_LOGGER = logging.getLogger(__name__)

_SAFE_INFLUX_IDENT = re.compile(r'^[A-Za-z0-9_.\-]{1,128}$')


def is_safe_influx_identifier(value: str) -> bool:
    """Validate InfluxDB bucket/org identifiers to prevent Flux query injection."""
    if not value or not isinstance(value, str):
        return False
    return bool(_SAFE_INFLUX_IDENT.match(value.strip()))


@dataclass
class CachedStation:
    """Lightweight station representation reconstructed from InfluxDB/SQLite."""

    code: int
    name: str
    address: str
    au_state: str = "NSW"


@dataclass
class CachedPrice:
    """Lightweight price representation reconstructed from InfluxDB."""

    station_code: int
    fuel_type: str
    price: float
    last_updated: Any


@dataclass
class StationPriceData:
    """Data structure for O(1) price and name lookups."""

    stations: dict[int, Any] = field(default_factory=dict)
    prices: dict[tuple[int, str], Any] = field(default_factory=dict)


class FuelDataFetcher:
    """Fetches fuel price data from NSW FuelCheck API."""

    def __init__(self, client_id: str = "", client_secret: str = ""):
        """Initialize the fuel data fetcher."""
        self.client_id = client_id
        self.client_secret = client_secret
        _LOGGER.info("FuelDataFetcher initialized")

    def fetch_station_price_data(self, config_stations: list[dict] = None) -> Optional[StationPriceData]:
        """Fetch fuel price and station data.
        
        Args:
            config_stations: List of station configurations from config. 
                            If None, fetches bulk data for both NSW and TAS.
        """
        
        async def _fetch():
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                client = NSWFuelApiClient(
                    session=session,
                    client_id=self.client_id,
                    client_secret=self.client_secret
                )
                
                # Identify which states we have
                if config_stations is not None:
                    states = {s.get('au_state', 'NSW') for s in config_stations}
                else:
                    states = {'NSW', 'TAS'}
                
                stations_map: dict[int, Station] = {}
                prices_list: list[Any] = []
                
                # 1. Fetch reference data to get Station objects for all required states
                for state in states:
                    try:
                        ref_data = await client.get_reference_data(states=[state])
                        for s in ref_data.stations:
                            stations_map[s.code] = s
                    except Exception as e:
                        _LOGGER.error("Failed to fetch reference data for %s: %s", state, e)

                # 2. Fetch prices
                # For NSW, we can use the bulk API (default)
                if 'NSW' in states:
                    try:
                        nsw_data = await client.get_fuel_prices()
                        prices_list.extend(nsw_data.prices)
                        # Also merge any stations we might have missed
                        for s in nsw_data.stations:
                            stations_map[s.code] = s
                    except Exception as e:
                        _LOGGER.error("Failed to fetch bulk NSW prices: %s", e)
                
                # For other states (like TAS), we fetch per station or bulk if possible.
                # Currently the library defaults bulk price fetch to NSW only.
                if 'TAS' in states:
                    tas_stations = []
                    if config_stations is not None:
                        tas_stations = [s for s in config_stations if s.get('au_state') == 'TAS']
                    else:
                        # If we want ALL TAS prices, we'd need to fetch them.
                        # Since we can't bulk fetch TAS prices easily with the current client,
                        # and lookups are usually for a single ID, we'll try to fetch the 
                        # specific station if it was in our config, or skip bulk for now.
                        pass
                    
                    if tas_stations:
                        tasks = [
                            client.get_fuel_prices_for_station(
                                str(s['station_id']), 
                                'TAS'
                            ) for s in tas_stations
                        ]
                        results = await asyncio.gather(*tasks, return_exceptions=True)
                        
                        for i, res in enumerate(results):
                            if isinstance(res, Exception):
                                _LOGGER.error(
                                    "Failed to fetch prices for TAS station %s: %s", 
                                    tas_stations[i]['station_id'], res
                                )
                            else:
                                prices_list.extend(res)
                
                return stations_map, prices_list

        try:
            _LOGGER.info("Fetching fuel price data from NSW/TAS Fuel API")
            stations_map, prices_list = asyncio.run(_fetch())
            
            # Restructure prices for O(1) lookup
            station_data = StationPriceData(
                stations=stations_map,
                prices={
                    (p.station_code, p.fuel_type): p
                    for p in prices_list
                },
            )
            
            _LOGGER.info(
                "Fetched data for %d stations with %d price points",
                len(station_data.stations),
                len(station_data.prices)
            )
            return station_data

        except NSWFuelApiClientError as exc:
            _LOGGER.error("Failed to fetch fuel station price data: %s", exc)
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

    def get_last_prices(self) -> dict[tuple[int, str], float]:
        """
        Fetch the last recorded prices for all stations/fuel types.
        
        Returns:
            Dict mapping (station_id, fuel_type) to last price
        """
        if not self.client:
            _LOGGER.error("InfluxDB client not connected")
            return {}

        if not is_safe_influx_identifier(self.bucket):
            _LOGGER.error("Refusing Flux query with unsafe bucket name")
            return {}

        try:
            query_api = self.client.query_api()
            
            # Query for the last price of each station/fuel type in the last 30 days
            query = f'from(bucket: "{self.bucket}")'
            query += ' |> range(start: -30d)'
            query += ' |> filter(fn: (r) => r._measurement == "fuel_price")'
            query += ' |> filter(fn: (r) => r._field == "price")'
            query += ' |> last()'
            
            tables = query_api.query(query)
            
            last_prices = {}
            for table in tables:
                for record in table.records:
                    sid = record.values.get('station_id')
                    ft = record.values.get('fuel_type')
                    price = record.get_value()
                    
                    if sid and ft:
                        try:
                            sid = int(sid)
                            last_prices[(sid, ft)] = price
                        except ValueError:
                            pass
                            
            return last_prices
            
        except Exception as exc:
            _LOGGER.error("Failed to fetch last prices: %s", exc)
            return {}

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
                    price_obj = data.prices.get((station_id, fuel_type))
                    
                    if price_obj is None:
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
                        .field("price", float(price_obj.price))
                        .time(timestamp)
                    )
                    points.append(point)
                    
                    _LOGGER.debug(
                        "Prepared point: station=%s, fuel=%s, price=%.1f",
                        station.name,
                        fuel_type,
                        price_obj.price
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

    def write_average_prices(self, averages: dict[str, float]) -> bool:
        """Write average fuel prices to InfluxDB as a virtual station (ID 0)."""
        if not self.client or not self.write_api or not averages:
            return False
            
        try:
            points = []
            timestamp = datetime.now(timezone.utc)
            for fuel_type, avg_price in averages.items():
                point = (
                    Point("fuel_price")
                    .tag("station_id", "0")
                    .tag("station_name", "Average Prices")
                    .tag("station_address", "Global")
                    .tag("fuel_type", fuel_type)
                    .field("price", float(avg_price))
                    .time(timestamp)
                )
                points.append(point)
                
            self.write_api.write(bucket=self.bucket, record=points)
            return True
        except Exception as exc:
            _LOGGER.error("Failed to write average prices to InfluxDB: %s", exc)
            return False

    def close(self):
        """Close the InfluxDB client connection."""
        if self.client:
            try:
                self.client.close()
            except Exception as exc:
                _LOGGER.warning("Error closing InfluxDB client: %s", exc)
            finally:
                self.client = None
                self.write_api = None


class InfluxDBReader:
    """Reusable InfluxDB read client for web workers (avoids per-request connection pools)."""

    def __init__(self):
        self._client: Optional[InfluxDBClient] = None
        self._sig: Optional[tuple[str, str, str]] = None

    def _get_client(self, url: str, token: str, org: str) -> InfluxDBClient:
        sig = (url, token, org)
        if self._client is None or self._sig != sig:
            self.close()
            self._client = InfluxDBClient(url=url, token=token, org=org)
            self._sig = sig
        return self._client

    def close(self):
        if self._client is not None:
            try:
                self._client.close()
            except Exception as exc:
                _LOGGER.warning("Error closing InfluxDBReader client: %s", exc)
            finally:
                self._client = None
                self._sig = None

    def get_current_and_recent_prices(
        self,
        url: str,
        token: str,
        org: str,
        bucket: str,
        stations_list: list[dict],
        lookback_days: int = 30,
    ) -> tuple[StationPriceData, dict[tuple[int, str], list[float]]]:
        """Fetch latest prices and up to 50 recent price points per series."""
        data = StationPriceData()
        last_prices: dict[tuple[int, str], list[float]] = {}

        if not is_safe_influx_identifier(bucket):
            _LOGGER.error("Refusing Flux query with unsafe bucket name")
            return data, last_prices

        discounts_by_station = {s['station_id']: s.get('discount', 0.0) for s in stations_list}
        states_by_station = {s['station_id']: s.get('au_state', 'NSW') for s in stations_list}

        client = self._get_client(url, token, org)
        query_api = client.query_api()

        query = (
            f'from(bucket: "{bucket}")'
            f' |> range(start: -{int(lookback_days)}d)'
            ' |> filter(fn: (r) => r._measurement == "fuel_price")'
            ' |> filter(fn: (r) => r._field == "price")'
            ' |> sort(columns: ["_time"], desc: true)'
            ' |> limit(n: 50)'
        )

        tables = query_api.query(query)
        for table in tables:
            for record in table.records:
                sid = record.values.get('station_id')
                ft = record.values.get('fuel_type')
                price = record.get_value()
                sname = record.values.get('station_name') or f"Station {sid}"
                saddr = record.values.get('station_address') or ""

                if sid and ft:
                    try:
                        sid_int = int(sid)
                        key = (sid_int, ft)
                        if key not in last_prices:
                            last_prices[key] = []
                            if sid_int not in data.stations:
                                data.stations[sid_int] = CachedStation(
                                    code=sid_int,
                                    name=sname,
                                    address=saddr,
                                    au_state=states_by_station.get(sid_int, 'NSW'),
                                )
                            # InfluxDB stores discounted price; reconstruct raw price for downstream
                            discount = discounts_by_station.get(sid_int, 0.0)
                            raw_price = price + discount
                            data.prices[key] = CachedPrice(sid_int, ft, raw_price, record.get_time())
                        last_prices[key].append(price)
                    except ValueError:
                        pass

        return data, last_prices

    def get_price_history(
        self,
        url: str,
        token: str,
        org: str,
        bucket: str,
        days: int,
        station_id: Optional[int] = None,
        fuel_type: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Query historical price series with automatic downsampling on broad >30d ranges."""
        if not is_safe_influx_identifier(bucket):
            raise ValueError("Invalid InfluxDB bucket name")

        client = self._get_client(url, token, org)
        query_api = client.query_api()

        filters = ['r._measurement == "fuel_price"']
        if station_id is not None:
            filters.append(f'r.station_id == "{int(station_id)}"')
        if fuel_type:
            filters.append(f'r.fuel_type == "{fuel_type}"')

        filter_expr = ' and '.join(filters)
        query = (
            f'from(bucket: "{bucket}") |> range(start: -{int(days)}d)'
            f' |> filter(fn: (r) => {filter_expr})'
            ' |> filter(fn: (r) => r._field == "price")'
        )
        if days > 30 and station_id is None and not fuel_type:
            query += ' |> aggregateWindow(every: 6h, fn: mean, createEmpty: false)'
        query += ' |> sort(columns: ["_time"])'

        tables = query_api.query(query)
        history = []
        for table in tables:
            for record in table.records:
                history.append({
                    'time': record.get_time().isoformat(),
                    'price': record.get_value(),
                    'station_id': record.values.get('station_id'),
                    'fuel_type': record.values.get('fuel_type'),
                })
        return history